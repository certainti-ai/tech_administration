"""
``data-model-analysis`` — introspect the model, save it, and report on its health.

This utility is the **producer** of the shared data-model snapshot (PRD
FR-1.9/1.10). Every other utility is a consumer: they call ``require_model()``
and refuse to act on a model that is missing or stale. Nothing else writes a
snapshot, so until this has run against an environment, the destructive tools
there cannot ``--apply``.

    python -m trd365_analysis --env dev                        # every tenant schema
    python -m trd365_analysis --env dev --schemas trd365_00042
    python -m trd365_analysis --env dev --no-orphans           # structure only, cheap
    python -m trd365_analysis --env dev --all-entities         # widen the orphan scan

It is read-only against the databases. ``--apply`` is what makes the snapshot
durable: without it the analysis runs and reports, and nothing is saved. That
keeps the shared model from being replaced as a side effect of someone looking.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from trd365_core.audit import AuditedRun
from trd365_core.cli import build_parser, common_args, describe_mode
from trd365_core.datamodel import DEFAULT_MAIN_SCHEMA, tenant_schemas
from trd365_core.db import ConnectionPool
from trd365_core.errors import Trd365Error
from trd365_core.model_snapshot import FileModelStore, build_snapshot, diff_snapshots

from . import deviations as dev
from . import orphans, reporting

EXIT_OK = 0
EXIT_FAILED = 1

DEFAULT_OUT_DIR = Path("reports")


def build_argument_parser():
    parser = build_parser(__doc__.split("\n\n")[0].strip())
    parser.add_argument(
        "--schemas",
        nargs="*",
        default=None,
        help="Tenant schemas to analyse. Default: every trd365_* schema.",
    )
    parser.add_argument(
        "--main-schema",
        default=DEFAULT_MAIN_SCHEMA,
        help=f"The shared schema holding the account table (default {DEFAULT_MAIN_SCHEMA}).",
    )
    parser.add_argument(
        "--no-orphans",
        action="store_true",
        help="Skip the orphan scan. Structure and deviations only, and much cheaper.",
    )
    parser.add_argument(
        "--all-entities",
        action="store_true",
        help=(
            "Scan every resolved reference for orphans, not just the four primary "
            "entities. Slower, and more prone to false positives."
        ),
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=orphans.DEFAULT_SAMPLE,
        help=f"Example rids to record per orphaned edge (default {orphans.DEFAULT_SAMPLE}).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Directory for the reports (default ./{DEFAULT_OUT_DIR}).",
    )
    return parser


def run(
    argv: list[str] | None = None,
    *,
    pool_factory=ConnectionPool,
    store: Any = None,
    audit_sink=None,
) -> int:
    parser = build_argument_parser()
    namespace = parser.parse_args(argv)
    args = common_args(namespace)

    def log(message: str) -> None:
        print(message, flush=True)

    log(describe_mode(args, "data-model-analysis"))
    model_store = store if store is not None else FileModelStore()

    with AuditedRun(
        "data-model-analysis",
        args.env,
        applied=args.apply,
        arguments={
            key: value
            for key, value in vars(namespace).items()
            if key not in ("env", "apply", "yes", "actor", "verbose")
        },
        actor=args.actor,
        sink=audit_sink,
    ) as audited:
        try:
            with pool_factory(args.env, log=log) as pool:
                fetch = pool.fetcher()

                names = namespace.schemas
                if not names:
                    names = tenant_schemas(fetch)
                    log(f"  discovered {len(names)} tenant schema(s)")
                if not names:
                    audited.mark_failed("no tenant schemas found")
                    log("no tenant schemas found — nothing to analyse")
                    return EXIT_FAILED

                log(f"\n  building the model for {len(names)} schema(s)…")
                snapshot = build_snapshot(
                    fetch,
                    args.env,
                    generated_by=args.actor or "data-model-analysis",
                    schemas=names,
                    main_schema=namespace.main_schema,
                    on_schema=lambda name: log(f"    {name}"),
                )

                # Cross-schema, before saving, so consumers read the good answer
                # and nobody has to remember a second pass. See deviations.py.
                changes = dev.apply_to(snapshot)
                if changes:
                    withdrawn = len([c for c in changes if c.is_downgrade])
                    log(
                        f"  reclassified {len(changes)} deviation(s) using cross-schema "
                        f"evidence, withdrawing {withdrawn} false typo(s)"
                    )
                    audited.note(f"reclassified {len(changes)} deviation(s)")

                scans: list = []
                if not namespace.no_orphans:
                    log("\n  scanning for orphan rows…")
                    scans = orphans.scan(
                        fetch,
                        snapshot,
                        schemas=names,
                        all_entities=namespace.all_entities,
                        sample=namespace.sample,
                        log=log,
                    )

        except Trd365Error as exc:
            audited.mark_failed(str(exc))
            log(f"FAILED: {exc}")
            return EXIT_FAILED

        previous = model_store.latest(args.env)
        digest = reporting.summary(snapshot, scans, changes)
        for key in ("schemas", "reclassified"):
            audited.note(f"{key}={digest[key]}")

        if previous is not None:
            difference = diff_snapshots(previous, snapshot)
            if difference.changed:
                log(f"\n  the model CHANGED since {previous.version}: {difference.summary()}")
                audited.note(f"model changed since {previous.version}: {difference.summary()}")
            else:
                log(f"\n  the model is unchanged since {previous.version}")

        paths = reporting.write_reports(snapshot, scans, changes, namespace.out_dir)
        log("\n" + reporting.render_text(snapshot, scans, changes))
        for name, path in sorted(paths.items()):
            log(f"{name} report: {path}")

        if args.apply:
            version = model_store.save(snapshot)
            audited.note(f"saved model {version}")
            log(f"\nsaved the model as {version}; consumers will pick it up on their next run")
        else:
            log(
                "\nnothing was saved. The shared model is unchanged — re-run with --apply "
                "to publish this one to the other utilities."
            )

        broken = [scan for scan in scans if scan.error is not None]
        if broken:
            names = ", ".join(scan.schema for scan in broken)
            audited.mark_failed(f"{len(broken)} schema(s) could not be scanned: {names}")
            log(f"\n{len(broken)} schema(s) could not be scanned: {names}")
            # The model was still built, and saved if asked — it is the orphan
            # scan that is incomplete, and saying so beats reporting a low
            # orphan count as though it were the whole picture.
            return EXIT_FAILED

        unchecked = sum(len(scan.failed_edges) for scan in scans)
        if unchecked:
            audited.note(f"{unchecked} edge(s) could not be checked")
            log(f"\n{unchecked} edge(s) could not be checked — recorded in the orphans CSV")

        return EXIT_OK


def main(argv: list[str] | None = None) -> None:
    try:
        sys.exit(run(argv))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
