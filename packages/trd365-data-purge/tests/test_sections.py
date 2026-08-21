"""
The section runner.

Most of these tests run against the **real vendor SQL** shipped in
``project_fiscal/base_sql``, not against fixtures. That is deliberate: the whole
module is a set of regexes matched against files somebody else wrote, and a
fixture that happens to match my regexes proves only that I can write two things
that agree with each other.

The tests in ``TestNoVendorIdentifierSurvives`` are the ones that matter. Those
files contain a live tenant schema and live account and project rids, so a
substitution that fails to match does not fail loudly — it deletes somebody
else's data.
"""

from __future__ import annotations

import re

import pytest

from trd365_data_purge import sections
from trd365_data_purge.project_fiscal import BASE_SQL

PARAMS = {
    "schema_name": "trd365_00042",
    "account_rid": "P001-account-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "project_rid": "P001-project-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "project_fiscal_id": "P001-fiscal-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "fiscal_year": 2025,
    "is_last_fiscal": False,
}
BACKUP = "data_purge"


def all_sections():
    return sections.discover(BASE_SQL)


# ---------------------------------------------------------------------------
# the check this module exists for
# ---------------------------------------------------------------------------


class TestNoVendorIdentifierSurvives:
    """
    The vendor SQL is not a template with placeholders. It is a working script
    with real identifiers in it, last run against tenant trd365_01379.
    """

    def test_the_shipped_sql_really_does_contain_live_identifiers(self):
        # If this ever fails, the premise of the whole module changed and the rest
        # of these tests are checking something that no longer needs checking.
        found = set()
        for section in all_sections():
            found |= set(sections._IDENTIFIER_LITERAL.findall(section.read()))
        assert found, "the vendor SQL no longer carries baked-in identifiers"
        assert any(f.startswith("trd365_") for f in found)
        assert any(re.match(r"[A-Z]\d{3}-", f) for f in found)

    def test_every_section_is_clean_after_substitution(self):
        for section in all_sections():
            prepared = sections.prepare(section, PARAMS, BACKUP)
            survivors = [
                found
                for found in sections._IDENTIFIER_LITERAL.findall(prepared.sql)
                if found not in set(PARAMS.values()) | {BACKUP}
            ]
            assert not survivors, f"{section.name} still contains {survivors}"

    def test_a_renamed_declaration_is_refused_rather_than_ignored(self, tmp_path):
        # The failure mode this exists to catch. The vendor renames a variable, the
        # regex stops matching, and the file keeps its own account rid — so the
        # section runs, succeeds, and deletes the wrong account's fiscal year.
        sql = tmp_path / "01_x_ORGDB_SECTION1.sql"
        sql.write_text(
            "DO $$ DECLARE\n"
            "  v_schema_name TEXT := 'trd365_01379';\n"
            "  v_acct_rid    TEXT := 'D001-4bf2b0a2-f11c-4941-b075-82e8682a1e20';\n"
            "BEGIN END $$;\n"
        )
        section = sections.discover(tmp_path)[0]
        with pytest.raises(sections.SectionError, match="still in this SQL"):
            sections.prepare(section, PARAMS, BACKUP)

    def test_an_identifier_in_the_body_is_caught_too(self, tmp_path):
        # Not only declarations: a rid used directly in a WHERE clause would be
        # just as dangerous and is not something substitution would reach.
        sql = tmp_path / "02_x_ORGDB_SECTION2.sql"
        sql.write_text(
            "DO $$ DECLARE\n"
            "  v_schema_name TEXT := 'trd365_01379';\n"
            "BEGIN\n"
            "  DELETE FROM project WHERE rid = 'D001-a9fc5b2a-8a2d-4895-bd28-817ae0b51f33';\n"
            "END $$;\n"
        )
        section = sections.discover(tmp_path)[0]
        with pytest.raises(sections.SectionError, match="D001-a9fc5b2a"):
            sections.prepare(section, PARAMS, BACKUP)

    def test_the_error_says_what_to_look_at(self, tmp_path):
        sql = tmp_path / "01_x_ORGDB_SECTION1.sql"
        sql.write_text("DO $$ DECLARE v_other TEXT := 'trd365_01379'; BEGIN END $$;")
        section = sections.discover(tmp_path)[0]
        with pytest.raises(sections.SectionError) as raised:
            sections.prepare(section, PARAMS, BACKUP)
        message = str(raised.value)
        assert "trd365_01379" in message
        assert "renamed" in message


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_the_shipped_sections_are_found_in_order(self):
        found = all_sections()
        assert [s.number for s in found] == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_each_section_is_routed_to_the_database_its_name_says(self):
        routing = {s.number: s.db_key for s in all_sections()}
        assert routing == {
            1: "orgdb",
            2: "orgdb",
            3: "maindb",
            4: "orgdb",
            5: "maindb",
            6: "trd365ai",
            7: "trd365ai",
            8: "trd365ai",
        }

    def test_a_file_that_does_not_name_a_database_is_an_error(self, tmp_path):
        # Better than guessing: SECTION 3 run against the org database would find
        # none of its tables and cheerfully report that everything was gone.
        (tmp_path / "09_delete_SECTION9.sql").write_text("SELECT 1;")
        with pytest.raises(sections.SectionError, match="which database"):
            sections.discover(tmp_path)

    def test_a_file_that_does_not_name_a_section_is_an_error(self, tmp_path):
        (tmp_path / "cleanup_ORGDB.sql").write_text("SELECT 1;")
        with pytest.raises(sections.SectionError, match="which section"):
            sections.discover(tmp_path)

    def test_an_empty_directory_is_an_error(self, tmp_path):
        with pytest.raises(sections.SectionError, match="no .sql files"):
            sections.discover(tmp_path)


