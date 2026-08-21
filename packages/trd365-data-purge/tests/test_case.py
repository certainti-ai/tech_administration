"""
The case sub-command: resolving a target into a plan, and the scoping rules that
decide which rows belong to the case.

The scoping tests are the ones that matter. A predicate that is too narrow leaves
rows behind, which is recoverable; a predicate that is too wide deletes another
case's data, which is not. So each test here pins the shape of the clause, not
just that one was produced.
"""

from __future__ import annotations

import pytest
from fakes import AccountDirectory, FakeConnection, FakePool, silent, table
from trd365_core.environments import Environment

from trd365_data_purge import cli
from trd365_data_purge.case import __main__ as case
from trd365_data_purge.case import manifest as M
from trd365_data_purge.case import scoping
from trd365_data_purge.checkpoint import Checkpoint, CheckpointStore
from trd365_data_purge.engine import SchemaCache

ACCOUNT_RID = "ACCT-1"
R_NUMBER = "ACC-00042"
SCHEMA = "trd365_00042"
CASE_RID = "P001-case-1"


def org_connection(**tables):
    return FakeConnection({(SCHEMA, name): t for name, t in tables.items()})


def pool_with(accounts, org=None):
    return FakePool(
        {
            "maindb": AccountDirectory(accounts),
            "orgdb": org if org is not None else org_connection(),
        }
    )


def one_account(org=None):
    return pool_with({ACCOUNT_RID: (R_NUMBER, "store_in_own", None)}, org)


def with_case(**extra):
    return org_connection(
        cases=table(["rid", "account_rid"], [{"rid": CASE_RID, "account_rid": ACCOUNT_RID}]),
        **extra,
    )


def context(pool, *, account_ref=R_NUMBER, saved=None) -> cli.ResolverContext:
    class Namespace:
        case_rid = CASE_RID

    namespace = Namespace()
    namespace.account_ref = account_ref

    return cli.ResolverContext(
        pool=pool,
        namespace=namespace,
        args=type("Args", (), {"env": Environment.DEV, "apply": True})(),
        cache=SchemaCache(),
        log=silent,
        saved=saved,
        model=None,
    )


def scoper_for(org):
    pool = one_account(org)
    cache = SchemaCache()
    resolved = scoping.resolve_case(pool, cache, R_NUMBER, CASE_RID)
    return scoping.CaseScoper(case=resolved, cache=cache), pool.get("orgdb")


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


class TestResolution:
    def test_an_account_can_be_named_by_its_reference_number(self):
        plan = case.resolve(context(one_account(with_case())))
        assert plan.schema_for["org"] == SCHEMA
        assert plan.resolved["account_rid"] == ACCOUNT_RID

    def test_an_account_can_also_be_named_by_its_rid(self):
        plan = case.resolve(context(one_account(with_case()), account_ref=ACCOUNT_RID))
        assert plan.schema_for["org"] == SCHEMA

    def test_the_plan_covers_the_org_schema_and_the_main_schema(self):
        plan = case.resolve(context(one_account(with_case())))
        assert plan.steps is M.STEPS
        assert plan.schema_for == {"org": SCHEMA, "main": M.MAIN_SCHEMA}
        assert plan.entity_rid == CASE_RID

    def test_a_store_in_parent_account_purges_inside_the_parents_schema(self):
        # The case's rows physically live in the parent's schema; pointing the
        # purge at a schema of its own would find nothing and report success.
        pool = pool_with(
            {
                ACCOUNT_RID: ("ACC-00099", "store_in_parent", "PARENT"),
                "PARENT": (R_NUMBER, "store_in_own", None),
            },
            with_case(),
        )
        plan = case.resolve(context(pool, account_ref=ACCOUNT_RID))
        assert plan.schema_for["org"] == SCHEMA

    def test_an_unknown_account_says_so_rather_than_blaming_the_case(self):
        with pytest.raises(cli.TargetNotFound, match="no account matches"):
            case.resolve(context(pool_with({}), account_ref="ACC-99999"))

    def test_a_case_in_a_different_tenants_schema_does_not_resolve(self):
        # The rid exists somewhere, but not in this account's schema. Resolving it
        # anyway would run the whole manifest against the wrong tenant.
        pool = one_account(org_connection(cases=table(["rid", "account_rid"], [])))
        with pytest.raises(cli.TargetNotFound, match="belongs to a different account"):
            case.resolve(context(pool))

    def test_the_expected_unscoped_tables_are_stated_up_front(self):
        # Three manifest tables never scope. Saying so in the plan means the report
        # reads as "as expected" rather than "eighty things need review".
        plan = case.resolve(context(one_account(with_case())))
        assert any("case_timeline_old" in note for note in plan.notes)


