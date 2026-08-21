"""
``purge-milestone-tasks`` — delete the tasks under one milestone.

    python -m trd365_data_purge.milestone_tasks --env dev \\
        --account-id ACC-00459 --case-rid P001-abc --milestone-rid P001-def
    ... --apply

The milestone row itself survives; only its tasks and their children go. Dry run
is the default and is a genuine preview — the script counts rows and skips every
delete.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from trd365_core.audit import AuditedRun
from trd365_core.cli import build_parser, common_args, confirm_production, describe_mode
from trd365_core.datamodel import PK_COLUMN
from trd365_core.db import ConnectionPool
from trd365_core.errors import Trd365Error

from .. import sections as S
from ..account.scoping import resolve_account_reference
from ..engine import SchemaCache, quote
from . import BASE_SQL, VARIABLES

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_TARGET_NOT_FOUND = 3

DESCRIPTION = """\
Delete every task belonging to one milestone of one case, and their children:
checklists and checklist items, comments and attachments, collaborators, tags,
history, the task summary rows in the case module, and the dependency mappings
that point at them. The milestone itself is kept.

This runs a hand-written script that was previously edited by hand and run in
psql. Its own dry-run flag is honoured, so a preview counts rows and deletes
nothing.
"""


def configure(parser) -> None:
    parser.add_argument(
        "--account-id",
        "--account-rid",
        dest="account_ref",
        required=True,
        metavar="ACCOUNT",
        help="The account, as its reference number (ACC-00459) or its rid.",
    )
    parser.add_argument("--case-rid", required=True, help="The case the milestone belongs to.")
    parser.add_argument("--milestone-rid", required=True, help="The milestone whose tasks go.")
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

    log(describe_mode(args, "purge-milestone-tasks"))
    log(f"  case        : {namespace.case_rid}")
    log(f"  milestone   : {namespace.milestone_rid}")

    try:
        confirm_production(args, "purge-milestone-tasks")
        sections = S.discover(BASE_SQL)
    except Trd365Error as exc:
        log(str(exc))
        return EXIT_FAILED

    cache = SchemaCache()
    with pool_factory(args.env, log=log) as pool:
        account = resolve_account_reference(pool, namespace.account_ref)
        if not account.exists:
            log(f"NOT FOUND: no account matches {namespace.account_ref!r}.")
            return EXIT_TARGET_NOT_FOUND

        conn = pool.get("orgdb")
        schema = account.org_schema
        log(f"  account     : {account.r_number or account.rid}")
        log(f"  org schema  : {schema}")

        # Confirm both exist in *this* account's schema before substituting them
        # into a script that deletes. A rid from another tenant would otherwise be
        # written into the SQL and simply match nothing — reporting success having
        # done nothing, which is the failure that looks most like success.
        for table, rid, label in (
            ("cases", namespace.case_rid, "case"),
            ("case_milestone", namespace.milestone_rid, "milestone"),
        ):
            if not cache.table_exists(conn, "orgdb", schema, table):
                log(f"NOT FOUND: {schema} has no {table} table.")
                return EXIT_TARGET_NOT_FOUND
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {PK_COLUMN} FROM {quote(schema)}.{quote(table)} "
                    f"WHERE {PK_COLUMN}=%s",
                    (rid,),
                )
                found = cur.fetchone()
            conn.rollback()
            if found is None:
                log(f"NOT FOUND: {label} {rid} is not in {schema}.{table}.")
                return EXIT_TARGET_NOT_FOUND

        params = {
            "schema": schema,
            "case_rid": namespace.case_rid,
            "milestone_rid": namespace.milestone_rid,
            # The script's own switch, driven from --apply.
            "dry_run": not args.apply,
        }

        with AuditedRun(
            "purge-milestone-tasks",
            args.env,
            applied=args.apply,
            arguments=vars(namespace),
            actor=args.actor,
            sink=audit_sink,
        ) as audited:
            notices: list[str] = []
            for section in sections:
                try:
                    prepared = S.prepare(section, params, "", VARIABLES)
                except S.SectionError as exc:
                    audited.mark_failed(str(exc))
                    log(f"REFUSED: {exc}")
                    return EXIT_FAILED

                log(f"  running {section.name} on {section.db_key}")
                try:
                    notices += S.execute(
                        pool, prepared, dry_run=not args.apply, on_progress=None, interval=0
                    )
                except Exception as exc:
                    conn.rollback()
                    audited.mark_failed(str(exc))
                    log(f"FAILED, rolled back: {exc}")
                    return EXIT_FAILED

            for notice in notices:
                log(f"    {notice}")
            audited.note(f"{len(notices)} notice(s) from the script")

        path = _write_report(namespace, params, notices, not args.apply)
        log(f"\nreport: {path}")

    log("DRY RUN complete — nothing was deleted." if not args.apply else "DONE.")
    return EXIT_OK


def _write_report(namespace, params, notices, dry_run: bool) -> Path:
    out_dir: Path = namespace.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    at = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in namespace.milestone_rid)
    path = out_dir / f"milestone_tasks_{safe}_{at}.json"
    path.write_text(
        json.dumps(
            {
                "entity": "milestone_tasks",
                "mode": "dry-run" if dry_run else "apply",
                "parameters": params,
                "notices": notices,
                "generated_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main()
