"""
The interaction sub-command.

The test that matters most here is ``test_chat_sessions_is_never_scoped``. Every
other rule in this file is about finding rows; that one is about *not* finding
them, and it is the only thing standing between a purge and deleting chat history
the interaction does not own.
"""

from __future__ import annotations

import pytest
from fakes import AccountDirectory, FakeConnection, FakePool, silent, table
from trd365_core.environments import Environment

from trd365_data_purge import cli
from trd365_data_purge.checkpoint import Checkpoint, CheckpointStore
from trd365_data_purge.engine import SchemaCache
from trd365_data_purge.interaction import __main__ as interaction
from trd365_data_purge.interaction import manifest as M
from trd365_data_purge.interaction import scoping

ACCOUNT_RID = "ACCT-1"
R_NUMBER = "ACC-00042"
SCHEMA = "trd365_00042"
RID = "P001-interaction-1"


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


def with_interaction(**extra):
    return org_connection(
        interactions=table(["rid", "account_rid"], [{"rid": RID, "account_rid": ACCOUNT_RID}]),
        **extra,
    )


def context(pool, *, account_ref=R_NUMBER, saved=None) -> cli.ResolverContext:
    class Namespace:
        interaction_rid = RID

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
    resolved = scoping.resolve_interaction(pool, cache, R_NUMBER, RID)
    return scoping.InteractionScoper(interaction=resolved, cache=cache), pool.get("orgdb")


# ---------------------------------------------------------------------------
# the exclusion
# ---------------------------------------------------------------------------


class TestChatSessionsIsNotOwned:
    def test_chat_sessions_is_not_in_the_manifest(self):
        assert "chat_sessions" not in M.ORG_TABLES
        assert "chat_sessions" not in M.MAIN_TABLES

    def test_chat_sessions_is_never_scoped_even_though_it_carries_the_column(self):
        # It has interaction_rid, so the ordinary rule would match it. It is only
        # safe because the manifest does not list it — this test is what stops a
        # future "discover tables with interaction_rid" from being added.
        scoper, conn = scoper_for(
            with_interaction(chat_sessions=table(["rid", "interaction_rid"], []))
        )
        assert scoper.discover(conn, SCHEMA, "org", M.ORG_TABLES) == []

    def test_foreign_keys_are_not_followed(self):
        # A table that reaches the interaction only through an FK is left for a
        # human rather than scoped, because the general rule that would catch it
        # would also catch chat_sessions.
        scoper, conn = scoper_for(
            with_interaction(
                interaction_items=table(["rid", "interaction_rid"], []),
                something_else=table(
                    ["rid", "item_rid"], [], fks=[("item_rid", "interaction_items", "rid")]
                ),
            )
        )
        assert scoper.predicate(conn, SCHEMA, "something_else", "org") is None

    def test_the_plan_says_what_it_will_not_touch(self):
        plan = interaction.resolve(context(one_account(with_interaction())))
        assert any("chat_sessions" in note for note in plan.notes)


# ---------------------------------------------------------------------------
# scoping
# ---------------------------------------------------------------------------


class TestScoping:
    def test_the_anchor_is_scoped_by_its_own_primary_key(self):
        scoper, conn = scoper_for(with_interaction())
        assert scoper.predicate(conn, SCHEMA, "interactions", "org") == ("rid = %s", [RID])

    def test_a_table_carrying_interaction_rid_is_scoped_by_it(self):
        scoper, conn = scoper_for(
            with_interaction(otp_entries=table(["rid", "interaction_rid"], []))
        )
        assert scoper.predicate(conn, SCHEMA, "otp_entries", "org") == (
            "interaction_rid = %s",
            [RID],
        )

    def test_the_timeline_is_scoped_by_its_generic_entity_column(self):
        scoper, conn = scoper_for(
            with_interaction(interaction_timeline=table(["rid", "entity_rid"], []))
        )
        assert scoper.predicate(conn, SCHEMA, "interaction_timeline", "org") == (
            "entity_rid = %s",
            [RID],
        )

    def test_response_history_is_reached_both_directly_and_through_the_item(self):
        # Both paths, not either: a row can carry one column and not the other.
        scoper, conn = scoper_for(
            with_interaction(
                interaction_items=table(["rid", "interaction_rid"], []),
                interaction_response_history=table(
                    ["rid", "interaction_rid", "interaction_item_rid"], []
                ),
            )
        )
        sql, params = scoper.predicate(conn, SCHEMA, "interaction_response_history", "org")
        assert sql == (
            "interaction_rid = %s OR interaction_item_rid IN "
            '(SELECT rid FROM "trd365_00042"."interaction_items" WHERE interaction_rid = %s)'
        )
        assert params == [RID, RID]

    def test_response_history_falls_back_to_the_direct_path_alone(self):
        # No interaction_items table in this schema: the second clause would be
        # invalid SQL, so it is not emitted at all.
        scoper, conn = scoper_for(
            with_interaction(
                interaction_response_history=table(["rid", "interaction_rid"], [])
            )
        )
        sql, params = scoper.predicate(conn, SCHEMA, "interaction_response_history", "org")
        assert sql == "interaction_rid = %s"
        assert params == [RID]

    def test_a_table_with_no_link_is_left_for_a_human(self):
        scoper, conn = scoper_for(with_interaction(mystery=table(["rid", "note"], [])))
        assert scoper.predicate(conn, SCHEMA, "mystery", "org") is None


