"""
Finding rows whose parent is gone.

A wrong orphan count is not a cosmetic problem: it is the input to a
remediation that deletes rows. The false-positive tests here matter as much as
the detection ones.
"""

from __future__ import annotations

from fakes import FakeDatabase, silent, table
from trd365_core.datamodel import SchemaCatalog, references
from trd365_core.model_snapshot import ModelSnapshot, SchemaModel

from trd365_analysis import orphans

SCHEMA = "trd365_00042"


def build_model(database: FakeDatabase, schema: str = SCHEMA) -> SchemaModel:
    """Derive the model from the fake, the way the analysis actually would."""
    rows = [
        (name, column)
        for (db, s, name), t in sorted(database.tables.items())
        if db == "orgdb" and s == schema
        for column in t.columns
    ]
    catalog = SchemaCatalog.from_columns("orgdb", schema, rows)
    return SchemaModel(schema=schema, catalog=catalog, references=references(catalog))


def snapshot_of(database: FakeDatabase, *schemas: str) -> ModelSnapshot:
    names = list(schemas) or [SCHEMA]
    return ModelSnapshot(
        environment="dev",
        generated_at="2026-08-20T00:00:00+00:00",
        generated_by="test",
        schemas={name: build_model(database, name) for name in names},
    )


def database(**org_tables) -> FakeDatabase:
    return FakeDatabase({("orgdb", SCHEMA, name): t for name, t in org_tables.items()})


def with_accounts(db: FakeDatabase, rids) -> FakeDatabase:
    db.tables[("maindb", "trd365", "account")] = table(
        ["rid", "r_number"], [{"rid": r} for r in rids]
    )
    return db


# ---------------------------------------------------------------- preloading


def test_account_rids_are_read_once_for_the_whole_run():
    db = with_accounts(database(), ["A1", "A2"])
    assert orphans.account_rids(db.fetch) == {"A1", "A2"}


def test_a_missing_account_table_is_detected_rather_than_assumed():
    assert orphans.account_table_exists(database().fetch) is False
    assert orphans.account_table_exists(with_accounts(database(), []).fetch) is True


# ------------------------------------------------------- same-database edges


def test_rows_pointing_at_a_missing_parent_are_counted():
    db = database(
        project=table(["rid"], [{"rid": "p1"}]),
        project_history=table(
            ["rid", "project_rid"],
            [
                {"rid": "h1", "project_rid": "p1"},
                {"rid": "h2", "project_rid": "GONE"},
                {"rid": "h3", "project_rid": "ALSO-GONE"},
            ],
        ),
    )
    scan = orphans.scan_schema(
        db.fetch, build_model(db), valid_accounts=set(), check_account=False, log=silent
    )

    assert len(scan.orphans) == 1
    found = scan.orphans[0]
    assert (found.child_table, found.column, found.rows) == ("project_history", "project_rid", 2)
    assert set(found.samples) == {"GONE", "ALSO-GONE"}


def test_null_references_are_not_orphans():
    db = database(
        project=table(["rid"], []),
        project_history=table(["rid", "project_rid"], [{"rid": "h1", "project_rid": None}]),
    )
    scan = orphans.scan_schema(
        db.fetch, build_model(db), valid_accounts=set(), check_account=False, log=silent
    )
    assert scan.orphans == []


def test_samples_are_capped_and_deduplicated():
    db = database(
        project=table(["rid"], [{"rid": "p1"}]),
        project_history=table(
            ["rid", "project_rid"],
            [{"rid": f"h{i}", "project_rid": "GONE"} for i in range(10)],
        ),
    )
    scan = orphans.scan_schema(
        db.fetch,
        build_model(db),
        valid_accounts=set(),
        check_account=False,
        sample=3,
        log=silent,
    )
    assert scan.orphans[0].rows == 10
    assert scan.orphans[0].samples == ["GONE"]


