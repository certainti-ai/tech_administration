"""
``purge-interaction`` — remove one interaction and the subtree it owns.

    python -m trd365_data_purge.interaction --env dev --account-id ACC-00459 \\
        --interaction-rid P001-abc

Dry run is the default, a deliberate reversal of the original tool; see
:mod:`trd365_core.cli`.
"""

from __future__ import annotations

from .. import cli
from . import manifest as M
from . import scoping

DESCRIPTION = """\
Purge one interaction: back up and delete its rows from the account's org schema
and then the interaction-owned rows in the shared main schema.

A pure subtree delete — nothing outside the interaction aggregates it, so nothing
is recalculated afterwards. chat_sessions is deliberately never touched: it
carries an interaction_rid without being owned by the interaction, and a
conversation is meant to outlive the interaction it was started from.
"""


def configure(parser) -> None:
    parser.add_argument(
        "--account-id",
        "--account-rid",
        dest="account_ref",
        required=True,
        metavar="ACCOUNT",
        help=(
            "The account the interaction belongs to, as its reference number "
            "(ACC-00459) or its rid. Needed because the interaction's rows live in "
            "that account's org schema."
        ),
    )
    parser.add_argument(
        "--interaction-rid",
        required=True,
        help="The rid of the interaction to purge, from the org schema's interactions table.",
    )


def entity_rid(namespace) -> str:
    return namespace.interaction_rid


def resolve(ctx: cli.ResolverContext) -> cli.PurgePlan:
    """Resolve the account, confirm the interaction is in its schema, plan the run."""
    rid = ctx.namespace.interaction_rid
    account_ref = ctx.namespace.account_ref

    interaction = scoping.resolve_interaction(ctx.pool, ctx.cache, account_ref, rid)

    if not interaction.exists:
        # `interactions` is the last table of the FIRST step, so a run interrupted
        # after it cannot re-resolve itself.
        resumed = scoping.resumed_from(ctx.saved, rid)
        if resumed is not None:
            interaction = resumed
            ctx.log("  the interaction row is already deleted; resuming the remaining steps")
        elif not interaction.account.exists:
            raise cli.TargetNotFound(
                f"no account matches {account_ref!r} in {M.MAIN_SCHEMA}.account, so there "
                f"is no schema to look for interaction {rid} in."
            )
        else:
            raise cli.TargetNotFound(
                f"interaction {rid} is not in {interaction.org_schema}.interactions, and no "
                f"checkpoint exists to resume from. Either it is already purged, the rid is "
                f"wrong, or it belongs to a different account."
            )

    ctx.log(f"  account     : {interaction.account.r_number or interaction.account.rid}")
    ctx.log(f"  org schema  : {interaction.org_schema}")

    notes = [
        "not touched by design (carries interaction_rid without owning anything): "
        + ", ".join(sorted(M.NOT_OWNED))
    ]

    return cli.PurgePlan(
        entity_rid=rid,
        steps=M.STEPS,
        schema_for={"org": interaction.org_schema, **scoping.FIXED_SCHEMAS},
        scoper=scoping.InteractionScoper(interaction=interaction, cache=ctx.cache),
        resolved=interaction.to_dict(),
        notes=notes,
    )


def main(argv: list[str] | None = None) -> None:
    cli.main(
        entity="interaction",
        description=DESCRIPTION,
        resolver=resolve,
        entity_rid=entity_rid,
        configure=configure,
        argv=argv,
    )


if __name__ == "__main__":
    main()
