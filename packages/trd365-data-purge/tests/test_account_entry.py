"""
The account sub-command's own logic: resolving a target into a plan, and the
one case that is easy to get wrong — resuming a run that already deleted the
account row it would otherwise resolve itself from.
"""

from __future__ import annotations

import pytest
from fakes import AccountDirectory, FakeConnection, FakePool, silent, table
from trd365_core.environments import Environment

from trd365_data_purge import cli
from trd365_data_purge.account import __main__ as account
from trd365_data_purge.account import manifest as M
from trd365_data_purge.checkpoint import Checkpoint
from trd365_data_purge.engine import SchemaCache

RID = "ACCT-1"
SCHEMA = "trd365_00042"


def org_connection(**tables):
    return FakeConnection({(SCHEMA, name): t for name, t in tables.items()})


def context(pool, *, saved=None, model=None, namespace=None) -> cli.ResolverContext:
    class Namespace:
        account_rid = RID

    return cli.ResolverContext(
        pool=pool,
        namespace=namespace or Namespace(),
        args=type("Args", (), {"env": Environment.DEV, "apply": True})(),
        cache=SchemaCache(),
        log=silent,
        saved=saved,
        model=model,
    )


def pool_with(accounts, org=None):
    return FakePool(
        {
            "maindb": AccountDirectory(accounts),
            "orgdb": org if org is not None else org_connection(),
            "trd365ai": FakeConnection({}),
        }
    )


def test_resolving_produces_a_plan_covering_all_three_databases():
    pool = pool_with(
        {RID: ("ACC-00042", "store_in_own", None)},
        org_connection(
            cases=table(["rid", "account_rid"], [{"rid": "c1", "account_rid": RID}]),
            project_fiscal=table(["rid", "account_rid"], [{"rid": "f1", "account_rid": RID}]),
        ),
    )
    plan = account.resolve(context(pool))

    assert plan.entity_rid == RID
    assert plan.steps is M.STEPS
    assert plan.schema_for == {"org": SCHEMA, "main": M.MAIN_SCHEMA, "ai": M.AI_SCHEMA}
    assert plan.resolved["org_schema"] == SCHEMA
    assert plan.id_sets["project_fiscal"] == ["f1"]


def test_an_unknown_account_is_reported_as_not_found():
    with pytest.raises(cli.TargetNotFound, match="not in trd365.account"):
        account.resolve(context(pool_with({})))


def test_a_run_that_already_deleted_the_account_row_resumes_from_the_checkpoint():
    # The account row goes during the main step, before the ai step runs. A run
    # that died in between cannot resolve itself again, and must not be told the
    # account "does not exist" — that would strand the remaining rows forever.
    saved = Checkpoint(
        entity="account",
        entity_rid=RID,
        environment="dev",
        run_id="earlier",
        resolved={"org_schema": SCHEMA, "r_number": "ACC-00042"},
        id_sets={"project_fiscal": ["f1"], "cases": []},
    )
    plan = account.resolve(context(pool_with({}), saved=saved))

    assert plan.schema_for["org"] == SCHEMA
    assert plan.id_sets == {"project_fiscal": ["f1"], "cases": []}
    assert any("resumed after the account row" in note for note in plan.notes)


def test_a_checkpoint_without_id_sets_cannot_stand_in_for_the_account():
    # Without the id-sets there is no way to scope trd365ai, so resuming would
    # silently purge nothing there and report success.
    saved = Checkpoint(
        entity="account", entity_rid=RID, environment="dev", run_id="earlier",
        resolved={"org_schema": SCHEMA},
    )
    with pytest.raises(cli.TargetNotFound):
        account.resolve(context(pool_with({}), saved=saved))


def test_saved_id_sets_are_preferred_over_re_reading_them():
    # Re-reading after a partial purge returns a short set, which would leave
    # the corresponding trd365ai rows behind.
    saved = Checkpoint(
        entity="account", entity_rid=RID, environment="dev", run_id="earlier",
        resolved={"org_schema": SCHEMA},
        id_sets={"project_fiscal": ["f1", "f2"]},
    )
    pool = pool_with(
        {RID: ("ACC-00042", "store_in_own", None)},
        org_connection(project_fiscal=table(["rid", "account_rid"], [])),
    )
    plan = account.resolve(context(pool, saved=saved))

    assert plan.id_sets["project_fiscal"] == ["f1", "f2"]


def test_model_drift_is_noted_for_the_audit_trail():
    class Model:
        def schema(self, _name):
            class SchemaModel:
                table_names = set(M.ORG_TABLES)

            return SchemaModel()

        def tables_referencing(self, _schema, _entity):
            return ["brand_new"]

    pool = pool_with({RID: ("ACC-00042", "store_in_own", None)})
    plan = account.resolve(context(pool, model=Model()))

    assert any("brand_new" in note for note in plan.notes)


def test_the_scoper_is_wired_to_the_run_scoped_cache():
    pool = pool_with({RID: ("ACC-00042", "store_in_own", None)})
    ctx = context(pool)
    plan = account.resolve(ctx)

    assert plan.scoper.cache is ctx.cache
    assert plan.scoper.db_for == {"org": "orgdb", "main": "maindb", "ai": "trd365ai"}


def test_the_entity_rid_comes_from_the_account_flag():
    class Namespace:
        account_rid = "OTHER"

    assert account.entity_rid(Namespace()) == "OTHER"
