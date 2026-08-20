"""
Scoping decides which rows belong to the account. It is the part of a purge
that, when wrong, deletes somebody else's data — so these tests assert on the
SQL and parameters produced, not on the effect of running them.
"""

from __future__ import annotations

import pytest
from fakes import AccountDirectory, FakeConnection, FakePool, table

from trd365_data_purge.account import manifest as M
from trd365_data_purge.account import scoping
from trd365_data_purge.engine import SchemaCache

RID = "ACCT-1"


def org(**tables):
    return FakeConnection({("trd365_00042", name): t for name, t in tables.items()})


def scoper(conn=None, sets=None, model=None, db_for=None):
    account = scoping.ResolvedAccount(
        rid=RID, exists=True, r_number="ACC-00042", org_schema="trd365_00042"
    )
    return scoping.AccountScoper(
        account=account,
        sets=sets or {},
        cache=SchemaCache(),
        db_for=db_for or scoping.DB_FOR_KIND,
        model=model,
    )


# ------------------------------------------------------------------- resolve


def test_resolve_account_that_does_not_exist():
    pool = FakePool({"maindb": AccountDirectory({})})
    resolved = scoping.resolve_account(pool, RID)
    assert resolved.exists is False
    assert resolved.org_schema == ""


def test_resolve_account_uses_its_own_reference_number():
    pool = FakePool({"maindb": AccountDirectory({RID: ("ACC-00042", "store_in_own", None)})})
    resolved = scoping.resolve_account(pool, RID)
    assert resolved.exists is True
    assert resolved.org_schema == "trd365_00042"


def test_store_in_parent_resolves_to_the_parents_schema():
    # Its rows live in the parent's schema, distinguished only by account_rid.
    # Getting this wrong points the purge at the wrong tenant entirely.
    pool = FakePool(
        {
            "maindb": AccountDirectory(
                {
                    RID: ("ACC-00099", "store_in_parent", "PARENT-1"),
                    "PARENT-1": ("ACC-00042", "store_in_own", None),
                }
            )
        }
    )
    resolved = scoping.resolve_account(pool, RID)
    assert resolved.org_schema == "trd365_00042"
    assert resolved.parent_rid == "PARENT-1"


def test_store_in_parent_with_a_missing_parent_falls_back_to_its_own():
    pool = FakePool(
        {"maindb": AccountDirectory({RID: ("ACC-00099", "store_in_parent", "GONE")})}
    )
    assert scoping.resolve_account(pool, RID).org_schema == "trd365_00099"


# ---------------------------------------------------------------- id capture


def test_capture_id_sets_reads_the_sets_the_later_steps_need():
    conn = org(
        cases=table(["rid", "account_rid"], [{"rid": "c1", "account_rid": RID}]),
        project=table(["rid", "account_rid"], [{"rid": "p1", "account_rid": RID}]),
        project_fiscal=table(
            ["rid", "account_rid"],
            [{"rid": "f1", "account_rid": RID}, {"rid": "f2", "account_rid": "OTHER"}],
        ),
        resources=table(["rid", "account_rid"], []),
        interactions=table(["rid", "account_rid"], [{"rid": "i1", "account_rid": RID}]),
    )
    account = scoping.ResolvedAccount(rid=RID, exists=True, org_schema="trd365_00042")

    sets = scoping.capture_id_sets(FakePool({"orgdb": conn}), SchemaCache(), account)

    assert sets["cases"] == ["c1"]
    assert sets["project_fiscal"] == ["f1"]
    assert sets["interactions"] == ["i1"]
    # Absent tables are empty sets, not errors.
    assert sets["project_task"] == []
    assert sets["checklists"] == []


# ------------------------------------------------------------- the predicate


def test_a_table_with_account_rid_is_scoped_directly():
    conn = org(project=table(["rid", "account_rid"]))
    where, params = scoper().predicate(conn, "trd365_00042", "project", "org")
    assert where == "account_rid = %s"
    assert params == [RID]


def test_a_table_is_reached_through_a_foreign_key_to_a_scoped_parent():
    conn = org(
        project=table(["rid", "account_rid"]),
        project_history=table(["rid", "project_rid"], fks=[("project_rid", "project", "rid")]),
    )
    where, params = scoper().predicate(conn, "trd365_00042", "project_history", "org")
    assert where == (
        '"project_rid" IN (SELECT "rid" FROM "trd365_00042"."project" WHERE account_rid = %s)'
    )
    assert params == [RID]


