"""
Shared command-line scaffolding for the purge sub-commands.

Everything common to every entity lives here: the argument conventions
inherited from :mod:`trd365_core.cli`, loading the data-model snapshot, opening
the pool, driving the five phases, writing the report, and recording the run in
the audit trail. A sub-command supplies only what makes it that entity — how to
name its target, how to resolve it, what its steps are, and how to scope a table
to it.

Exit codes
----------
==  =========================================================================
0   completed (or, in dry run, analysed) with a clean audit
1   the purge failed, or the audit found something
2   bad invocation (argparse)
3   the target does not exist and there is nothing saved to resume
==  =========================================================================
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from trd365_core.audit import AuditedRun
from trd365_core.cli import CommonArgs, build_parser, common_args, confirm_production, describe_mode
from trd365_core.db import ConnectionPool
from trd365_core.errors import Trd365Error
from trd365_core.model_snapshot import (
    FileModelStore,
    ModelSnapshot,
    StaleModelError,
    require_model,
)

from . import engine, reporting
from .checkpoint import Checkpoint, CheckpointStore

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_MODEL_MAX_AGE_DAYS = 7

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_TARGET_NOT_FOUND = 3


class TargetNotFound(Trd365Error):
    """The entity being purged is not in the database and no run can be resumed."""


@dataclass
class PurgePlan:
    """Everything the generic driver needs in order to purge one entity."""

    entity_rid: str
    steps: list
    schema_for: dict[str, str]
    scoper: Any
    resolved: dict[str, Any] = field(default_factory=dict)
    id_sets: dict[str, list] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class ResolverContext:
    """What a sub-command's resolver is handed."""

    pool: ConnectionPool
    namespace: Any
    args: CommonArgs
    cache: engine.SchemaCache
    log: Callable[[str], None]
    #: The saved checkpoint for this target, if a previous run left one. A purge
    #: deletes its own anchor row partway through, so a resumed run frequently
    #: cannot resolve the target again and must rely on this.
    saved: Checkpoint | None
    model: ModelSnapshot | None


Resolver = Callable[[ResolverContext], PurgePlan]


def add_common_arguments(parser) -> None:
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Rows per backup+delete batch (default {DEFAULT_CHUNK_SIZE}).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("reports"),
        help="Directory for the run report (default ./reports).",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Discard any saved checkpoint and start this target from the beginning.",
    )
    parser.add_argument(
        "--model-max-age-days",
        type=int,
        default=DEFAULT_MODEL_MAX_AGE_DAYS,
        help=(
            "How old the data-model snapshot may be (default "
            f"{DEFAULT_MODEL_MAX_AGE_DAYS} days). 0 accepts any age."
        ),
    )
    parser.add_argument(
        "--ignore-model",
        action="store_true",
        help=(
            "Run without the data-model snapshot. Tables added since the manifest "
            "was written will not be discovered. Recorded in the audit trail."
        ),
    )


def load_model(args: CommonArgs, namespace, log) -> ModelSnapshot | None:
    """
    The shared data-model snapshot for this environment, or ``None``.

    A snapshot is required to apply, because applying without one means purging
    against a stale idea of the schema — the exact failure the shared model
    exists to prevent. A dry run proceeds without it, with a warning, so an
    operator can preview before the first analysis has ever been run.
    """
    if namespace.ignore_model:
        log("  data model: IGNORED by request — newly added tables will not be discovered")
        return None

    max_age = (
        None if namespace.model_max_age_days == 0 else timedelta(days=namespace.model_max_age_days)
    )
    try:
        model = require_model(
            FileModelStore(), args.env, max_age=max_age, utility="purge"
        )
    except StaleModelError as exc:
        if args.apply:
            raise
        log(f"  data model: unavailable — {str(exc).splitlines()[0]}")
        log("  continuing: this is a dry run. --apply would refuse.")
        return None

    log(f"  data model: {model.version} ({model.fingerprint[:12]}), {model.age.days}d old")
    return model


