"""
The driver: safety defaults, resumption, the data-model requirement, and what
ends up in the audit trail.
"""

from __future__ import annotations

import pytest
from fakes import FakeConnection, FakePool, table
from trd365_core.audit import MemoryAuditSink
from trd365_core.datamodel import SchemaCatalog
from trd365_core.model_snapshot import FileModelStore, ModelSnapshot, SchemaModel

from trd365_data_purge import cli
from trd365_data_purge.checkpoint import Checkpoint, CheckpointStore

RID = "ACCT-1"
SCHEMA = "trd365_00042"


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRD365_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TRD365_MODEL_DIR", str(tmp_path / "model"))
    monkeypatch.setenv("TRD365_AUDIT_DIR", str(tmp_path / "audit"))


def rows(rid, count):
    return [{"rid": f"r{i}", "account_rid": rid} for i in range(count)]


def make_pool(count=3):
    conn = FakeConnection({(SCHEMA, "cases"): table(["rid", "account_rid"], rows(RID, count))})
    return FakePool({"orgdb": conn}), conn


class SimpleScoper:
    def predicate(self, _conn, _schema, _table, _kind):
        return "account_rid = %s", [RID]


def make_resolver(pool_holder, *, missing=False, notes=()):
    def resolve(ctx: cli.ResolverContext) -> cli.PurgePlan:
        pool_holder.append(ctx)
        if missing and ctx.saved is None:
            raise cli.TargetNotFound("no such account")
        return cli.PurgePlan(
            entity_rid=RID,
            steps=[("org_delete", "orgdb", "org", ["cases"])],
            schema_for={"org": SCHEMA},
            scoper=SimpleScoper(),
            resolved={"org_schema": SCHEMA},
            id_sets={"project_fiscal": ["f1"]},
            notes=list(notes),
        )

    return resolve


def invoke(argv, pool, *, resolver=None, sink=None, holder=None, store=None):
    return cli.run(
        entity="account",
        description="test purge",
        resolver=resolver or make_resolver(holder if holder is not None else []),
        entity_rid=lambda ns: ns.account_rid,
        configure=lambda p: p.add_argument("--account-rid", required=True),
        argv=argv,
        pool_factory=lambda _env, log=None: pool,
        audit_sink=sink,
        store=store,
    )


def snapshot(environment="dev") -> ModelSnapshot:
    return ModelSnapshot(
        environment=environment,
        generated_at="2026-08-20T00:00:00+00:00",
        generated_by="test",
        schemas={
            SCHEMA: SchemaModel(schema=SCHEMA, catalog=SchemaCatalog(db_key="orgdb", schema=SCHEMA))
        },
    )


def store_model(tmp_path, environment="dev"):
    FileModelStore(tmp_path / "model").save(snapshot(environment))


# ----------------------------------------------------------- safety defaults


def test_without_apply_nothing_is_written(tmp_path, capsys):
    pool, conn = make_pool()
    code = invoke(["--env", "dev", "--account-rid", RID, "--out-dir", str(tmp_path)], pool)

    assert code == cli.EXIT_OK
    assert len(conn.tables[(SCHEMA, "cases")].rows) == 3
    assert "would delete 3 row(s)" in capsys.readouterr().out


def test_apply_writes(tmp_path):
    store_model(tmp_path)
    pool, conn = make_pool()
    code = invoke(
        ["--env", "dev", "--account-rid", RID, "--apply", "--out-dir", str(tmp_path)], pool
    )

    assert code == cli.EXIT_OK
    assert conn.tables[(SCHEMA, "cases")].rows == []
    assert len(conn.tables[("data_purge", "bak_cases")].rows) == 3


def test_dry_run_is_the_default_for_the_registered_utility():
    # The estate's headline bug was tools that wrote unless told not to.
    from trd365_data_purge.registry import PURGE_ACCOUNT

    assert PURGE_ACCOUNT.is_destructive
    assert "apply" not in {p.name for p in PURGE_ACCOUNT.parameters}


def test_dry_run_is_removed_and_explained_rather_than_ignored(tmp_path):
    pool, _conn = make_pool()
    with pytest.raises(SystemExit) as exit_info:
        invoke(["--env", "dev", "--account-rid", RID, "--dry-run"], pool)
    assert exit_info.value.code == 2


# ---------------------------------------------------------------- the model


def test_applying_without_a_data_model_snapshot_is_refused(tmp_path, capsys):
    pool, conn = make_pool()
    code = invoke(
        ["--env", "dev", "--account-rid", RID, "--apply", "--out-dir", str(tmp_path)], pool
    )

    assert code == cli.EXIT_FAILED
    assert "needs a data-model snapshot" in capsys.readouterr().out
    assert len(conn.tables[(SCHEMA, "cases")].rows) == 3


def test_a_dry_run_proceeds_without_a_snapshot_and_says_so(tmp_path, capsys):
    pool, _conn = make_pool()
    code = invoke(["--env", "dev", "--account-rid", RID, "--out-dir", str(tmp_path)], pool)

    assert code == cli.EXIT_OK
    assert "data model: unavailable" in capsys.readouterr().out


