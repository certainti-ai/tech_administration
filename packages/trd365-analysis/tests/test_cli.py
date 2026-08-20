"""
The producer's own contract: it reports freely, and it publishes only when told.
"""

from __future__ import annotations

import pytest
from fakes import FakeDatabase, FakePool, table
from trd365_core.audit import MemoryAuditSink
from trd365_core.environments import Environment
from trd365_core.model_snapshot import FileModelStore

from trd365_analysis import cli


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRD365_MODEL_DIR", str(tmp_path / "model"))
    monkeypatch.setenv("TRD365_AUDIT_DIR", str(tmp_path / "audit"))


def estate(schemas=("trd365_1",), accounts=("A1",)) -> FakeDatabase:
    db = FakeDatabase()
    for schema in schemas:
        db.tables[("orgdb", schema, "project")] = table(["rid", "account_rid"], [])
        db.tables[("orgdb", schema, "project_history")] = table(
            ["rid", "project_rid"], [{"rid": "h1", "project_rid": "GONE"}]
        )
    db.tables[("maindb", "trd365", "account")] = table(
        ["rid"], [{"rid": r} for r in accounts]
    )
    return db


def invoke(argv, db, *, store=None, sink=None) -> int:
    return cli.run(
        argv,
        pool_factory=lambda _env, log=None: FakePool(db),
        store=store,
        audit_sink=sink,
    )


# ------------------------------------------------------------- publishing


def test_without_apply_nothing_is_published(tmp_path, capsys):
    store = FileModelStore(tmp_path / "model")
    code = invoke(["--env", "dev", "--out-dir", str(tmp_path)], estate(), store=store)

    assert code == cli.EXIT_OK
    assert store.latest(Environment.DEV) is None
    assert "nothing was saved" in capsys.readouterr().out


def test_apply_publishes_the_snapshot(tmp_path):
    store = FileModelStore(tmp_path / "model")
    code = invoke(
        ["--env", "dev", "--apply", "--out-dir", str(tmp_path)], estate(), store=store
    )

    assert code == cli.EXIT_OK
    published = store.latest(Environment.DEV)
    assert published is not None
    assert published.tenant_schemas == ["trd365_1"]


def test_publishing_is_what_unblocks_the_consumers(tmp_path):
    # The whole reason this utility comes first: require_model() is what every
    # destructive tool calls, and nothing else writes what it reads.
    from trd365_core.model_snapshot import StaleModelError, require_model

    store = FileModelStore(tmp_path / "model")
    with pytest.raises(StaleModelError):
        require_model(store, Environment.DEV)

    invoke(["--env", "dev", "--apply", "--out-dir", str(tmp_path)], estate(), store=store)
    assert require_model(store, Environment.DEV) is not None


def test_the_environment_is_required_and_has_no_default(tmp_path):
    with pytest.raises(SystemExit):
        invoke(["--out-dir", str(tmp_path)], estate())


# ------------------------------------------------------------- what it finds


def test_schemas_are_discovered_when_not_named(tmp_path, capsys):
    invoke(
        ["--env", "dev", "--out-dir", str(tmp_path)],
        estate(schemas=("trd365_1", "trd365_2")),
    )
    assert "discovered 2 tenant schema(s)" in capsys.readouterr().out


def test_named_schemas_are_used_verbatim(tmp_path):
    store = FileModelStore(tmp_path / "model")
    invoke(
        ["--env", "dev", "--apply", "--schemas", "trd365_2", "--out-dir", str(tmp_path)],
        estate(schemas=("trd365_1", "trd365_2")),
        store=store,
    )
    assert store.latest(Environment.DEV).tenant_schemas == ["trd365_2"]


def test_an_estate_with_no_tenant_schemas_fails_rather_than_publishing_nothing(tmp_path):
    # An empty snapshot would look like a valid model to every consumer and let
    # them run against a schema they know nothing about.
    store = FileModelStore(tmp_path / "model")
    db = FakeDatabase({("maindb", "trd365", "account"): table(["rid"], [])})

    code = invoke(["--env", "dev", "--apply", "--out-dir", str(tmp_path)], db, store=store)

    assert code == cli.EXIT_FAILED
    assert store.latest(Environment.DEV) is None