class TestResuming:
    def test_a_run_that_already_deleted_the_case_row_resumes_from_the_checkpoint(self):
        # `cases` is the last table of the FIRST step, so a run interrupted before
        # the main step cannot resolve itself again. Being told the case "does not
        # exist" would strand its main-schema rows forever.
        saved = Checkpoint(
            entity="case",
            entity_rid=CASE_RID,
            environment="dev",
            run_id="run-1",
            resolved={"org_schema": SCHEMA, "account_rid": ACCOUNT_RID, "r_number": R_NUMBER},
        )
        pool = one_account(org_connection(cases=table(["rid", "account_rid"], [])))
        plan = case.resolve(context(pool, saved=saved))
        assert plan.schema_for["org"] == SCHEMA

    def test_a_checkpoint_without_a_schema_is_not_enough_to_resume(self):
        saved = Checkpoint(
            entity="case", entity_rid=CASE_RID, environment="dev", run_id="run-1", resolved={}
        )
        pool = one_account(org_connection(cases=table(["rid", "account_rid"], [])))
        with pytest.raises(cli.TargetNotFound):
            case.resolve(context(pool, saved=saved))


# ---------------------------------------------------------------------------
# scoping
# ---------------------------------------------------------------------------


class TestScoping:
    def test_the_anchor_is_scoped_by_its_own_primary_key(self):
        scoper, conn = scoper_for(with_case())
        assert scoper.predicate(conn, SCHEMA, "cases", "org") == ("rid = %s", [CASE_RID])

    def test_a_table_carrying_case_rid_is_scoped_by_it(self):
        scoper, conn = scoper_for(with_case(case_task=table(["rid", "case_rid"], [])))
        assert scoper.predicate(conn, SCHEMA, "case_task", "org") == ("case_rid = %s", [CASE_RID])

    def test_checklist_items_are_scoped_through_their_checklist(self):
        # checklist_items has no case_rid of its own; the checklist has.
        scoper, conn = scoper_for(
            with_case(
                checklists=table(["rid", "case_rid"], []),
                checklist_items=table(["rid", "checklist_rid"], []),
            )
        )
        sql, params = scoper.predicate(conn, SCHEMA, "checklist_items", "org")
        assert sql == (
            'checklist_rid IN (SELECT rid FROM "trd365_00042"."checklists" WHERE case_rid = %s)'
        )
        assert params == [CASE_RID]

    def test_checklist_items_scope_to_nothing_when_checklists_is_absent(self):
        # Not None: None means "we could not work this out, a human should look".
        # An absent parent is different — it is known that nothing can match.
        scoper, conn = scoper_for(with_case(checklist_items=table(["rid", "checklist_rid"], [])))
        assert scoper.predicate(conn, SCHEMA, "checklist_items", "org") == ("1=0", [])

    def test_a_table_reaches_the_case_through_a_foreign_key(self):
        scoper, conn = scoper_for(
            with_case(
                case_task=table(["rid", "case_rid"], []),
                case_task_dependency_mapping=table(
                    ["rid", "task_rid"], [], fks=[("task_rid", "case_task", "rid")]
                ),
            )
        )
        sql, params = scoper.predicate(conn, SCHEMA, "case_task_dependency_mapping", "org")
        assert sql == (
            '"task_rid" IN (SELECT "rid" FROM "trd365_00042"."case_task" WHERE case_rid = %s)'
        )
        assert params == [CASE_RID]

    def test_a_self_referencing_foreign_key_is_not_followed(self):
        # Following it would produce `parent_rid IN (SELECT rid FROM me WHERE
        # case_rid = ...)`, which is circular and, worse, plausible-looking.
        scoper, conn = scoper_for(
            with_case(
                case_task=table(
                    ["rid", "case_rid", "parent_rid"],
                    [],
                    fks=[("parent_rid", "case_task", "rid")],
                )
            )
        )
        sql, _ = scoper.predicate(conn, SCHEMA, "case_task", "org")
        assert sql == "case_rid = %s"

    def test_a_table_with_no_path_to_the_case_is_left_for_a_human(self):
        scoper, conn = scoper_for(with_case(case_timeline_old=table(["rid", "attach_to"], [])))
        assert scoper.predicate(conn, SCHEMA, "case_timeline_old", "org") is None

    def test_nothing_is_discovered_beyond_the_manifest(self):
        # Deliberate: a table that merely mentions case_rid is not necessarily
        # owned by the case, and widening the scope by guessing would delete rows
        # that should survive it.
        scoper, conn = scoper_for(with_case())
        assert scoper.discover(conn, SCHEMA, "org", M.ORG_TABLES) == []


