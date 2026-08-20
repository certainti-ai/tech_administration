"""The engine's contract: back up what you delete, delete nothing else."""

from __future__ import annotations

import pytest
from fakes import FakeConnection, FakePool, silent, table

from trd365_data_purge import engine


@pytest.fixture
def tag():
    return engine.RunTag(
        run_at="2026-08-20T00:00:00Z", run_id="run-1", entity="account", entity_rid="A1"
    )


def account_predicate(rid):
    class Scoper:
        def predicate(self, _conn, _schema, _table, _kind):
            return "account_rid = %s", [rid]

    return Scoper()


# --------------------------------------------------------------------- quote


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("project", '"project"'), ('od"d', '"od""d"'), ("Mixed Case", '"Mixed Case"')],
)
def test_quote_escapes_embedded_quotes(raw, expected):
    assert engine.quote(raw) == expected


# ---------------------------------------------------------------- SchemaCache


def test_cache_does_not_serve_one_database_metadata_for_another():
    # The legacy cache was keyed by (schema, table) only, and never cleared. Two
    # databases that share a schema and table name — which orgdb and maindb do —
    # could therefore be told each other's columns.
    org = FakeConnection({("shared", "notes"): table(["rid", "account_rid"])})
    main = FakeConnection({("shared", "notes"): table(["rid", "owner_rid"])})
    cache = engine.SchemaCache()

    assert cache.columns(org, "orgdb", "shared", "notes") == {"rid", "account_rid"}
    assert cache.columns(main, "maindb", "shared", "notes") == {"rid", "owner_rid"}


def test_cache_reads_each_table_once():
    conn = FakeConnection({("s", "t"): table(["rid"])})
    cache = engine.SchemaCache()

    for _ in range(3):
        cache.columns(conn, "orgdb", "s", "t")

    assert sum("information_schema.columns" in s for s in conn.statements) == 1


def test_cache_remembers_that_a_table_is_absent():
    conn = FakeConnection({})
    cache = engine.SchemaCache()

    assert cache.table_exists(conn, "orgdb", "s", "gone") is False
    assert cache.table_exists(conn, "orgdb", "s", "gone") is False
    assert sum("information_schema.tables" in s for s in conn.statements) == 1


# -------------------------------------------------------------- process_table


def rows_for(rid, count, other=0):
    return [{"rid": f"r{i}", "account_rid": rid} for i in range(count)] + [
        {"rid": f"x{i}", "account_rid": "OTHER"} for i in range(other)
    ]


def test_absent_table_is_skipped_not_failed(tag):
    conn = FakeConnection({})
    metrics = engine.process_table(
        conn, engine.SchemaCache(), "orgdb", "s", "gone", "account_rid = %s", ["A1"],
        tag, "data_purge", 100, False, silent,
    )
    assert metrics["status"] == "skipped"
    assert conn.commits == 0


def test_table_with_nothing_in_scope_is_left_alone(tag):
    conn = FakeConnection({("s", "t"): table(["rid", "account_rid"], rows_for("A1", 0, other=5))})
    metrics = engine.process_table(
        conn, engine.SchemaCache(), "orgdb", "s", "t", "account_rid = %s", ["A1"],
        tag, "data_purge", 100, False, silent,
    )
    assert metrics["status"] == "empty"
    assert metrics["total_before"] == 5
    assert conn.commits == 0


def test_dry_run_counts_and_writes_nothing(tag):
    conn = FakeConnection({("s", "t"): table(["rid", "account_rid"], rows_for("A1", 4, other=2))})
    metrics = engine.process_table(
        conn, engine.SchemaCache(), "orgdb", "s", "t", "account_rid = %s", ["A1"],
        tag, "data_purge", 100, True, silent,
    )
    assert metrics["status"] == "dry-run"
    assert metrics["scope_before"] == 4
    assert metrics["deleted"] == 0
    assert conn.ddl == []
    assert len(conn.tables[("s", "t")].rows) == 6