def test_ignore_model_is_allowed_but_recorded_in_the_audit_trail(tmp_path):
    pool, _conn = make_pool()
    sink = MemoryAuditSink()
    code = invoke(
        [
            "--env", "dev", "--account-rid", RID, "--apply",
            "--ignore-model", "--out-dir", str(tmp_path),
        ],
        pool,
        sink=sink,
    )

    assert code == cli.EXIT_OK
    assert "ran without a data-model snapshot" in sink.records[0].notes


def test_the_snapshot_reaches_the_resolver(tmp_path):
    store_model(tmp_path)
    pool, _conn = make_pool()
    holder: list[cli.ResolverContext] = []
    invoke(
        ["--env", "dev", "--account-rid", RID, "--apply", "--out-dir", str(tmp_path)],
        pool,
        holder=holder,
    )
    assert holder[0].model is not None
    assert SCHEMA in holder[0].model.schemas


def test_a_stale_snapshot_is_refused_and_the_age_limit_can_be_lifted(tmp_path):
    old = snapshot()
    old.generated_at = "2020-01-01T00:00:00+00:00"
    FileModelStore(tmp_path / "model").save(old)
    pool, _conn = make_pool()

    refused = invoke(
        ["--env", "dev", "--account-rid", RID, "--apply", "--out-dir", str(tmp_path)], pool
    )
    assert refused == cli.EXIT_FAILED

    pool, _conn = make_pool()
    allowed = invoke(
        [
            "--env", "dev", "--account-rid", RID, "--apply",
            "--model-max-age-days", "0", "--out-dir", str(tmp_path),
        ],
        pool,
    )
    assert allowed == cli.EXIT_OK


# ------------------------------------------------------------- resumption


def test_a_completed_table_is_not_purged_twice(tmp_path):
    store_model(tmp_path)
    store = CheckpointStore(tmp_path / "state")
    store.save(
        Checkpoint(
            entity="account",
            entity_rid=RID,
            environment="dev",
            run_id="earlier",
            completed={"org_delete": ["cases"]},
            id_sets={"project_fiscal": ["f1"]},
            resolved={"org_schema": SCHEMA},
        )
    )
    pool, conn = make_pool()

    code = invoke(
        ["--env", "dev", "--account-rid", RID, "--apply", "--out-dir", str(tmp_path)],
        pool,
        store=store,
    )

    assert code == cli.EXIT_OK
    assert len(conn.tables[(SCHEMA, "cases")].rows) == 3, "already-completed table was redone"


def test_restart_discards_the_checkpoint(tmp_path):
    store_model(tmp_path)
    store = CheckpointStore(tmp_path / "state")
    store.save(
        Checkpoint(
            entity="account", entity_rid=RID, environment="dev", run_id="earlier",
            completed={"org_delete": ["cases"]},
        )
    )
    pool, conn = make_pool()

    invoke(
        ["--env", "dev", "--account-rid", RID, "--apply", "--restart", "--out-dir", str(tmp_path)],
        pool,
        store=store,
    )
    assert conn.tables[(SCHEMA, "cases")].rows == []


def test_a_dry_run_never_resumes(tmp_path, capsys):
    # A dry run reports what the database holds now. Skipping tables a previous
    # run completed would under-report the impact of the next apply.
    store = CheckpointStore(tmp_path / "state")
    store.save(
        Checkpoint(
            entity="account", entity_rid=RID, environment="dev", run_id="earlier",
            completed={"org_delete": ["cases"]},
        )
    )
    pool, _conn = make_pool()

    invoke(["--env", "dev", "--account-rid", RID, "--out-dir", str(tmp_path)], pool, store=store)
    assert "would delete 3 row(s)" in capsys.readouterr().out


def test_the_saved_checkpoint_is_handed_to_the_resolver(tmp_path):
    store_model(tmp_path)
    store = CheckpointStore(tmp_path / "state")
    store.save(
        Checkpoint(
            entity="account", entity_rid=RID, environment="dev", run_id="earlier",
            id_sets={"project_fiscal": ["from-checkpoint"]},
        )
    )
    pool, _conn = make_pool()
    seen: list = []

    def resolve(ctx: cli.ResolverContext) -> cli.PurgePlan:
        # Read at resolve time: the driver reuses the saved checkpoint object
        # for the new run, so its fields are overwritten once resolution returns.
        seen.append(None if ctx.saved is None else dict(ctx.saved.id_sets))
        return make_resolver([])(ctx)

    invoke(
        ["--env", "dev", "--account-rid", RID, "--apply", "--out-dir", str(tmp_path)],
        pool,
        resolver=resolve,
        store=store,
    )
    assert seen == [{"project_fiscal": ["from-checkpoint"]}]


