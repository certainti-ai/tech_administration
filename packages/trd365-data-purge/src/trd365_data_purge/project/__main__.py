"""
``purge-project`` — delete a whole project: every fiscal year, in order.

    python -m trd365_data_purge.project --env dev \\
        --account-id ACC-00459 --project P001-abc
    python -m trd365_data_purge.project --env dev \\
        --account-id ACC-00459 --project "Infosys FY25 Project 1" --apply

This is the project-fiscal purge run once per fiscal, oldest first, with the last
one removing the project row and recomputing the account totals. Same SQL, same
recompute — which is what keeps deleting a project identical to deleting its
years one at a time.

**A dry run here is not free**, for the same reason and once per fiscal year. See
:mod:`trd365_data_purge.sections`.
"""

from __future__ import annotations

from trd365_core.audit import AuditedRun
from trd365_core.cli import build_parser, common_args, confirm_production, describe_mode
from trd365_core.db import ConnectionPool
from trd365_core.errors import Trd365Error

from ..engine import SchemaCache
from ..project_fiscal import flow, resolve
from ..project_fiscal.__main__ import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_TARGET_NOT_FOUND,
    add_section_arguments,
    sections_for,
    write_report,
)

DESCRIPTION = """\
Delete a whole project — every fiscal year — across the org schema, the shared
main schema and trd365ai, recomputing the aggregates as it goes.

Each fiscal is deleted by the vendor's SECTION 1-8 flow, oldest first. Only the
final fiscal carries is_last_fiscal, and that run is the one that also removes the
project row and its project-level children and recomputes the account totals.

Fiscals are processed in year order rather than in whatever order the database
returns them, because which one is last decides where the recompute happens.

A DRY RUN OF THIS UTILITY IS NOT FREE. Each fiscal's sections execute their
deletes and recompute inside a transaction that is then rolled back, because SQL
that recomputes cannot be previewed any other way.
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
    parser.add_argument(
        "--project",
        "--project-rid",
        dest="project_ref",
        required=True,
        metavar="PROJECT",
        help="The project, as its rid or its project code.",
    )
    parser.add_argument(
        "--stop-on-first-failure",
        action="store_true",
        default=True,
        help=(
            "Stop as soon as one fiscal fails, rather than continuing. On by "
            "default: a failed fiscal means the recompute chain is already "
            "inconsistent, and pressing on compounds it."
        ),
    )
    add_section_arguments(parser)


def run(argv: list[str] | None = None, *, pool_factory=ConnectionPool, audit_sink=None) -> int:
    parser = build_parser(DESCRIPTION)
    configure(parser)
    namespace = parser.parse_args(argv)
    args = common_args(namespace)

    def log(message: str) -> None:
        print(message, flush=True)

    log(describe_mode(args, "purge-project"))
    log(f"  target      : {namespace.project_ref}")
    log(f"  backups into: schema {namespace.backup_schema!r} of each database touched")
    if not args.apply:
        log(
            "  NOTE        : a dry run of this utility executes the deletes and the "
            "recompute for every fiscal, then rolls each back. It is not free."
        )

    try:
        confirm_production(args, "purge-project")
        section_list = sections_for(namespace)
    except Trd365Error as exc:
        log(str(exc))
        return EXIT_FAILED

    cache = SchemaCache()
    with pool_factory(args.env, log=log) as pool:
        account, project_rid, fiscals = resolve.resolve_project(
            pool, cache, account_ref=namespace.account_ref, project_ref=namespace.project_ref
        )
        if not account.exists:
            log(f"NOT FOUND: no account matches {namespace.account_ref!r}.")
            return EXIT_TARGET_NOT_FOUND
        if project_rid is None:
            log(
                f"NOT FOUND: {namespace.project_ref!r} is not a project in "
                f"{account.org_schema}, by rid or by code."
            )
            return EXIT_TARGET_NOT_FOUND

        log(f"  account     : {account.r_number or account.rid}")
        log(f"  org schema  : {account.org_schema}")
        log(f"  project     : {project_rid}")

        if not fiscals:
            # Not an error, and not something to invent a deletion for: the
            # project row exists with no fiscal years, so there is no SECTION run
            # that would remove it. Say so rather than reporting success.
            log(
                "\nThis project has no fiscal years. The SECTION flow deletes a project "
                "only as part of deleting its last fiscal, so there is nothing here to "
                "run — the bare project row needs a decision from a human, not a purge."
            )
            return EXIT_FAILED

        plan = resolve.plan_project_fiscals(account, project_rid, fiscals)
        log(f"  fiscals     : {len(plan)}, oldest first")
        for entry in plan:
            marker = "  <- last: also deletes the project row" if entry["is_last_fiscal"] else ""
            year = entry["fiscal_year"] or "(no year)"
            log(f"      {year}  {entry['project_fiscal_id']}{marker}")

        outcomes = []
        failed = None
        with AuditedRun(
            "purge-project",
            args.env,
            applied=args.apply,
            arguments=vars(namespace),
            actor=args.actor,
            sink=audit_sink,
        ) as audited:
            audited.note(f"{len(plan)} fiscal(s)")
            for index, entry in enumerate(plan, start=1):
                log(f"\n  === fiscal {index}/{len(plan)}: {entry['project_fiscal_id']} ===")
                outcome = flow.run_fiscal(
                    pool,
                    section_list,
                    entry,
                    backup_schema=namespace.backup_schema,
                    dry_run=not args.apply,
                    log=log,
                    verbose=namespace.verbose,
                    heartbeat_seconds=namespace.heartbeat_seconds,
                )
                outcomes.append(outcome)
                if outcome.status != "ok":
                    failed = outcome
                    audited.note(f"fiscal {entry['project_fiscal_id']} failed: {outcome.error}")
                    if namespace.stop_on_first_failure:
                        break
            if failed is not None:
                audited.mark_failed(failed.error or "a fiscal failed")

        report = write_report(
            "project",
            project_rid,
            {
                "account_rid": account.rid,
                "r_number": account.r_number,
                "org_schema": account.org_schema,
                "project_rid": project_rid,
                "fiscals": len(plan),
            },
            outcomes,
            namespace.out_dir,
            not args.apply,
        )
        log(f"\nreport: {report}")

        if failed is not None:
            done = len(outcomes) - 1
            log(f"FAILED on fiscal {len(outcomes)} of {len(plan)} — {failed.error}")
            if args.apply:
                last = failed.last_committed
                log(
                    f"  {done} fiscal(s) completed before this one and are already "
                    f"applied. Within the failed fiscal, "
                    + (
                        f"{last.name} was the last section to commit."
                        if last is not None
                        else "no section committed."
                    )
                )
                log(
                    f"  Re-run purge-project-fiscal for {failed.project_fiscal_id} with "
                    f"--backup-schema {namespace.backup_schema} once the cause is fixed, "
                    f"then re-run this to finish the remaining fiscal(s)."
                )
            return EXIT_FAILED

    log(
        f"\n{'DRY RUN complete — nothing was kept.' if not args.apply else 'DONE.'} "
        f"{len(outcomes)} fiscal(s)."
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main()