def test_sample_zero_records_counts_without_examples():
    db = database(
        project=table(["rid"], []),
        project_history=table(["rid", "project_rid"], [{"rid": "h1", "project_rid": "GONE"}]),
    )
    scan = orphans.scan_schema(
        db.fetch,
        build_model(db),
        valid_accounts=set(),
        check_account=False,
        sample=0,
        log=silent,
    )
    assert scan.orphans[0].rows == 1
    assert scan.orphans[0].samples == []


# ------------------------------------------------------- the cross-DB account


def test_account_references_are_checked_against_the_preloaded_set():
    # No foreign key can enforce this one — the parent is in another database.
    db = database(
        project=table(
            ["rid", "account_rid"],
            [
                {"rid": "p1", "account_rid": "A1"},
                {"rid": "p2", "account_rid": "VANISHED"},
                {"rid": "p3", "account_rid": "VANISHED"},
            ],
        )
    )
    scan = orphans.scan_schema(
        db.fetch, build_model(db), valid_accounts={"A1"}, log=silent
    )

    (found,) = [o for o in scan.orphans if o.column == "account_rid"]
    assert found.rows == 2
    assert found.samples == ["VANISHED"]
    assert found.entity == "account"


def test_account_edges_are_skipped_when_there_is_no_account_table():
    db = database(project=table(["rid", "account_rid"], [{"rid": "p1", "account_rid": "X"}]))
    scan = orphans.scan_schema(
        db.fetch, build_model(db), valid_accounts=set(), check_account=False, log=silent
    )
    assert scan.orphans == []
    assert scan.edges_checked == 0


# --------------------------------------------------- the false positive guard


def test_a_parent_that_is_empty_here_but_mastered_in_main_is_excluded():
    # interaction_type is the example the original calls out: the tenant table
    # is empty because the rows live in main, so every child looks orphaned.
    db = database(
        interaction_type=table(["rid"], []),
        interactions=table(
            ["rid", "interaction_type_rid"],
            [{"rid": "i1", "interaction_type_rid": "T1"}],
        ),
    )
    db.tables[("maindb", "trd365", "interaction_type")] = table(["rid"], [{"rid": "T1"}])

    model = build_model(db)
    assert orphans.global_lookup_parents(db.fetch, model) == {"interaction_type"}

    scan = orphans.scan_schema(
        db.fetch,
        model,
        valid_accounts=set(),
        check_account=False,
        all_entities=True,
        log=silent,
    )
    assert scan.orphans == []
    assert scan.excluded_parents == ["interaction_type"]


def test_an_empty_parent_with_no_master_in_main_is_still_scanned():
    # Empty and unmastered means the children really are orphaned.
    db = database(
        project=table(["rid"], []),
        project_history=table(["rid", "project_rid"], [{"rid": "h1", "project_rid": "GONE"}]),
    )
    scan = orphans.scan_schema(
        db.fetch, build_model(db), valid_accounts=set(), check_account=False, log=silent
    )
    assert scan.orphans[0].rows == 1


# ------------------------------------------------------------- scope control


def test_only_the_primary_entities_are_scanned_by_default():
    db = database(
        project=table(["rid"], []),
        widget=table(["rid"], []),
        thing=table(
            ["rid", "project_rid", "widget_rid"],
            [{"rid": "t1", "project_rid": "GONE", "widget_rid": "ALSO-GONE"}],
        ),
    )
    scan = orphans.scan_schema(
        db.fetch, build_model(db), valid_accounts=set(), check_account=False, log=silent
    )
    assert [o.column for o in scan.orphans] == ["project_rid"]


def test_all_entities_widens_the_scan():
    db = database(
        project=table(["rid"], []),
        widget=table(["rid"], []),
        thing=table(
            ["rid", "project_rid", "widget_rid"],
            [{"rid": "t1", "project_rid": "GONE", "widget_rid": "ALSO-GONE"}],
        ),
    )
    scan = orphans.scan_schema(
        db.fetch,
        build_model(db),
        valid_accounts=set(),
        check_account=False,
        all_entities=True,
        log=silent,
    )
    assert sorted(o.column for o in scan.orphans) == ["project_rid", "widget_rid"]