def test_a_dry_run_leaves_no_checkpoint_behind(tmp_path):
    store = CheckpointStore(tmp_path / "state")
    pool, _conn = make_pool()
    invoke(["--env", "dev", "--account-rid", RID, "--out-dir", str(tmp_path)], pool, store=store)
    assert store.load("dev", "account", RID) is None


# -------------------------------------------------------------- exit codes


def test_a_target_that_does_not_exist_has_its_own_exit_code(tmp_path, capsys):
    pool, _conn = make_pool()
    code = invoke(
        ["--env", "dev", "--account-rid", RID, "--out-dir", str(tmp_path)],
        pool,
        resolver=make_resolver([], missing=True),
    )
    assert code == cli.EXIT_TARGET_NOT_FOUND
    assert "NOT FOUND" in capsys.readouterr().out


def test_a_failed_purge_exits_non_zero_and_records_the_failure(tmp_path):
    store_model(tmp_path)
    conn = FakeConnection(
        {
            (SCHEMA, "a"): table(["rid", "account_rid"], rows(RID, 1), blocked_by="b"),
            (SCHEMA, "b"): table(["rid", "account_rid"], rows(RID, 1), blocked_by="a"),
        }
    )
    pool = FakePool({"orgdb": conn})
    sink = MemoryAuditSink()

    def resolve(_ctx):
        return cli.PurgePlan(
            entity_rid=RID,
            steps=[("org_delete", "orgdb", "org", ["a", "b"])],
            schema_for={"org": SCHEMA},
            scoper=SimpleScoper(),
        )

    code = invoke(
        ["--env", "dev", "--account-rid", RID, "--apply", "--out-dir", str(tmp_path)],
        pool,
        resolver=resolve,
        sink=sink,
    )

    assert code == cli.EXIT_FAILED
    assert sink.records[0].outcome == "failed"
    assert "FK-blocked" in (sink.records[0].error or "")


# ------------------------------------------------------------- audit record


def test_the_audit_record_carries_the_run_and_the_rows(tmp_path):
    store_model(tmp_path)
    pool, _conn = make_pool()
    sink = MemoryAuditSink()

    invoke(
        ["--env", "dev", "--account-rid", RID, "--apply", "--out-dir", str(tmp_path)],
        pool,
        sink=sink,
    )

    (record,) = sink.records
    assert record.utility == "purge-account"
    assert record.environment == "dev"
    assert record.applied is True
    assert record.outcome == "success"
    assert record.rows_affected == {f"{SCHEMA}.cases": 3}
    assert record.arguments["account_rid"] == RID


def test_resolver_notes_reach_the_audit_record(tmp_path):
    store_model(tmp_path)
    pool, _conn = make_pool()
    sink = MemoryAuditSink()

    invoke(
        ["--env", "dev", "--account-rid", RID, "--apply", "--out-dir", str(tmp_path)],
        pool,
        resolver=make_resolver([], notes=["2 tables not in the manifest"]),
        sink=sink,
    )
    assert "2 tables not in the manifest" in sink.records[0].notes


def test_a_dry_run_is_audited_as_a_dry_run(tmp_path):
    pool, _conn = make_pool()
    sink = MemoryAuditSink()
    invoke(["--env", "dev", "--account-rid", RID, "--out-dir", str(tmp_path)], pool, sink=sink)

    assert sink.records[0].applied is False
    assert sink.records[0].mode == "dry-run"


# ----------------------------------------------------------------- reports


def test_every_run_writes_a_report(tmp_path):
    pool, _conn = make_pool()
    invoke(["--env", "dev", "--account-rid", RID, "--out-dir", str(tmp_path / "out")], pool)
    written = sorted(p.suffix for p in (tmp_path / "out").iterdir())
    assert written == [".json", ".txt"]


# ------------------------------------------------------------- production


def test_production_requires_a_typed_confirmation(tmp_path, monkeypatch):
    store_model(tmp_path, environment="prod")
    pool, conn = make_pool()
    monkeypatch.setattr("builtins.input", lambda _prompt="": "no")

    code = invoke(
        ["--env", "prod", "--account-rid", RID, "--apply", "--out-dir", str(tmp_path)], pool
    )

    assert code == cli.EXIT_FAILED
    assert len(conn.tables[(SCHEMA, "cases")].rows) == 3


def test_yes_skips_the_prompt_for_non_interactive_callers(tmp_path, monkeypatch):
    store_model(tmp_path, environment="prod")
    pool, conn = make_pool()

    def refuse(_prompt=""):
        raise AssertionError("should not have prompted")

    monkeypatch.setattr("builtins.input", refuse)

    code = invoke(
        ["--env", "prod", "--account-rid", RID, "--apply", "--yes", "--out-dir", str(tmp_path)],
        pool,
    )
    assert code == cli.EXIT_OK
    assert conn.tables[(SCHEMA, "cases")].rows == []


def test_the_environment_is_required_and_has_no_default(tmp_path):
    pool, _conn = make_pool()
    with pytest.raises(SystemExit):
        invoke(["--account-rid", RID], pool)