def test_deletes_only_in_scope_rows_and_backs_up_exactly_those(tag):
    conn = FakeConnection({("s", "t"): table(["rid", "account_rid"], rows_for("A1", 3, other=2))})
    metrics = engine.process_table(
        conn, engine.SchemaCache(), "orgdb", "s", "t", "account_rid = %s", ["A1"],
        tag, "data_purge", 100, False, silent,
    )

    assert metrics["status"] == "ok"
    assert (metrics["deleted"], metrics["backed_up"]) == (3, 3)
    assert metrics["scope_after"] == 0
    assert [r["account_rid"] for r in conn.tables[("s", "t")].rows] == ["OTHER", "OTHER"]

    backup = conn.tables[("data_purge", "bak_t")].rows
    assert len(backup) == 3
    assert {r["_purge_run_id"] for r in backup} == {"run-1"}
    assert {r["_purge_entity_rid"] for r in backup} == {"A1"}


def test_deletes_in_chunks_committing_each(tag):
    conn = FakeConnection({("s", "t"): table(["rid", "account_rid"], rows_for("A1", 7))})
    metrics = engine.process_table(
        conn, engine.SchemaCache(), "orgdb", "s", "t", "account_rid = %s", ["A1"],
        tag, "data_purge", 3, False, silent,
    )
    assert metrics["batches"] == 3
    assert metrics["deleted"] == 7
    assert conn.commits >= 3


def test_backup_table_name_is_truncated_to_what_postgres_stores(tag):
    long_name = "a" * 70
    conn = FakeConnection({("s", long_name): table(["rid", "account_rid"], rows_for("A1", 1))})
    engine.process_table(
        conn, engine.SchemaCache(), "orgdb", "s", long_name, "account_rid = %s", ["A1"],
        tag, "data_purge", 10, False, silent,
    )
    (created,) = [k for k in conn.tables if k[0] == "data_purge"]
    assert len(created[1]) == 63


def test_fk_violation_defers_the_table_and_keeps_committed_work(tag):
    conn = FakeConnection(
        {
            ("s", "parent"): table(["rid", "account_rid"], rows_for("A1", 2), blocked_by="child"),
            ("s", "child"): table(["rid", "account_rid"], rows_for("A1", 1)),
        }
    )
    metrics = engine.process_table(
        conn, engine.SchemaCache(), "orgdb", "s", "parent", "account_rid = %s", ["A1"],
        tag, "data_purge", 10, False, silent,
    )

    assert metrics["status"] == "fk_blocked"
    assert metrics["deleted"] == 0
    assert "FK-blocked" in metrics["note"]
    # Nothing was left half-written: the batch rolled back whole.
    assert len(conn.tables[("s", "parent")].rows) == 2
    assert ("data_purge", "bak_parent") not in conn.tables or not conn.tables[
        ("data_purge", "bak_parent")
    ].rows


def test_a_non_fk_error_is_raised_not_swallowed(tag):
    conn = FakeConnection({("s", "t"): table(["rid", "account_rid"], rows_for("A1", 1))})

    with pytest.raises(NotImplementedError):
        engine.process_table(
            conn, engine.SchemaCache(), "orgdb", "s", "t", "no_such_shape = 1", [],
            tag, "data_purge", 10, False, silent,
        )


# ------------------------------------------------------------------ run_steps


def steps(tables):
    return [("org_delete", "orgdb", "org", tables)]


def test_run_steps_retries_a_deferred_table_once_its_child_is_gone(tag):
    conn = FakeConnection(
        {
            ("s", "parent"): table(["rid", "account_rid"], rows_for("A1", 2), blocked_by="child"),
            ("s", "child"): table(["rid", "account_rid"], rows_for("A1", 3)),
        }
    )
    pool = FakePool({"orgdb": conn})
    metrics, completed = {}, {}
    lines: list[str] = []

    # Deliberately the wrong order: parent first. The engine must recover.
    ok, error = engine.run_steps(
        pool, steps(["parent", "child"]), {"org": "s"}, account_predicate("A1"), tag,
        engine.SchemaCache(), chunk_size=10, dry_run=False, log=lines.append,
        metrics=metrics, completed=completed, persist=lambda: None,
    )

    assert (ok, error) == (True, None)
    assert conn.tables[("s", "parent")].rows == []
    assert conn.tables[("s", "child")].rows == []
    assert metrics["org_delete"]["parent"]["deleted"] == 2
    assert any("retry pass 2" in line for line in lines)


