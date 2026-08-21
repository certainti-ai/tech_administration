"""
Resolving a project fiscal, and deciding ``is_last_fiscal``.

That flag is the whole reason this file is long. It decides whether deleting one
fiscal year also deletes the project row and recomputes the account-level
financial totals. Getting it wrong in one direction leaves an orphaned project
row; getting it wrong in the other destroys a project that still has years in it.
"""

from __future__ import annotations

from fakes import AccountDirectory, FakeConnection, FakePool, table

from trd365_data_purge.engine import SchemaCache
from trd365_data_purge.project_fiscal import resolve

ACCOUNT_RID = "ACCT-1"
R_NUMBER = "ACC-00042"
SCHEMA = "trd365_00042"
PROJECT_RID = "P001-project-1"
FISCAL_RID = "P001-fiscal-2025"


def org(**tables):
    return FakeConnection({(SCHEMA, name): t for name, t in tables.items()})


def pool_with(org_conn):
    return FakePool(
        {
            "maindb": AccountDirectory({ACCOUNT_RID: (R_NUMBER, "store_in_own", None)}),
            "orgdb": org_conn,
        }
    )


def fiscal_rows(*years):
    """A project_fiscal table holding one row per year given."""
    return table(
        ["rid", "project_rid", "fiscal_year"],
        [
            {
                "rid": FISCAL_RID if year == 2025 else f"P001-fiscal-{year}",
                "project_rid": PROJECT_RID,
                "fiscal_year": year,
            }
            for year in years
        ],
    )


def resolved(*years, force_last=None, fiscal_rid=FISCAL_RID):
    pool = pool_with(org(project_fiscal=fiscal_rows(*years)))
    return resolve.resolve_fiscal(
        pool,
        SchemaCache(),
        account_ref=R_NUMBER,
        fiscal_rid=fiscal_rid,
        force_last=force_last,
    )


# ---------------------------------------------------------------------------
# is_last_fiscal
# ---------------------------------------------------------------------------


class TestIsLastFiscal:
    def test_the_only_fiscal_of_a_project_is_the_last_one(self):
        found = resolved(2025)
        assert found.siblings == 1
        assert found.is_last is True
        assert found.decided_by == "counted"

    def test_one_of_several_is_not_the_last_one(self):
        # The project survives and its rollups are recomputed to exclude this year.
        found = resolved(2023, 2024, 2025)
        assert found.siblings == 3
        assert found.is_last is False

    def test_an_operator_can_force_it_on(self):
        # The case this exists for: a sibling fiscal was already deleted by a run
        # that failed partway, so the count now says "not last" when it is.
        found = resolved(2024, 2025, force_last=True)
        assert found.is_last is True
        assert found.decided_by == "forced"

    def test_an_operator_can_force_it_off(self):
        found = resolved(2025, force_last=False)
        assert found.is_last is False
        assert found.decided_by == "forced"

    def test_forcing_against_the_count_is_recorded_for_the_report(self):
        # "The tool decided" and "a human insisted" have to be different things to
        # read afterwards, because only one of them is worth asking about.
        found = resolved(2024, 2025, force_last=True)
        assert found.notes
        assert "forced to True" in found.notes[0]
        assert "2 fiscal(s)" in found.notes[0]

    def test_forcing_to_agree_with_the_count_is_not_worth_a_note(self):
        found = resolved(2025, force_last=True)
        assert found.notes == []


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


class TestResolution:
    def test_the_project_and_year_are_looked_up_from_the_fiscal(self):
        found = resolved(2023, 2025)
        assert found.exists is True
        assert found.project_rid == PROJECT_RID
        assert found.year == 2025
        assert found.org_schema == SCHEMA

    def test_an_unknown_fiscal_does_not_resolve(self):
        found = resolved(2025, fiscal_rid="P001-nope")
        assert found.exists is False

    def test_an_unknown_account_does_not_resolve(self):
        pool = pool_with(org(project_fiscal=fiscal_rows(2025)))
        found = resolve.resolve_fiscal(
            pool, SchemaCache(), account_ref="ACC-99999", fiscal_rid=FISCAL_RID
        )
        assert found.exists is False
        assert found.account.exists is False

    def test_a_schema_without_the_table_does_not_resolve(self):
        pool = pool_with(org())
        found = resolve.resolve_fiscal(
            pool, SchemaCache(), account_ref=R_NUMBER, fiscal_rid=FISCAL_RID
        )
        assert found.exists is False
        assert found.org_schema == SCHEMA


