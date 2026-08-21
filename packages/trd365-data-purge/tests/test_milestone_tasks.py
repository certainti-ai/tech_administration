"""
The milestone-tasks utility.

This one is mostly about a script that used to be edited by hand. The tests worth
having are the ones covering what a human editing three variables in psql could
get wrong: the wrong tenant, a rid that belongs to somebody else, and a preview
that turns out not to be one.
"""

from __future__ import annotations

import json

from fakes import AccountDirectory, FakeConnection, FakePool, table
from trd365_core.audit import MemoryAuditSink

from trd365_data_purge import sections as S
from trd365_data_purge.milestone_tasks import BASE_SQL, VARIABLES
from trd365_data_purge.milestone_tasks import __main__ as milestone

ACCOUNT_RID = "ACCT-1"
R_NUMBER = "ACC-00042"
SCHEMA = "trd365_00042"
CASE_RID = "P001-case-1"
MILESTONE_RID = "P001-milestone-1"

PARAMS = {
    "schema": SCHEMA,
    "case_rid": CASE_RID,
    "milestone_rid": MILESTONE_RID,
    "dry_run": True,
}


# ---------------------------------------------------------------------------
# the identifier guard, against the real script
# ---------------------------------------------------------------------------


class TestTheShippedScript:
    def test_it_is_discovered_and_routed_to_the_org_database(self):
        found = S.discover(BASE_SQL)
        assert len(found) == 1
        assert found[0].db_key == "orgdb"

    def test_it_really_does_contain_live_identifiers(self):
        # The premise. This script shipped with a real tenant schema and a real
        # case rid in the three variables a human was told to edit.
        literals = set(S._IDENTIFIER_LITERAL.findall(S.discover(BASE_SQL)[0].read()))
        assert literals, "the script no longer carries baked-in identifiers"
        assert any(literal.startswith("trd365_") for literal in literals)

    def test_none_survive_substitution_in_executable_sql(self):
        # Scanned with comments stripped, which is the invariant that matters: the
        # script documents its own variables with example identifiers, and a comment
        # cannot execute. prepare() applies the same rule.
        prepared = S.prepare(S.discover(BASE_SQL)[0], PARAMS, "", VARIABLES)
        executable = S.strip_comments(prepared.sql)
        survivors = [
            found
            for found in S._IDENTIFIER_LITERAL.findall(executable)
            if found not in set(map(str, PARAMS.values()))
        ]
        assert not survivors, f"still contains {survivors}"

    def test_the_example_in_the_comment_is_what_makes_that_necessary(self):
        # If this stops being true the stripper is no longer earning its place.
        raw = S.discover(BASE_SQL)[0].read()
        assert "trd365_000001" in raw
        assert "trd365_000001" not in S.strip_comments(raw)

    def test_the_three_variables_are_all_substituted(self):
        prepared = S.prepare(S.discover(BASE_SQL)[0], PARAMS, "", VARIABLES)
        assert set(prepared.applied) >= {"v_schema", "v_case_rid", "v_milestone_rid", "dry_run"}

    def test_a_missing_value_is_refused(self):
        try:
            S.prepare(S.discover(BASE_SQL)[0], {**PARAMS, "case_rid": ""}, "", VARIABLES)
        except S.SectionError as exc:
            assert "no value supplied" in str(exc)
        else:
            raise AssertionError("a missing case rid must be refused")


class TestTheDryRunSwitch:
    """
    The script's own flag, which is why this utility's preview is genuinely free —
    unlike the project purges, which have to execute and roll back.
    """

    def test_a_preview_sets_the_scripts_flag_true(self):
        prepared = S.prepare(S.discover(BASE_SQL)[0], {**PARAMS, "dry_run": True}, "", VARIABLES)
        assert prepared.applied["dry_run"] is True
        assert "dry_run         BOOLEAN := TRUE" in prepared.sql

    def test_applying_sets_it_false(self):
        prepared = S.prepare(S.discover(BASE_SQL)[0], {**PARAMS, "dry_run": False}, "", VARIABLES)
        assert prepared.applied["dry_run"] is False
        assert "dry_run         BOOLEAN := FALSE" in prepared.sql

    def test_the_script_ships_set_to_delete(self):
        # Worth pinning: the file's own default is FALSE, i.e. it deletes. Anyone
        # who ran it as shipped got a deletion, not a preview. The runner always
        # substitutes, so that default never reaches the database.
        assert "dry_run         BOOLEAN := FALSE" in S.discover(BASE_SQL)[0].read()

    def test_the_registry_says_the_preview_is_free(self):
        from trd365_data_purge.registry import PURGE_MILESTONE_TASKS

        assert PURGE_MILESTONE_TASKS.dry_run_executes is False