def run(
    *,
    entity: str,
    description: str,
    resolver: Resolver,
    entity_rid: Callable[[Any], str],
    argv: list[str] | None = None,
    configure: Callable[[Any], None] | None = None,
    store: CheckpointStore | None = None,
    pool_factory: Callable[..., ConnectionPool] = ConnectionPool,
    audit_sink=None,
) -> int:
    """Drive one purge from the command line. Returns a process exit code."""
    parser = build_parser(description)
    add_common_arguments(parser)
    if configure is not None:
        configure(parser)

    namespace = parser.parse_args(argv)
    args = common_args(namespace)
    rid = entity_rid(namespace)

    def log(message: str) -> None:
        print(message, flush=True)

    log(describe_mode(args, f"purge-{entity}"))
    log(f"  target      : {rid}")
    log(f"  chunk size  : {namespace.chunk_size}")
    log(f"  backups into: schema {engine.BACKUP_SCHEMA!r} of each database touched")

    checkpoints = store if store is not None else CheckpointStore()
    if namespace.restart:
        checkpoints.clear(args.env.value, entity, rid)

    # A dry run must never resume: it reports what the *current* database holds,
    # and a checkpoint would make it skip everything a previous run completed.
    saved = checkpoints.load(args.env.value, entity, rid) if args.apply else None

    try:
        confirm_production(args, f"purge-{entity}")
        model = load_model(args, namespace, log)
    except Trd365Error as exc:
        log(str(exc))
        return EXIT_FAILED

    cache = engine.SchemaCache()

    with pool_factory(args.env, log=log) as pool:
        try:
            plan = resolver(
                ResolverContext(
                    pool=pool,
                    namespace=namespace,
                    args=args,
                    cache=cache,
                    log=log,
                    saved=saved,
                    model=model,
                )
            )
        except TargetNotFound as exc:
            log(f"NOT FOUND: {exc}")
            return EXIT_TARGET_NOT_FOUND
        except Trd365Error as exc:
            log(f"could not resolve the target: {exc}")
            return EXIT_FAILED

        checkpoint = saved or Checkpoint(
            entity=entity,
            entity_rid=rid,
            environment=args.env.value,
            run_id=str(uuid.uuid4()),
        )
        if saved is not None:
            log(
                f"  resuming run {saved.run_id}: {saved.tables_completed} table(s) already "
                f"completed. Pass --restart to start over."
            )

        checkpoint.resolved = plan.resolved
        checkpoint.id_sets = plan.id_sets
        checkpoint.steps_meta = [
            {"step": step, "db": db_key, "schema": plan.schema_for[kind]}
            for (step, db_key, kind, _tables) in plan.steps
        ]
        checkpoint.error = None

        def persist() -> None:
            if args.apply:
                checkpoints.save(checkpoint)

        persist()

        tag = engine.RunTag(
            run_at=checkpoint.started_at,
            run_id=checkpoint.run_id,
            entity=entity,
            entity_rid=rid,
        )

        arguments = {
            key: value
            for key, value in vars(namespace).items()
            if key not in ("env", "apply", "yes", "actor", "verbose")
        }

        with AuditedRun(
            f"purge-{entity}",
            args.env,
            applied=args.apply,
            arguments=arguments,
            actor=args.actor,
            sink=audit_sink,
        ) as audited:
            audited.note(f"run {checkpoint.run_id}")
            if model is not None:
                audited.note(f"data model {model.version} ({model.fingerprint[:12]})")
            else:
                audited.note("ran without a data-model snapshot")
            for note in plan.notes:
                audited.note(note)

            ok, error = engine.run_steps(
                pool,
                plan.steps,
                plan.schema_for,
                plan.scoper,
                tag,
                cache,
                chunk_size=namespace.chunk_size,
                dry_run=not args.apply,
                log=log,
                metrics=checkpoint.metrics,
                completed=checkpoint.completed,
                persist=persist,
                on_rows=audited.record_rows,
            )

            if ok:
                findings, clean = engine.audit(
                    pool,
                    plan.steps,
                    plan.schema_for,
                    plan.scoper,
                    checkpoint.metrics,
                    not args.apply,
                    log,
                )
                checkpoint.findings = findings
                checkpoint.audit_clean = clean
            else:
                checkpoint.error = error

            checkpoint.finished_at = datetime.now(UTC).isoformat()
            persist()

            paths = reporting.write_report(checkpoint, args.apply, namespace.out_dir)
            totals = reporting.summarise(checkpoint)
            log(f"\nreport: {paths['text']}")

            if not ok:
                audited.mark_failed(error or "purge failed")
                log(f"FAILED: {error}")
                log("Committed batches are persisted; re-run to resume where this stopped.")
                return EXIT_FAILED

            if checkpoint.audit_clean is False:
                audited.mark_failed(f"{len(checkpoint.findings)} audit finding(s)")
                log(f"AUDIT FOUND {len(checkpoint.findings)} ISSUE(S) — see the report")
                return EXIT_FAILED

            if args.apply:
                log(
                    f"\ndeleted {totals['rows_deleted']} row(s) "
                    f"(backed up {totals['rows_backed_up']}) "
                    f"across {totals['tables_with_rows']} table(s)"
                )
            else:
                log(
                    f"\nwould delete {totals['rows_in_scope']} row(s) "
                    f"across {totals['tables_with_rows']} table(s). "
                    f"Re-run with --apply to write."
                )

            if totals["unscoped_tables"]:
                log(
                    f"{len(totals['unscoped_tables'])} table(s) could not be scoped and were "
                    f"left untouched — see the report"
                )
            return EXIT_OK


def main(**kwargs) -> None:
    """Entry-point wrapper that turns the return code into an exit."""
    try:
        sys.exit(run(**kwargs))
    except KeyboardInterrupt:
        print("\nInterrupted. Committed batches are persisted; re-run to resume.")
        sys.exit(130)
