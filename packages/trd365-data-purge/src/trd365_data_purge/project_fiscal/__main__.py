"""
``purge-project-fiscal`` — delete one fiscal year of one project, with recompute.

    python -m trd365_data_purge.project_fiscal --env dev \\
        --account-id ACC-00459 --project-fiscal-rid P001-abc
    python -m trd365_data_purge.project_fiscal --env dev \\
        --account-id ACC-00459 --project-fiscal-rid P001-abc --apply

This does not use the row-level engine. It runs the vendor's SECTION 1-8 SQL,
which deletes *and recomputes* the financial aggregates that survive the
deletion. See :mod:`trd365_data_purge.sections`.

**A dry run here is not free.** Everywhere else in this package a dry run counts
rows and touches nothing. These sections cannot be previewed that way, because
they recompute: the only way to see what they would do is to do it inside a
transaction and then roll it back. Same locks, same work, result discarded.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from trd365_core.audit import AuditedRun
from trd365_core.cli import build_parser, common_args, confirm_production, describe_mode
from trd365_core.db import ConnectionPool
from trd365_core.errors import Trd365Error

from .. import sections as S
from ..engine import SchemaCache
from . import BACKUP_SCHEMA, BASE_SQL, flow, resolve

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_TARGET_NOT_FOUND = 3

DESCRIPTION = """\
Delete one project fiscal year across the org schema, the shared main schema and
trd365ai, and recompute the aggregates that survive it.

Unlike the account, case and interaction purges this runs the vendor's SECTION
1-8 SQL rather than enumerating rows, because the deletion has to be followed by
a financial recompute that must not be re-derived.

is_last_fiscal is worked out automatically: TRUE only when this is the project's
only remaining fiscal, in which case the project row and its project-level
children go too and the account totals are recomputed. Override it with
--last-fiscal / --not-last-fiscal when a previous failed run has already removed
a sibling and left the count misleading.

A DRY RUN OF THIS UTILITY IS NOT FREE. It executes the deletes and the recompute
inside a transaction that is then rolled back, because SQL that recomputes cannot
be previewed any other way.
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
        "--project-fiscal-rid",
        required=True,
        help="The rid of the project fiscal to delete, from the org schema's project_fiscal.",
    )
    last = parser.add_mutually_exclusive_group()
    last.add_argument(
        "--last-fiscal",
        dest="force_last",
        action="store_true",
        default=None,
        help="Force is_last_fiscal TRUE: also delete the project row and recompute account totals.",
    )
    last.add_argument(
        "--not-last-fiscal",
        dest="force_last",
        action="store_false",
        help="Force is_last_fiscal FALSE: keep the project and recompute its rollups.",
    )
    add_section_arguments(parser)