def test_run_steps_stops_instead_of_spinning_when_nothing_can_progress(tag):
    # Two tables blocking each other, neither able to move: retrying is futile
    # and the run has to say so rather than burn 25 passes.
    conn = FakeConnection(
        {
            ("s", "a"): table(["rid", "account_rid"], rows_for("A1", 1), blocked_by="b"),
            ("s", "b"): table(["rid", "account_rid"], rows_for("A1", 1), blocked_by="a"),
        }
    )
    ok, error = engine.run_steps(
        FakePool({"orgdb": conn}), steps(["a", "b"]), {"org": "s"}, account_predicate("A1"),
        tag, engine.SchemaCache(), chunk_size=10, dry_run=False, log=silent,
        metrics={}, completed={}, persist=lambda: None,
    )

    assert ok is False
    assert "could not be resolved" in error


def test_run_steps_leaves_an_unscopable_table_completely_untouched(tag):
    class NoScope:
        def predicate(self, _conn, _schema, table_name, _kind):
            return None if table_name == "mystery" else ("account_rid = %s", ["A1"])

    conn = FakeConnection(
        {
            ("s", "mystery"): table(["rid"], [{"rid": "keep"}]),
            ("s", "known"): table(["rid", "account_rid"], rows_for("A1", 1)),
        }
    )
    metrics: dict = {}
    ok, _ = engine.run_steps(
        FakePool({"orgdb": conn}), steps(["mystery", "known"]), {"org": "s"}, NoScope(), tag,
        engine.SchemaCache(), chunk_size=10, dry_run=False, log=silent,
        metrics=metrics, completed={}, persist=lambda: None,
    )

    assert ok is True
    assert metrics["org_delete"]["mystery"]["status"] == "unscoped"
    assert conn.tables[("s", "mystery")].rows == [{"rid": "keep", "_ctid": "(0,1)"}]


def test_run_steps_records_completed_tables_so_a_rerun_skips_them(tag):
    conn = FakeConnection({("s", "t"): table(["rid", "account_rid"], rows_for("A1", 2))})
    completed: dict = {}
    saves: list[int] = []

    engine.run_steps(
        FakePool({"orgdb": conn}), steps(["t"]), {"org": "s"}, account_predicate("A1"), tag,
        engine.SchemaCache(), chunk_size=10, dry_run=False, log=silent,
        metrics={}, completed=completed, persist=lambda: saves.append(1),
    )

    assert completed["org_delete"] == ["t"]
    assert saves, "the checkpoint was never persisted"


def test_a_dry_run_marks_nothing_completed(tag):
    conn = FakeConnection({("s", "t"): table(["rid", "account_rid"], rows_for("A1", 2))})
    completed: dict = {}

    engine.run_steps(
        FakePool({"orgdb": conn}), steps(["t"]), {"org": "s"}, account_predicate("A1"), tag,
        engine.SchemaCache(), chunk_size=10, dry_run=True, log=silent,
        metrics={}, completed=completed, persist=lambda: None,
    )

    assert completed == {}


def test_run_steps_reports_row_counts_as_it_goes(tag):
    conn = FakeConnection({("s", "t"): table(["rid", "account_rid"], rows_for("A1", 4))})
    recorded: list[tuple[str, int]] = []

    engine.run_steps(
        FakePool({"orgdb": conn}), steps(["t"]), {"org": "s"}, account_predicate("A1"), tag,
        engine.SchemaCache(), chunk_size=10, dry_run=False, log=silent,
        metrics={}, completed={}, persist=lambda: None,
        on_rows=lambda t, n: recorded.append((t, n)),
    )

    assert recorded == [("s.t", 4)]