def test_orphans_are_scanned_by_default(tmp_path, capsys):
    invoke(["--env", "dev", "--out-dir", str(tmp_path)], estate())
    assert "orphan rows:" in capsys.readouterr().out


def test_no_orphans_skips_the_scan(tmp_path, capsys):
    invoke(["--env", "dev", "--no-orphans", "--out-dir", str(tmp_path)], estate())
    assert "orphan scan: not performed" in capsys.readouterr().out


def test_reports_are_written_every_run(tmp_path):
    out = tmp_path / "out"
    invoke(["--env", "dev", "--out-dir", str(out)], estate())
    written = sorted(p.name.split("_")[0] for p in out.iterdir())
    assert written == ["data", "deviations", "orphans"]


def test_no_orphans_writes_no_orphans_csv(tmp_path):
    out = tmp_path / "out"
    invoke(["--env", "dev", "--no-orphans", "--out-dir", str(out)], estate())
    assert not any(p.name.startswith("orphans") for p in out.iterdir())


# ------------------------------------------------------------------- drift


def test_a_second_run_says_the_model_is_unchanged(tmp_path, capsys):
    store = FileModelStore(tmp_path / "model")
    db = estate()
    invoke(["--env", "dev", "--apply", "--out-dir", str(tmp_path)], db, store=store)
    capsys.readouterr()

    invoke(["--env", "dev", "--out-dir", str(tmp_path)], db, store=store)
    assert "the model is unchanged" in capsys.readouterr().out


def test_a_new_table_is_reported_as_a_change(tmp_path, capsys):
    store = FileModelStore(tmp_path / "model")
    db = estate()
    invoke(["--env", "dev", "--apply", "--out-dir", str(tmp_path)], db, store=store)
    capsys.readouterr()

    db.tables[("orgdb", "trd365_1", "cases")] = table(["rid"], [])
    db.tables[("orgdb", "trd365_1", "case_history")] = table(["rid", "case_rid"], [])
    invoke(["--env", "dev", "--out-dir", str(tmp_path)], db, store=store)

    assert "the model CHANGED" in capsys.readouterr().out


# ------------------------------------------------------------------ failures


def test_a_schema_that_cannot_be_scanned_fails_the_run(tmp_path):
    # The counts would otherwise read as "few orphans" when they mean
    # "we could not look".
    db = estate()
    db.fail_on = {"SELECT count(*) FROM": RuntimeError("tunnel dropped")}
    code = invoke(["--env", "dev", "--out-dir", str(tmp_path)], db)
    assert code == cli.EXIT_FAILED


def test_the_model_is_still_published_when_only_the_orphan_scan_broke(tmp_path):
    # The structural model is complete and consumers need it; it is the orphan
    # figures that are untrustworthy, and the exit code says so.
    store = FileModelStore(tmp_path / "model")
    db = estate()
    db.fail_on = {"SELECT count(*) FROM": RuntimeError("tunnel dropped")}

    code = invoke(["--env", "dev", "--apply", "--out-dir", str(tmp_path)], db, store=store)

    assert code == cli.EXIT_FAILED
    assert store.latest(Environment.DEV) is not None


# -------------------------------------------------------------- audit record


def test_the_run_is_audited(tmp_path):
    sink = MemoryAuditSink()
    invoke(["--env", "dev", "--out-dir", str(tmp_path)], estate(), sink=sink)

    (record,) = sink.records
    assert record.utility == "data-model-analysis"
    assert record.environment == "dev"
    assert record.applied is False
    assert record.outcome == "success"


def test_publishing_is_recorded_in_the_audit_trail(tmp_path):
    sink = MemoryAuditSink()
    store = FileModelStore(tmp_path / "model")
    invoke(
        ["--env", "dev", "--apply", "--out-dir", str(tmp_path)],
        estate(),
        store=store,
        sink=sink,
    )
    assert any(note.startswith("saved model ") for note in sink.records[0].notes)


def test_a_dry_run_records_no_save(tmp_path):
    sink = MemoryAuditSink()
    invoke(["--env", "dev", "--out-dir", str(tmp_path)], estate(), sink=sink)
    assert not any(note.startswith("saved model") for note in sink.records[0].notes)