# ------------------------------------------------------------------ failures


def test_one_unreadable_edge_is_recorded_and_the_scan_continues():
    db = database(
        project=table(["rid"], []),
        cases=table(["rid"], []),
        project_history=table(["rid", "project_rid"], [{"rid": "h1", "project_rid": "GONE"}]),
        case_history=table(["rid", "case_rid"], [{"rid": "c1", "case_rid": "GONE"}]),
    )
    db.fail_on = {'"case_history" c': RuntimeError("permission denied")}

    scan = orphans.scan_schema(
        db.fetch, build_model(db), valid_accounts=set(), check_account=False, log=silent
    )

    assert len(scan.failed_edges) == 1
    assert "permission denied" in scan.failed_edges[0].error
    # The good edge still produced a count.
    assert any(o.checked and o.rows == 1 for o in scan.orphans)


def test_a_failed_edge_contributes_no_rows_to_the_total():
    db = database(
        project=table(["rid"], []),
        project_history=table(["rid", "project_rid"], [{"rid": "h1", "project_rid": "GONE"}]),
    )
    db.fail_on = {'"project_history" c': RuntimeError("boom")}
    scan = orphans.scan_schema(
        db.fetch, build_model(db), valid_accounts=set(), check_account=False, log=silent
    )
    assert scan.total_rows == 0
    assert scan.failed_edges


def test_a_schema_whose_exclusion_check_fails_is_marked_not_silently_empty():
    db = database(
        project=table(["rid"], []),
        project_history=table(["rid", "project_rid"], [{"rid": "h1", "project_rid": "GONE"}]),
    )
    db.fail_on = {"SELECT count(*) FROM": RuntimeError("tunnel dropped")}
    scan = orphans.scan_schema(
        db.fetch, build_model(db), valid_accounts=set(), check_account=False, log=silent
    )
    assert scan.error is not None
    assert scan.orphans == []


# --------------------------------------------------------------- whole sweep


def test_scan_walks_every_schema_in_the_snapshot():
    db = FakeDatabase()
    for schema in ("trd365_1", "trd365_2"):
        db.tables[("orgdb", schema, "project")] = table(["rid"], [])
        db.tables[("orgdb", schema, "project_history")] = table(
            ["rid", "project_rid"], [{"rid": "h1", "project_rid": "GONE"}]
        )
    with_accounts(db, [])

    model = ModelSnapshot(
        environment="dev",
        generated_at="2026-08-20T00:00:00+00:00",
        generated_by="test",
        schemas={name: build_model(db, name) for name in ("trd365_1", "trd365_2")},
    )
    results = orphans.scan(db.fetch, model, log=silent)

    assert [r.schema for r in results] == ["trd365_1", "trd365_2"]
    assert orphans.totals(results)["orphan_rows"] == 2


def test_a_schema_missing_from_the_snapshot_is_reported_not_crashed():
    db = with_accounts(FakeDatabase(), [])
    model = ModelSnapshot(
        environment="dev", generated_at="x", generated_by="test", schemas={}
    )
    results = orphans.scan(db.fetch, model, schemas=["trd365_nope"], log=silent)

    assert results[0].error is not None
    assert orphans.totals(results)["schemas_failed"] == 1


def test_totals_separate_what_was_checked_from_what_was_found():
    db = database(
        project=table(["rid"], []),
        project_history=table(["rid", "project_rid"], [{"rid": "h1", "project_rid": "GONE"}]),
    )
    with_accounts(db, [])
    results = orphans.scan(db.fetch, snapshot_of(db), log=silent)
    counts = orphans.totals(results)

    assert counts["schemas_scanned"] == 1
    assert counts["orphan_edges"] == 1
    assert counts["orphan_rows"] == 1
    assert counts["edges_failed"] == 0