def test_run_steps_adds_tables_the_scoper_discovers(tag):
    class Discovering:
        def discover(self, _conn, _schema, _kind, _tables):
            return ["extra"]

        def predicate(self, _conn, _schema, _table, _kind):
            return "account_rid = %s", ["A1"]

    conn = FakeConnection(
        {
            ("s", "listed"): table(["rid", "account_rid"], rows_for("A1", 1)),
            ("s", "extra"): table(["rid", "account_rid"], rows_for("A1", 2)),
        }
    )
    metrics: dict = {}
    engine.run_steps(
        FakePool({"orgdb": conn}), steps(["listed"]), {"org": "s"}, Discovering(), tag,
        engine.SchemaCache(), chunk_size=10, dry_run=False, log=silent,
        metrics=metrics, completed={}, persist=lambda: None,
    )

    assert metrics["org_delete"]["extra"]["deleted"] == 2


# ---------------------------------------------------------------------- audit


def test_audit_is_not_performed_after_a_dry_run():
    findings, clean = engine.audit(
        FakePool({}), [], {}, account_predicate("A1"), {}, True, silent
    )
    assert (findings, clean) == ([], None)


def test_audit_is_clean_when_the_numbers_add_up():
    conn = FakeConnection(
        {("s", "t"): table(["rid", "account_rid"], rows_for("OTHER", 0, other=2))}
    )
    metrics = {
        "org_delete": {
            "t": {"status": "ok", "deleted": 3, "backed_up": 3, "total_before": 5, "total_after": 2}
        }
    }
    findings, clean = engine.audit(
        FakePool({"orgdb": conn}), steps(["t"]), {"org": "s"}, account_predicate("A1"),
        metrics, False, silent,
    )
    assert (findings, clean) == ([], True)


def test_audit_reports_rows_that_should_have_gone_but_did_not():
    conn = FakeConnection({("s", "t"): table(["rid", "account_rid"], rows_for("A1", 2))})
    metrics = {
        "org_delete": {
            "t": {"status": "ok", "deleted": 3, "backed_up": 3, "total_before": 5, "total_after": 2}
        }
    }
    findings, clean = engine.audit(
        FakePool({"orgdb": conn}), steps(["t"]), {"org": "s"}, account_predicate("A1"),
        metrics, False, silent,
    )
    assert clean is False
    assert "2 in-scope row(s) still present" in findings[0]["issues"]


def test_audit_reports_collateral_damage():
    # The table lost more rows than the purge deleted: something cascaded.
    conn = FakeConnection({("s", "t"): table(["rid", "account_rid"], [])})
    metrics = {
        "org_delete": {
            "t": {"status": "ok", "deleted": 3, "backed_up": 3, "total_before": 9, "total_after": 2}
        }
    }
    findings, clean = engine.audit(
        FakePool({"orgdb": conn}), steps(["t"]), {"org": "s"}, account_predicate("A1"),
        metrics, False, silent,
    )
    assert clean is False
    assert any("collateral" in issue for issue in findings[0]["issues"])


def test_audit_reports_a_delete_that_was_not_backed_up():
    conn = FakeConnection({("s", "t"): table(["rid", "account_rid"], [])})
    metrics = {
        "org_delete": {
            "t": {"status": "ok", "deleted": 3, "backed_up": 1, "total_before": 3, "total_after": 0}
        }
    }
    findings, clean = engine.audit(
        FakePool({"orgdb": conn}), steps(["t"]), {"org": "s"}, account_predicate("A1"),
        metrics, False, silent,
    )
    assert clean is False
    assert any("backed_up 1 != deleted 3" in issue for issue in findings[0]["issues"])


def test_audit_ignores_tables_it_never_touched():
    conn = FakeConnection({})
    metrics = {"org_delete": {"t": {"status": "skipped"}, "u": {"status": "unscoped"}}}
    findings, clean = engine.audit(
        FakePool({"orgdb": conn}), steps(["t", "u"]), {"org": "s"}, account_predicate("A1"),
        metrics, False, silent,
    )
    assert (findings, clean) == ([], True)
