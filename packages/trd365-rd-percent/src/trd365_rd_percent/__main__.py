"""
``rd-percent-update`` — correct a project's R&D percentages.

    python -m trd365_rd_percent --env dev \\
        --account-id ACC-00459 --project-code "FY25 Project 1" --fiscal-year 2025 \\
        --potential-ai 60 --adjustment 5 --final 65
    ... --apply

Dry run is the default. A dry run here *is* free: it resolves the target, computes
every figure, and prints what would be written without opening a write
transaction.

Batching over a CSV, which the legacy tool supported, is not repeated. One
invocation corrects one project fiscal and produces one audit record; running a
list is the orchestrator's job, where each becomes a job with its own approval and
outcome — the same decision taken for the purges.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from trd365_core.audit import AuditedRun
from trd365_core.cli import build_parser, common_args, confirm_production, describe_mode
from trd365_core.db import ConnectionPool
from trd365_core.errors import Trd365Error

from . import calculation as calc
from . import resolve as R
from . import subcon, writes

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_TARGET_NOT_FOUND = 3

DESCRIPTION = """\
Correct one project fiscal's R&D percentages and everything the application would
recompute from them: QRE dollars per component, qualification, the case module's
copies, the shared main-database summary, and the audit trail.

Reproduces the write path of the application's own updateQreAdjustment mutation.
The three percentages must be internally consistent — final = potential +
adjustment — because the application always derives the final one that way, and
writing an inconsistent set would produce a state it could never produce.

Sub-contractor QRE is capped at the percentage configured for the project's
jurisdiction. The legacy Node tool omitted that cap and so overstated
sub-contractor QRE, typically by half again.