# ---------------------------------------------------------------------------
# resolution and the manifest
# ---------------------------------------------------------------------------


class TestResolution:
    def test_the_plan_covers_the_org_schema_and_the_main_schema(self):
        plan = interaction.resolve(context(one_account(with_interaction())))
        assert plan.steps is M.STEPS
        assert plan.schema_for == {"org": SCHEMA, "main": M.MAIN_SCHEMA}
        assert plan.entity_rid == RID

    def test_an_unknown_account_says_so_rather_than_blaming_the_interaction(self):
        with pytest.raises(cli.TargetNotFound, match="no account matches"):
            interaction.resolve(context(pool_with({}), account_ref="ACC-99999"))

    def test_an_interaction_in_another_tenants_schema_does_not_resolve(self):
        pool = one_account(org_connection(interactions=table(["rid", "account_rid"], [])))
        with pytest.raises(cli.TargetNotFound, match="belongs to a different account"):
            interaction.resolve(context(pool))

    def test_a_run_that_already_deleted_the_anchor_resumes_from_the_checkpoint(self):
        saved = Checkpoint(
            entity="interaction",
            entity_rid=RID,
            environment="dev",
            run_id="run-1",
            resolved={"org_schema": SCHEMA, "account_rid": ACCOUNT_RID, "r_number": R_NUMBER},
        )
        pool = one_account(org_connection(interactions=table(["rid", "account_rid"], [])))
        plan = interaction.resolve(context(pool, saved=saved))
        assert plan.schema_for["org"] == SCHEMA


class TestManifest:
    def test_the_anchor_is_deleted_last_in_the_org_step(self):
        assert M.ORG_TABLES[-1] == "interactions"

    def test_children_come_before_the_tables_they_point_at(self):
        order = M.ORG_TABLES
        assert order.index("interaction_response_history") < order.index("interaction_items")
        assert order.index("otp_entries_history") < order.index("otp_entries")

    def test_the_org_step_runs_before_the_main_step(self):
        assert [step[1] for step in M.STEPS] == ["orgdb", "maindb"]


# ---------------------------------------------------------------------------
# end to end
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def run(self, extra_argv, tmp_path, org=None):
        pool = one_account(org if org is not None else with_interaction())
        code = cli.run(
            entity="interaction",
            description=interaction.DESCRIPTION,
            resolver=interaction.resolve,
            entity_rid=interaction.entity_rid,
            configure=interaction.configure,
            argv=[
                "--env", "dev",
                "--account-id", R_NUMBER,
                "--interaction-rid", RID,
                "--out-dir", str(tmp_path / "reports"),
                "--ignore-model",
                *extra_argv,
            ],
            pool_factory=lambda _env, log=None: pool,
            store=CheckpointStore(tmp_path / "state"),
        )
        return code, pool

    def test_a_dry_run_deletes_nothing(self, tmp_path):
        code, pool = self.run([], tmp_path)
        assert code == 0
        assert pool.get("orgdb").live_rows(SCHEMA, "interactions")

    def test_apply_deletes_the_interaction_row(self, tmp_path):
        code, pool = self.run(["--apply"], tmp_path)
        assert code == 0
        assert pool.get("orgdb").live_rows(SCHEMA, "interactions") == []

    def test_apply_leaves_chat_sessions_alone(self, tmp_path):
        org = with_interaction(
            chat_sessions=table(
                ["rid", "interaction_rid"], [{"rid": "s1", "interaction_rid": RID}]
            )
        )
        code, pool = self.run(["--apply"], tmp_path, org=org)
        assert code == 0
        assert pool.get("orgdb").live_rows(SCHEMA, "chat_sessions"), (
            "the conversation must outlive the interaction it was started from"
        )