def test_an_unambiguous_rid_column_falls_back_to_its_known_parent():
    # No declared foreign key, but case_rid can only mean one thing.
    conn = org(
        cases=table(["rid", "account_rid"]),
        checklist_items=table(["rid", "case_rid"]),
    )
    where, params = scoper().predicate(conn, "trd365_00042", "checklist_items", "org")
    assert where == (
        '"case_rid" IN (SELECT rid FROM "trd365_00042"."cases" WHERE account_rid = %s)'
    )
    assert params == [RID]


def test_project_rid_alone_is_not_enough_to_scope_a_table():
    # project_rid means a project in some tables and a project fiscal in others.
    # Guessing would scope a delete by an unrelated row's identifier.
    assert "project_rid" not in scoping.FALLBACK_PARENTS


def test_a_table_that_cannot_be_tied_to_the_account_returns_none():
    conn = org(mystery=table(["rid", "label"]))
    assert scoper().predicate(conn, "trd365_00042", "mystery", "org") is None


def test_conditions_are_combined_with_or_not_and():
    # A row qualifies if *any* link ties it to the account. Requiring all of them
    # would leave rows behind whenever one link is null.
    conn = org(
        project=table(["rid", "account_rid"]),
        thing=table(
            ["rid", "account_rid", "project_rid"], fks=[("project_rid", "project", "rid")]
        ),
    )
    where, params = scoper().predicate(conn, "trd365_00042", "thing", "org")
    assert where.startswith("account_rid = %s OR ")
    assert params == [RID, RID]


def test_a_self_referencing_foreign_key_is_ignored():
    conn = org(
        node=table(["rid", "account_rid", "parent_rid"], fks=[("parent_rid", "node", "rid")])
    )
    where, _params = scoper().predicate(conn, "trd365_00042", "node", "org")
    assert where == "account_rid = %s"


# ------------------------------------------------------- special predicates


def test_timeline_tables_are_reached_through_the_row_they_attach_to():
    conn = org(attachments=table(["rid", "account_rid"]), attachment_timeline=table(["rid"]))
    where, params = scoper().predicate(conn, "trd365_00042", "attachment_timeline", "org")
    assert where == (
        'attach_to IN (SELECT rid FROM "trd365_00042"."attachments" WHERE account_rid = %s)'
    )
    assert params == [RID]


def test_a_timeline_whose_subject_table_is_absent_matches_nothing():
    conn = org(attachment_timeline=table(["rid"]))
    assert scoper().predicate(conn, "trd365_00042", "attachment_timeline", "org") == ("1=0", [])


def test_the_account_row_itself_is_selected_by_primary_key():
    conn = FakeConnection({("trd365", "account"): table(["rid"])})
    assert scoper().predicate(conn, "trd365", "account", "main") == ("rid = %s", [RID])


def test_kafka_events_reaches_documents_and_imports():
    conn = org(
        document=table(["rid", "account_rid"]),
        **{"import": table(["rid", "document_rid"])},
        kafka_events=table(["rid", "document_rid", "document_upload_rid"]),
    )
    where, params = scoper().predicate(conn, "trd365_00042", "kafka_events", "org")
    assert "document_rid IN" in where
    assert "document_upload_rid IN" in where
    assert params == [RID, RID]


def test_kafka_events_without_an_import_table_only_uses_documents():
    conn = org(
        document=table(["rid", "account_rid"]),
        kafka_events=table(["rid", "document_rid"]),
    )
    where, params = scoper().predicate(conn, "trd365_00042", "kafka_events", "org")
    assert "document_upload_rid" not in where
    assert params == [RID]


def test_key_contact_details_covers_both_the_project_and_the_account():
    conn = org(project=table(["rid", "account_rid"]), key_contact_details=table(["entity_rid"]))
    where, params = scoper().predicate(conn, "trd365_00042", "key_contact_details", "org")
    assert "OR entity_rid = %s" in where
    assert params == [RID, RID]


