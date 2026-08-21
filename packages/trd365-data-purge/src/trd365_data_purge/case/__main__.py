"""
``purge-case`` — remove one case (a credit study) and its whole subtree.

    python -m trd365_data_purge.case --env dev --account-id ACC-00459 --case-rid P001-abc
    python -m trd365_data_purge.case --env dev --account-id ACC-00459 --case-rid P001-abc --apply

Dry run is the default, a deliberate reversal of the original tool; see
:mod:`trd365_core.cli`.
"""

from __future__ import annotations

from .. import cli
from . import manifest as M
from . import scoping

DESCRIPTION = """\
Purge one case: back up and delete its rows from the account's org schema and
then the case-owned rows in the shared main schema.

A case purge is a pure subtree delete — no aggregate outside the case depends on
it, so nothing is recalculated afterwards. Backups are written to the data_purge
schema of each database touched, tagged with the run id, and the run is audited
afterwards to confirm only the intended rows were removed. Tables that cannot be
tied to the case are reported and left completely untouched.
"""


def configure(parser) -> None:
    parser.add_argument(
        "--account-id",
        "--account-rid",
        dest="account_ref",
        required=True,
        metavar="ACCOUNT",
        help=(
            "The account the case belongs to, as its reference number (ACC-00459) "
            "or its rid. Needed because the case's rows live in that account's "
            "org schema."
        ),
    )
    parser.add_argument(
        "--case-rid",
        required=True,
        help="The rid of the case to purge, from the org schema's cases table.",
    )


def entity_rid(namespace) -> str:
    return namespace.case_rid


def resolve(ctx: cli.ResolverContext) -> cli.PurgePlan:
    """Resolve the account, confirm the case is in its schema, assemble the plan."""
    rid = ctx.namespace.case_rid
    account_ref = ctx.namespace.account_ref

    case = scoping.resolve_case(ctx.pool, ctx.cache, account_ref, rid)

    if not case.exists:
        # `cases` is the last table of the FIRST step, so a run interrupted after
        # it cannot re-resolve itself. The checkpoint carries the org schema, which
        # is the only thing resolution contributes.
        resumed = scoping.resumed_from(ctx.saved, rid)
        if resumed is not None:
            case = resumed
            ctx.log("  the case row is already deleted; resuming the remaining steps")
        elif not case.account.exists:
            raise cli.TargetNotFound(
                f"no account matches {account_ref!r} in {M.MAIN_SCHEMA}.account, so there "
                f"is no schema to look for case {rid} in."
            )
        else:
            raise cli.TargetNotFound(
                f"case {rid} is not in {case.org_schema}.cases, and no checkpoint exists "
                f"to resume from. Either it is already purged, the rid is wrong, or it "
                f"belongs to a different account."
            )

    ctx.log(f"  account     : {case.account.r_number or case.account.rid}")
    ctx.log(f"  org schema  : {case.org_schema}")

    notes: list[str] = []
    if M.KNOWN_UNSCOPED:
        notes.append(
            "expected unscoped (no case link in the schema): "
            + ", ".join(sorted(M.KNOWN_UNSCOPED))
        )

    return cli.PurgePlan(
        entity_rid=rid,
        steps=M.STEPS,
        schema_for={"org": case.org_schema, **scoping.FIXED_SCHEMAS},
        scoper=scoping.CaseScoper(case=case, cache=ctx.cache),
        resolved=case.to_dict(),
        notes=notes,
    )


def main(argv: list[str] | None = None) -> None:
    cli.main(
        entity="case",
        description=DESCRIPTION,
        resolver=resolve,
        entity_rid=entity_rid,
        configure=configure,
        argv=argv,
    )


if __name__ == "__main__":
    main()