# ---------------------------------------------------------------------------
# substitution
# ---------------------------------------------------------------------------


class TestSubstitution:
    def test_the_run_values_reach_every_declaration_that_wants_them(self):
        prepared = sections.prepare(all_sections()[0], PARAMS, BACKUP)
        assert prepared.applied["v_schema_name"] == PARAMS["schema_name"]
        assert prepared.applied["v_account_rid"] == PARAMS["account_rid"]
        assert prepared.applied["v_project_rid"] == PARAMS["project_rid"]
        assert f"'{PARAMS['schema_name']}'" in prepared.sql

    def test_one_backup_schema_is_forced_into_every_section(self):
        # Sections 2-8 declare it as a pasted literal; SECTION 1 computes a
        # timestamped name. Both are overridden, so one run has one backup schema
        # across all three databases.
        for section in all_sections():
            prepared = sections.prepare(section, PARAMS, BACKUP)
            assert prepared.applied.get("v_backup_schema") == BACKUP, section.name
            assert "backup_release" not in prepared.sql.replace(
                "-- ", ""
            ) or f"'{BACKUP}'" in prepared.sql

    def test_section_ones_computed_name_is_overridden_not_appended(self):
        prepared = sections.prepare(all_sections()[0], PARAMS, BACKUP)
        assert re.search(r"v_backup_schema\s*:=\s*'data_purge';", prepared.sql)

    def test_a_missing_value_is_refused(self):
        # The section declares v_account_rid; running with it left at the vendor's
        # value is exactly what must not happen, so an absent value is an error
        # rather than a skipped substitution.
        params = dict(PARAMS)
        params["account_rid"] = ""
        with pytest.raises(sections.SectionError, match="no value supplied for"):
            sections.prepare(all_sections()[0], params, BACKUP)

    def test_a_quote_in_a_value_cannot_break_out_of_its_literal(self):
        params = dict(PARAMS) | {"schema_name": "trd365_00042'; DROP SCHEMA public; --"}
        # The identifier check would also fire, so aim at the escaping directly.
        assert sections._sql_literal(params["schema_name"]) == (
            "'trd365_00042''; DROP SCHEMA public; --'"
        )

    def test_the_fiscal_year_goes_in_as_a_number(self):
        # Sections 3 and 5 declare v_fiscal_year INT. Quoting it would be a type
        # error inside the DO block rather than a silent wrong answer, but a wrong
        # number would not be, so pin it.
        for section in all_sections():
            prepared = sections.prepare(section, PARAMS, BACKUP)
            if "v_fiscal_year" in prepared.applied:
                assert re.search(r"v_fiscal_year\s+INT\s*:=\s*2025", prepared.sql)

    def test_is_last_fiscal_is_a_real_boolean_not_a_string(self):
        # This flag decides whether the project row itself is deleted. "False" as a
        # non-empty string is truthy in the wrong hands.
        false = sections.prepare(all_sections()[0], PARAMS | {"is_last_fiscal": "false"}, BACKUP)
        true = sections.prepare(all_sections()[0], PARAMS | {"is_last_fiscal": "yes"}, BACKUP)
        assert false.applied["v_is_last_fiscal"] is False
        assert true.applied["v_is_last_fiscal"] is True
        assert re.search(r"v_is_last_fiscal\s+BOOLEAN\s*:=\s*FALSE", false.sql)
        assert re.search(r"v_is_last_fiscal\s+BOOLEAN\s*:=\s*TRUE", true.sql)

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "t", "yes", "Y"])
    def test_truthy_spellings(self, value):
        assert sections.as_bool(value) is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "", "n", None, "maybe"])
    def test_everything_else_is_false(self, value):
        assert sections.as_bool(value) is False


class TestBackupSchemaAnnouncement:
    def test_the_announced_name_is_read_out_of_the_notices(self):
        notices = [
            "NOTICE: starting",
            "NOTICE: backup schema for this run = backup_release_v5_3_3_20260723_083409",
            "NOTICE: done",
        ]
        assert sections.announced_backup_schema(notices) == (
            "backup_release_v5_3_3_20260723_083409"
        )

    def test_nothing_announced_is_not_an_error(self):
        # The caller decides what to do; it has a name of its own to fall back on.
        assert sections.announced_backup_schema(["NOTICE: nothing to report"]) is None