def add_section_arguments(parser) -> None:
    """Flags shared with the whole-project purge."""
    parser.add_argument(
        "--sections",
        nargs="*",
        type=int,
        metavar="N",
        help=(
            "Run only these sections, e.g. --sections 4 5 8 to re-run the audit "
            "after a failure. Omit for all eight, in order."
        ),
    )
    parser.add_argument(
        "--backup-schema",
        default=BACKUP_SCHEMA,
        help=(
            "The schema every section backs up into. Override to resume into the "
            f"schema an earlier run created. Default {BACKUP_SCHEMA!r}."
        ),
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=int,
        default=15,
        metavar="SECONDS",
        help=(
            "How often to report that a section is still running. Each section is "
            "one DO block that emits nothing until it finishes, so without this "
            "there is no way to tell slow from hung. 0 to stay quiet."
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("reports"),
        help="Where to write the run report.",
    )


def sections_for(namespace) -> list[S.Section]:
    found = S.discover(BASE_SQL)
    if not namespace.sections:
        return found
    wanted = set(namespace.sections)
    chosen = [section for section in found if section.number in wanted]
    missing = wanted - {section.number for section in chosen}
    if missing:
        raise Trd365Error(f"no such section(s): {', '.join(str(n) for n in sorted(missing))}")
    return chosen


def write_report(
    entity: str, rid: str, context: dict, outcomes: list, out_dir: Path, dry_run: bool
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    at = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in rid)
    path = out_dir / f"{entity}_{safe}_{at}.json"
    path.write_text(
        json.dumps(
            {
                "entity": entity,
                "entity_rid": rid,
                "mode": "dry-run" if dry_run else "apply",
                "context": context,
                "fiscals": [outcome.to_dict() for outcome in outcomes],
                "generated_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return path


def run(argv: list[str] | None = None, *, pool_factory=ConnectionPool, audit_sink=None) -> int:
    # build_parser already carries --env, --apply, --yes, --verbose and --actor.
    # trd365_data_purge.cli.add_common_arguments is deliberately NOT used: its
    # flags — chunk size, checkpoints, the model snapshot — belong to the row-level
    # engine, and none of them mean anything to SQL the vendor wrote.
    parser = build_parser(DESCRIPTION)
    configure(parser)
    namespace = parser.parse_args(argv)
    args = common_args(namespace)

    def log(message: str) -> None:
        print(message, flush=True)

    log(describe_mode(args, "purge-project-fiscal"))
    log(f"  target      : {namespace.project_fiscal_rid}")
    log(f"  backups into: schema {namespace.backup_schema!r} of each database touched")
    if not args.apply:
        log(
            "  NOTE        : a dry run of this utility executes the deletes and the "
            "recompute, then rolls back. It is not free."
        )

    try:
        confirm_production(args, "purge-project-fiscal")
        section_list = sections_for(namespace)
    except Trd365Error as exc:
        log(str(exc))
        return EXIT_FAILED

    if namespace.sections:
        log(f"  sections    : {', '.join(str(s.number) for s in section_list)} only")

    cache = SchemaCache()
    with pool_factory(args.env, log=log) as pool:
        fiscal = resolve.resolve_fiscal(
            pool,
            cache,
            account_ref=namespace.account_ref,
            fiscal_rid=namespace.project_fiscal_rid,
            force_last=namespace.force_last,
        )
        if not fiscal.exists:
            if not fiscal.account.exists:
                log(f"NOT FOUND: no account matches {namespace.account_ref!r}.")
            else:
                log(
                    f"NOT FOUND: {namespace.project_fiscal_rid} is not in "
                    f"{fiscal.org_schema}.project_fiscal."
                )
            return EXIT_TARGET_NOT_FOUND

        log(f"  account     : {fiscal.account.r_number or fiscal.account.rid}")
        log(f"  org schema  : {fiscal.org_schema}")
        log(f"  project     : {fiscal.project_rid}")
        log(f"  fiscal year : {fiscal.year}")
        log(
            f"  last fiscal : {fiscal.is_last} "
            f"({fiscal.decided_by}; the project has {fiscal.siblings} fiscal(s))"
        )
        for note in fiscal.notes:
            log(f"  note        : {note}")

        with AuditedRun(
            "purge-project-fiscal",
            args.env,
            applied=args.apply,
            arguments=vars(namespace),
            actor=args.actor,
            sink=audit_sink,
        ) as audited:
            for note in fiscal.notes:
                audited.note(note)
            outcome = flow.run_fiscal(
                pool,
                section_list,
                fiscal.params,
                backup_schema=namespace.backup_schema,
                dry_run=not args.apply,
                log=log,
                verbose=namespace.verbose,
                heartbeat_seconds=namespace.heartbeat_seconds,
            )
            if outcome.status != "ok":
                audited.mark_failed(outcome.error or "a section failed")
                last = outcome.last_committed
                if last is not None:
                    audited.note(f"last committed section: {last.name}")

        report = write_report(
            "project_fiscal",
            fiscal.rid,
            fiscal.to_dict(),
            [outcome],
            namespace.out_dir,
            not args.apply,
        )
        log(f"\nreport: {report}")

        if outcome.status != "ok":
            log(f"FAILED — {outcome.error}")
            last = outcome.last_committed
            if last is not None and args.apply:
                log(
                    f"  {last.name} was the last section to commit. The run is "
                    f"half-applied; re-run with --sections from {last.number + 1} once "
                    f"the cause is fixed, and --backup-schema {namespace.backup_schema}."
                )
            return EXIT_FAILED

    log("DRY RUN complete — nothing was kept." if not args.apply else "DONE.")
    return EXIT_OK


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main()