class TestManifest:
    def test_the_anchor_is_deleted_last_in_the_org_step(self):
        assert M.ORG_TABLES[-1] == "cases"

    def test_children_come_before_the_tables_they_point_at(self):
        order = M.ORG_TABLES
        assert order.index("checklist_items") < order.index("checklists")
        assert order.index("case_task") < order.index("cases")

    def test_the_org_step_runs_before_the_main_step(self):
        assert [step[0] for step in M.STEPS] == ["org_delete", "main_delete"]
        assert [step[1] for step in M.STEPS] == ["orgdb", "maindb"]

    def test_every_expected_unscoped_table_is_actually_in_the_manifest(self):
        # They are listed on purpose so the engine reports them. If one were
        # dropped from the manifest it would vanish from the report as well, and
        # "we deliberately do not touch this" would become invisible.
        assert set(M.ORG_TABLES) >= M.KNOWN_UNSCOPED


# ---------------------------------------------------------------------------
# end to end, through the real sub-command
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """
    The real ``case`` sub-command driven through the real CLI, against fakes.

    The unit tests above cover the resolver and the predicates in isolation, which
    is where the logic lives — but between them and a working command sit the
    argument names, the flag the entity rid is read from, and the step list the
    engine is handed. Those are exactly the joints a rename breaks silently, so
    one run exercises all of them.
    """

    def run(self, extra_argv, tmp_path, org=None):
        pool = one_account(org if org is not None else with_case())
        code = cli.run(
            entity="case",
            description=case.DESCRIPTION,
            resolver=case.resolve,
            entity_rid=case.entity_rid,
            configure=case.configure,
            argv=[
                "--env", "dev",
                "--account-id", R_NUMBER,
                "--case-rid", CASE_RID,
                "--out-dir", str(tmp_path / "reports"),
                "--ignore-model",
                *extra_argv,
            ],
            pool_factory=lambda _env, log=None: pool,
            # Rooted in tmp_path on purpose. The default store writes outside the
            # test run, so a checkpoint left by one --apply makes the next one
            # resume and skip every table — passing once and failing for good.
            store=CheckpointStore(tmp_path / "state"),
        )
        return code, pool

    def test_a_dry_run_reports_the_case_row_without_deleting_it(self, tmp_path, capsys):
        code, pool = self.run([], tmp_path)
        assert code == 0
        conn = pool.get("orgdb")
        assert conn.live_rows(SCHEMA, "cases"), "a dry run must not delete anything"
        assert "DRY RUN" in capsys.readouterr().out.upper()

    def test_apply_deletes_the_case_row(self, tmp_path):
        code, pool = self.run(["--apply"], tmp_path)
        assert code == 0
        conn = pool.get("orgdb")
        assert conn.live_rows(SCHEMA, "cases") == []

    def test_a_missing_case_exits_with_the_not_found_code(self, tmp_path):
        code, _ = self.run(
            [], tmp_path, org=org_connection(cases=table(["rid", "account_rid"], []))
        )
        assert code == cli.EXIT_TARGET_NOT_FOUND

    def test_the_report_names_the_case_it_purged(self, tmp_path):
        self.run(["--apply"], tmp_path)
        reports = sorted((tmp_path / "reports").glob("*.json"))
        assert reports, "the run produced no report"
        assert CASE_RID.replace("-", "_") in reports[0].name or CASE_RID in reports[0].read_text()