class TestVariableSetsAreNotShared:
    def test_this_family_uses_v_schema_and_the_project_family_v_schema_name(self):
        # The reason the sets are per-family. One global table would let these two
        # names be substituted into each other's SQL.
        assert "v_schema" in VARIABLES.text
        assert "v_schema" not in S.PROJECT_VARIABLES.text
        assert "v_schema_name" in S.PROJECT_VARIABLES.text
        assert "v_schema_name" not in VARIABLES.text

    def test_the_project_family_is_still_the_default(self):
        from trd365_data_purge.project_fiscal import BACKUP_SCHEMA
        from trd365_data_purge.project_fiscal import BASE_SQL as PROJECT_SQL

        # No variables argument: the project sections must keep working untouched.
        for section in S.discover(PROJECT_SQL):
            S.prepare(
                section,
                {
                    "schema_name": SCHEMA,
                    "account_rid": "P001-a",
                    "project_rid": "P001-p",
                    "project_fiscal_id": "P001-f",
                    "fiscal_year": 2025,
                    "is_last_fiscal": False,
                },
                BACKUP_SCHEMA,
            )


# ---------------------------------------------------------------------------
# end to end
# ---------------------------------------------------------------------------


class SectionConnection(FakeConnection):
    """Swallows the one DO block; answers ordinary reads normally."""

    def __init__(self, tables=None):
        super().__init__(tables or {})
        self.notices = _Notices()
        self.ran: list[str] = []
        self.commits = 0

    def cursor(self):
        outer = self
        inner = super().cursor()

        class Cursor:
            _section = False

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_exc):
                return False

            def close(self_inner):
                inner.close()

            def execute(self_inner, sql, params=None):
                if sql.lstrip().startswith("--") or "DO $$" in sql:
                    self_inner._section = True
                    outer.ran.append(sql[:40])
                    return
                self_inner._section = False
                inner.execute(sql, params)

            @property
            def rowcount(self_inner):
                return inner.rowcount

            def fetchone(self_inner):
                return None if self_inner._section else inner.fetchone()

            def fetchall(self_inner):
                return [] if self_inner._section else inner.fetchall()

        return Cursor()

    def commit(self):
        self.commits += 1


class _Notices:
    def __init__(self):
        self.lines = ["NOTICE: DRY-RUN checklist_items 4"]

    def clear(self):
        pass

    def snapshot(self):
        return list(self.lines)

    @property
    def last(self):
        return self.lines[-1]


def org(*, has_case=True, has_milestone=True):
    tables = {
        (SCHEMA, "cases"): table(["rid"], [{"rid": CASE_RID}] if has_case else []),
        (SCHEMA, "case_milestone"): table(
            ["rid"], [{"rid": MILESTONE_RID}] if has_milestone else []
        ),
    }
    return SectionConnection(tables)


def invoke(tmp_path, extra=(), *, org_conn=None, sink=None):
    org_conn = org_conn if org_conn is not None else org()
    pool = FakePool(
        {
            "maindb": AccountDirectory({ACCOUNT_RID: (R_NUMBER, "store_in_own", None)}),
            "orgdb": org_conn,
        }
    )
    code = milestone.run(
        [
            "--env", "dev",
            "--account-id", R_NUMBER,
            "--case-rid", CASE_RID,
            "--milestone-rid", MILESTONE_RID,
            "--out-dir", str(tmp_path / "reports"),
            *extra,
        ],
        pool_factory=lambda _env, log=None: pool,
        audit_sink=sink or MemoryAuditSink(),
    )
    return code, org_conn


class TestEndToEnd:
    def test_a_dry_run_runs_the_script_without_committing(self, tmp_path):
        code, conn = invoke(tmp_path)
        assert code == 0
        assert conn.ran, "the script did not run"
        assert conn.commits == 0

    def test_applying_commits(self, tmp_path):
        code, conn = invoke(tmp_path, ["--apply", "--yes"])
        assert code == 0
        assert conn.commits == 1

    def test_a_case_from_another_tenant_is_refused(self, tmp_path, capsys):
        # The failure that looks most like success: a rid from elsewhere would be
        # substituted in, match nothing, and report a clean run.
        code, conn = invoke(tmp_path, org_conn=org(has_case=False))
        assert code == milestone.EXIT_TARGET_NOT_FOUND
        assert not conn.ran
        assert "case P001-case-1 is not in" in capsys.readouterr().out

    def test_an_unknown_milestone_is_refused(self, tmp_path, capsys):
        code, conn = invoke(tmp_path, org_conn=org(has_milestone=False))
        assert code == milestone.EXIT_TARGET_NOT_FOUND
        assert not conn.ran
        assert "milestone" in capsys.readouterr().out

    def test_the_scripts_notices_are_reported_and_kept(self, tmp_path, capsys):
        invoke(tmp_path)
        assert "DRY-RUN checklist_items 4" in capsys.readouterr().out
        report = json.loads(sorted((tmp_path / "reports").glob("*.json"))[-1].read_text())
        assert report["mode"] == "dry-run"
        assert any("checklist_items" in n for n in report["notices"])

    def test_the_run_is_audited(self, tmp_path):
        # The thing the SQL-in-psql version could never have: a record that it
        # happened, and to what.
        sink = MemoryAuditSink()
        invoke(tmp_path, ["--apply", "--yes"], sink=sink)
        assert len(sink.records) == 1
        assert sink.records[0].utility == "purge-milestone-tasks"
        assert sink.records[0].applied is True