Rows are snapshotted into <schema>.rd_percent_backup before being overwritten, in
the same transaction, so a backup and its change commit or roll back together.
"""


def configure(parser) -> None:
    parser.add_argument(
        "--account-id", required=True, help="Account ID from the UI, e.g. ACC-00459."
    )
    parser.add_argument("--project-code", required=True, help="The project's code.")
    parser.add_argument("--fiscal-year", required=True, type=int, help="The fiscal year.")
    parser.add_argument(
        "--potential-ai",
        required=True,
        type=float,
        metavar="PERCENT",
        help="rd_percent_potential_ai to store. Must be >= 0.",
    )
    parser.add_argument(
        "--adjustment",
        required=True,
        type=float,
        metavar="PERCENT",
        help="rd_percent_adjustment — the delta, which may be negative.",
    )
    parser.add_argument(
        "--final",
        required=True,
        type=float,
        metavar="PERCENT",
        help="rd_percent_final. Must equal potential-ai + adjustment.",
    )
    parser.add_argument("--comments", default=None, help="Free text for the history row.")
    parser.add_argument(
        "--out-dir", type=Path, default=Path("reports"), help="Where to write the run report."
    )


def run(argv: list[str] | None = None, *, pool_factory=ConnectionPool, audit_sink=None) -> int:
    parser = build_parser(DESCRIPTION)
    configure(parser)
    namespace = parser.parse_args(argv)
    args = common_args(namespace)

    def log(message: str) -> None:
        print(message, flush=True)

    log(describe_mode(args, "rd-percent-update"))
    log(f"  account     : {namespace.account_id}")
    log(f"  project     : {namespace.project_code} FY{namespace.fiscal_year}")

    try:
        confirm_production(args, "rd-percent-update")
        # Refuse an impossible set of percentages before touching a database, so
        # the operator is told while it is still only a typo.
        calc.check_consistent(namespace.potential_ai, namespace.adjustment, namespace.final)
    except Trd365Error as exc:
        log(str(exc))
        return EXIT_FAILED

    with pool_factory(args.env, log=log) as pool:
        main_conn = pool.get("maindb")
        org_conn = pool.get("orgdb")

        try:
            target = R.resolve(
                main_conn,
                org_conn,
                account_id=namespace.account_id,
                project_code=namespace.project_code,
                fiscal_year=namespace.fiscal_year,
            )
        except R.NotFound as exc:
            log(f"NOT FOUND: {exc}")
            return EXIT_TARGET_NOT_FOUND

        log(f"  schema      : {target.schema}")
        log(f"  fiscal rid  : {target.project_fiscal_rid}")

        cap = subcon.resolve(
            lambda sql, params: _fetch(main_conn, sql, params),
            country_rid=target.country_rid,
            fiscal_year=target.fiscal_year,
            account_fiscal_start=target.fiscal_start,
            account_fiscal_end=target.fiscal_end,
        )
        log(f"  sub-con cap : {cap.percent}%  ({cap.reason})")

        try:
            qre = calc.compute(
                potential_ai=namespace.potential_ai,
                adjustment=namespace.adjustment,
                costs=calc.Costs.from_row(target.row),
                sub_con_percent=cap.percent,
            )
        except Trd365Error as exc:
            log(str(exc))
            return EXIT_FAILED

        log("  computed    :")
        for key, value in qre.to_dict().items():
            log(f"      {key:26} {value}")

        applied = writes.Applied(backup=writes.Backup(run_id=writes.new_run_id()))

        if not args.apply:
            log("\nDRY RUN — nothing was written. Re-run with --apply.")
            _write_report(namespace, target, cap, qre, applied, dry_run=True, log=log)
            return EXIT_OK

        closed = R.closed_case_status(main_conn)
        event_type_rid, created_by_name = R.ui_event_type(main_conn)
        if closed is None:
            log(
                "  WARNING     : no closed case status resolved; the case-module tables "
                "will be left alone rather than risk rewriting frozen financials."
            )

        with AuditedRun(
            "rd-percent-update",
            args.env,
            applied=True,
            arguments=vars(namespace),
            actor=args.actor,
            sink=audit_sink,
        ) as audited:
            audited.note(f"sub-con cap {cap.percent}% ({cap.reason})")
            audited.note(f"backup run id {applied.backup.run_id}")
            try:
                log("\n  org database:")
                writes.apply_org(
                    org_conn,
                    schema=target.schema,
                    project_fiscal_rid=target.project_fiscal_rid,
                    project_rid=target.project_rid,
                    project_code=target.project_code,
                    account_rid=target.account_rid,
                    qre=qre,
                    closed_status_rid=closed,
                    event_type_rid=event_type_rid,
                    created_by_name=created_by_name,
                    comments=namespace.comments,
                    applied=applied,
                    log=log,
                )
                org_conn.commit()
                log("    committed")
            except Exception as exc:
                org_conn.rollback()
                audited.mark_failed(f"org database: {exc}")
                log(f"FAILED on the org database, rolled back: {exc}")
                return EXIT_FAILED

            try:
                log("  main database:")
                writes.apply_main(
                    main_conn, project_fiscal_rid=target.project_fiscal_rid, qre=qre,
                    applied=applied,
                )
                main_conn.commit()
                log("    committed")
            except Exception as exc:
                main_conn.rollback()
                # The org side is already committed and cannot be undone from here.
                # Say so precisely: this is the partial state the application itself
                # can leave, and the fix is to re-run this record.
                audited.mark_failed(f"main database: {exc}")
                audited.note("org database committed; main database did not")
                log(f"FAILED on the main database, rolled back: {exc}")
                log(
                    "  The org database changes ARE committed. The main-database statement "
                    "is idempotent, so re-running this same command finishes the record. "
                    f"Backups are under run id {applied.backup.run_id}."
                )
                return EXIT_FAILED

            for table, count in sorted(applied.updated.items()):
                audited.record_rows(f"{target.schema}.{table}", count)

        for note in applied.skipped:
            log(f"  skipped     : {note}")
        log(f"\n  backed up   : {applied.backup.total} row(s) under {applied.backup.run_id}")
        _write_report(namespace, target, cap, qre, applied, dry_run=False, log=log)

    log("DONE.")
    return EXIT_OK


def _fetch(conn, sql: str, params: list) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _write_report(namespace, target, cap, qre, applied, *, dry_run: bool, log) -> None:
    out_dir: Path = namespace.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    at = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in target.project_fiscal_rid)
    path = out_dir / f"rd_percent_{safe}_{at}.json"
    path.write_text(
        json.dumps(
            {
                "mode": "dry-run" if dry_run else "apply",
                "target": target.to_dict(),
                "sub_con": {"percent": cap.percent, "reason": cap.reason},
                "computed": qre.to_dict(),
                "writes": applied.to_dict(),
                "generated_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    log(f"report: {path}")


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main()
