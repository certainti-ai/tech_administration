"""
``purge-account`` — remove every record belonging to one account, across all
three databases, with a backup, an audit and a report.

    python -m trd365_data_purge.account --env dev --account-rid P001-abc
    python -m trd365_data_purge.account --env dev --account-rid P001-abc --apply

Dry run is the default. This is a deliberate reversal of the original tool,
which wrote unless it was given ``--dry-run``; see :mod:`trd365_core.cli`.

Batching over a CSV of accounts, which the original supported, is not repeated
here. One invocation purges one account and produces one audit record; running
a list of them is the orchestrator's job (Phase 2), where each account becomes
a separate job with its own approval, log and outcome.
"""

from __future__ import annotations

from .. import cli
from . import manifest as M
from . import scoping

DESCRIPTION = """\
Purge one account: back up and delete its rows from the org schema, the shared
main schema, and trd365ai, in that order.

Backups are written to the data_purge schema of each database touched, tagged
with the run id, and the run is audited afterwards to confirm that only the
intended rows were removed. Tables that cannot be tied to the account are
reported and left completely untouched.
"""


def configure(parser) -> None:
    parser.add_argument(
        "--account-rid",
        required=True,
        help="The rid of the account to purge, from trd365.account.",
    )


def entity_rid(namespace) -> str:
    return namespace.account_rid


def resolve(ctx: cli.ResolverContext) -> cli.PurgePlan:
    """Resolve the account, capture its id-sets, and assemble the plan."""
    rid = ctx.namespace.account_rid
    notes: list[str] = []

    account = scoping.resolve_account(ctx.pool, rid)

    if not account.exists:
        # The account row is deleted during the main step, before the ai step
        # runs. A run that died after that point cannot resolve itself again,
        # so the checkpoint is what is left to go on.
        saved = ctx.saved
        if saved is not None and saved.resolved.get("org_schema") and saved.id_sets:
            account = scoping.ResolvedAccount(
                rid=rid,
                exists=True,
                r_number=saved.resolved.get("r_number"),
                storage_type=saved.resolved.get("storage_type"),
                org_schema=saved.resolved["org_schema"],
            )
            ctx.log("  the account row is already deleted; resuming the remaining steps")
            notes.append("resumed after the account row had been deleted")
        else:
            raise cli.TargetNotFound(
                f"{rid} is not in {M.MAIN_SCHEMA}.account, and no checkpoint exists to "
                f"resume from. Either it is already purged, or the rid is wrong."
            )

    ctx.log(f"  org schema  : {account.org_schema}")
    if account.storage_type == "store_in_parent":
        ctx.log(
            "  storage     : store_in_parent — its rows live in the parent's schema, "
            "selected by account_rid only"
        )

    # The id-sets were read before anything was deleted, so a saved set is
    # authoritative: re-reading now would come back short, or empty.
    if ctx.saved is not None and ctx.saved.id_sets:
        id_sets = ctx.saved.id_sets
        ctx.log("  id sets     : reused from the checkpoint")
    else:
        id_sets = scoping.capture_id_sets(ctx.pool, ctx.cache, account)
        ctx.log(
            "  id sets     : "
            + ", ".join(f"{name}={len(values)}" for name, values in sorted(id_sets.items()))
        )

    if ctx.model is not None:
        drift = M.reconcile(ctx.model, account.org_schema)
        if drift["missing_from_manifest"]:
            message = (
                f"{len(drift['missing_from_manifest'])} account-scoped table(s) in the data "
                f"model are not in the manifest: {', '.join(drift['missing_from_manifest'])}"
            )
            ctx.log(f"  model drift : {message}")
            notes.append(message)
        if drift["absent_from_model"]:
            ctx.log(
                f"  model drift : {len(drift['absent_from_model'])} manifest table(s) are not "
                f"in {account.org_schema}; they will be skipped as not present"
            )

    scoper = scoping.AccountScoper(
        account=account,
        sets=id_sets,
        cache=ctx.cache,
        db_for=scoping.DB_FOR_KIND,
        model=ctx.model,
    )

    return cli.PurgePlan(
        entity_rid=rid,
        steps=M.STEPS,
        schema_for={"org": account.org_schema, **scoping.FIXED_SCHEMAS},
        scoper=scoper,
        resolved=account.to_dict(),
        id_sets=id_sets,
        notes=notes,
    )


def main(argv: list[str] | None = None) -> None:
    cli.main(
        entity="account",
        description=DESCRIPTION,
        resolver=resolve,
        entity_rid=entity_rid,
        configure=configure,
        argv=argv,
    )


if __name__ == "__main__":
    main()