def test_chat_children_are_reached_through_the_session():
    conn = org(chat_sessions=table(["session_rid", "account_rid"]), chat_messages=table(["rid"]))
    where, _params = scoper().predicate(conn, "trd365_00042", "chat_messages", "org")
    assert where.startswith("session_rid IN (SELECT session_rid FROM")


# ------------------------------------------------------------------ the ai db


def test_ai_tables_are_scoped_by_the_captured_fiscal_set():
    conn = FakeConnection({("public", "master_ai_request"): table(["rid", "projectId"])})
    where, params = scoper(sets={"project_fiscal": ["f1", "f2"]}).predicate(
        conn, "public", "master_ai_request", "ai"
    )
    assert where == '"projectId" = ANY(%s)'
    assert params == [["f1", "f2"]]


@pytest.mark.parametrize("column", M.AI_FISCAL_COLUMNS)
def test_every_spelling_of_the_fiscal_column_is_recognised(column):
    conn = FakeConnection({("public", "t"): table(["rid", column])})
    where, _params = scoper(sets={"project_fiscal": []}).predicate(conn, "public", "t", "ai")
    assert where.startswith(f'"{column}" =')


def test_an_ai_table_with_no_fiscal_column_is_unscopable():
    conn = FakeConnection({("public", "t"): table(["rid", "note"])})
    assert scoper(sets={"project_fiscal": []}).predicate(conn, "public", "t", "ai") is None


# ------------------------------------------------------------------ discovery


def test_discovery_finds_org_tables_the_manifest_never_heard_of():
    conn = org(
        project=table(["rid", "account_rid"]),
        newly_added=table(["rid", "account_rid"]),
    )
    found = scoper().discover(conn, "trd365_00042", "org", ["project"])
    assert found == ["newly_added"]


def test_discovery_does_not_re_list_tables_handled_by_a_special_predicate():
    conn = org(project=table(["rid", "account_rid"]), kafka_events=table(["rid", "account_rid"]))
    assert scoper().discover(conn, "trd365_00042", "org", ["project"]) == []


def test_discovery_uses_the_shared_data_model_as_well_as_the_live_catalog():
    # This is how re-running the data-model analysis reaches the purge: a table
    # the model knows references an account gets purged without anyone editing
    # the manifest.
    class Model:
        def schema(self, _name):
            class SchemaModel:
                table_names = {"project", "from_the_model"}

            return SchemaModel()

        def tables_referencing(self, _schema, _entity):
            return ["from_the_model"]

    conn = org(project=table(["rid", "account_rid"]))
    found = scoper(model=Model()).discover(conn, "trd365_00042", "org", ["project"])
    assert found == ["from_the_model"]


def test_discovery_on_the_main_schema_follows_foreign_keys_into_account():
    conn = FakeConnection(
        {
            ("trd365", "account"): table(["rid"]),
            ("trd365", "extra_summary"): table(
                ["rid", "account_rid"], fks=[("account_rid", "account", "rid")]
            ),
        }
    )
    found = scoper().discover(conn, "trd365", "main", ["account"])
    assert found == ["extra_summary"]


def test_nothing_is_discovered_in_the_ai_database():
    # trd365ai has no account link at all, so there is nothing to find and
    # anything "found" would be scoped by guesswork.
    conn = FakeConnection({("public", "whatever"): table(["rid"])})
    assert scoper().discover(conn, "public", "ai", []) == []


# ------------------------------------------------------------ reconciliation


def test_reconcile_reports_both_directions_of_drift():
    class Model:
        def schema(self, _name):
            class SchemaModel:
                table_names = set(M.ORG_TABLES[:-1]) | {"brand_new"}

            return SchemaModel()

        def tables_referencing(self, _schema, _entity):
            return ["brand_new", "cases"]

    drift = M.reconcile(Model(), "trd365_00042")
    assert drift["missing_from_manifest"] == ["brand_new"]
    assert drift["absent_from_model"] == [M.ORG_TABLES[-1]]


def test_reconcile_is_silent_about_a_schema_the_snapshot_does_not_cover():
    class Model:
        def schema(self, name):
            raise KeyError(name)

        def tables_referencing(self, _schema, _entity):
            raise KeyError

    assert M.reconcile(Model(), "trd365_99999") == {
        "missing_from_manifest": [],
        "absent_from_model": [],
    }