class TestSectionParameters:
    def test_every_value_the_sections_declare_is_supplied(self):
        params = resolved(2023, 2025).params
        assert params == {
            "schema_name": SCHEMA,
            "account_rid": ACCOUNT_RID,
            "project_rid": PROJECT_RID,
            "project_fiscal_id": FISCAL_RID,
            "fiscal_year": 2025,
            "is_last_fiscal": False,
        }

    def test_the_parameters_satisfy_the_real_vendor_sql(self):
        # The end of the chain: what resolution produces has to be exactly what
        # substitution needs, or prepare() refuses and the two halves were never
        # actually connected.
        from trd365_data_purge import sections
        from trd365_data_purge.project_fiscal import BACKUP_SCHEMA, BASE_SQL

        params = resolved(2023, 2025).params
        for section in sections.discover(BASE_SQL):
            sections.prepare(section, params, BACKUP_SCHEMA)  # must not raise

    def test_a_missing_year_is_passed_as_absent_not_as_null(self):
        # The sections declare v_fiscal_year INT. An absent value has to read as
        # absent so prepare() reports it, rather than substituting a blank and
        # producing `v_fiscal_year INT := ;`.
        pool = pool_with(
            org(
                project_fiscal=table(
                    ["rid", "project_rid", "fiscal_year"],
                    [{"rid": FISCAL_RID, "project_rid": PROJECT_RID, "fiscal_year": None}],
                )
            )
        )
        found = resolve.resolve_fiscal(
            pool, SchemaCache(), account_ref=R_NUMBER, fiscal_rid=FISCAL_RID
        )
        assert found.params["fiscal_year"] == ""


# ---------------------------------------------------------------------------
# a whole project
# ---------------------------------------------------------------------------


class TestProject:
    def project_pool(self, *years, code=None):
        columns = ["rid", "account_rid"] + (["project_code"] if code else [])
        row = {"rid": PROJECT_RID, "account_rid": ACCOUNT_RID}
        if code:
            row["project_code"] = code
        return pool_with(
            org(project=table(columns, [row]), project_fiscal=fiscal_rows(*years))
        )

    def test_a_project_is_resolved_by_rid(self):
        pool = self.project_pool(2023, 2024, 2025)
        _, project_rid, fiscals = resolve.resolve_project(
            pool, SchemaCache(), account_ref=R_NUMBER, project_ref=PROJECT_RID
        )
        assert project_rid == PROJECT_RID
        assert [f.year for f in fiscals] == [2023, 2024, 2025]

    def test_a_project_can_also_be_resolved_by_its_code(self):
        pool = self.project_pool(2025, code="Infosys FY25 Project 1")
        _, project_rid, _ = resolve.resolve_project(
            pool, SchemaCache(), account_ref=R_NUMBER, project_ref="Infosys FY25 Project 1"
        )
        assert project_rid == PROJECT_RID

    def test_an_unknown_project_resolves_to_nothing(self):
        pool = self.project_pool(2025)
        _, project_rid, fiscals = resolve.resolve_project(
            pool, SchemaCache(), account_ref=R_NUMBER, project_ref="not-a-project"
        )
        assert project_rid is None
        assert fiscals == []

    def test_only_the_final_fiscal_carries_is_last(self):
        # This is what removes the project row and recomputes the account totals.
        # Deleting a project deletes every fiscal, so the last one processed
        # genuinely is the last remaining — which is why it can be decided up front
        # here and cannot be for a single-fiscal purge.
        pool = self.project_pool(2023, 2024, 2025)
        account, project_rid, fiscals = resolve.resolve_project(
            pool, SchemaCache(), account_ref=R_NUMBER, project_ref=PROJECT_RID
        )
        plan = resolve.plan_project_fiscals(account, project_rid, fiscals)
        assert [p["is_last_fiscal"] for p in plan] == [False, False, True]
        assert [p["fiscal_year"] for p in plan] == [2023, 2024, 2025]

    def test_the_oldest_fiscal_goes_first(self):
        # Order must not depend on how the database returned the rows: which
        # fiscal is last decides where the recompute happens.
        pool = self.project_pool(2025, 2023, 2024)
        account, project_rid, fiscals = resolve.resolve_project(
            pool, SchemaCache(), account_ref=R_NUMBER, project_ref=PROJECT_RID
        )
        plan = resolve.plan_project_fiscals(account, project_rid, fiscals)
        assert [p["fiscal_year"] for p in plan] == [2023, 2024, 2025]

    def test_a_single_fiscal_project_marks_its_only_fiscal_last(self):
        pool = self.project_pool(2025)
        account, project_rid, fiscals = resolve.resolve_project(
            pool, SchemaCache(), account_ref=R_NUMBER, project_ref=PROJECT_RID
        )
        plan = resolve.plan_project_fiscals(account, project_rid, fiscals)
        assert [p["is_last_fiscal"] for p in plan] == [True]

    def test_name_is_the_last_code_column_tried(self):
        # It is the least likely to be unique, and resolving a project by a
        # non-unique column would purge whichever row came back first.
        assert resolve.CODE_COLUMNS[-1] == "name"
