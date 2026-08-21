"""
Registration of the purge utilities with the shared catalogue.

Importing this module registers them; the Phase-2 API and the Phase-3 UI are
generated from the result, so nothing about invoking a purge is hand-written in
the frontend (PRD FR-4.4).
"""

from __future__ import annotations

from trd365_core.registry import Impact, Parameter, ParameterType, Registry, Utility
from trd365_core.registry import registry as default_registry

from .cli import DEFAULT_CHUNK_SIZE, DEFAULT_MODEL_MAX_AGE_DAYS

COMMON_PARAMETERS: tuple[Parameter, ...] = (
    Parameter(
        name="chunk_size",
        type=ParameterType.INTEGER,
        help="Rows per backup+delete batch. Smaller batches hold locks for less time.",
        default=DEFAULT_CHUNK_SIZE,
    ),
    Parameter(
        name="out_dir",
        type=ParameterType.PATH,
        help="Where to write the run report.",
        default="reports",
    ),
    Parameter(
        name="restart",
        type=ParameterType.BOOLEAN,
        help="Discard any saved checkpoint and start this target from the beginning.",
        default=False,
    ),
    Parameter(
        name="model_max_age_days",
        type=ParameterType.INTEGER,
        help="How old the data-model snapshot may be. 0 accepts any age.",
        default=DEFAULT_MODEL_MAX_AGE_DAYS,
    ),
    Parameter(
        name="ignore_model",
        type=ParameterType.BOOLEAN,
        help="Run without the data-model snapshot. Newly added tables go undiscovered.",
        default=False,
    ),
)

PURGE_ACCOUNT = Utility(
    id="purge-account",
    title="Purge account",
    description=(
        "Delete every record belonging to one account, across the org schema, the "
        "shared main schema and trd365ai. Rows are copied into the data_purge schema "
        "of each database before deletion, and the run is audited afterwards to "
        "confirm nothing else was removed."
    ),
    module="trd365_data_purge.account",
    impact=Impact.DESTRUCTIVE,
    databases=("maindb", "orgdb", "trd365ai"),
    parameters=(
        Parameter(
            name="account_rid",
            type=ParameterType.STRING,
            help="The rid of the account to purge, from trd365.account.",
            required=True,
        ),
        *COMMON_PARAMETERS,
    ),
    supersedes="account_deletion",
    notes=(
        "Dry run by default; --apply writes. Backups live in data_purge.bak_<table> "
        "tagged with the run id, and are not removed by this utility — retention is a "
        "separate, deliberate decision."
    ),
)


PURGE_CASE = Utility(
    id="purge-case",
    title="Purge case",
    description=(
        "Delete one case — a credit study — and its whole subtree: its rows in the "
        "account's org schema, then the case-owned rows in the shared main schema. "
        "A pure subtree delete: no aggregate outside the case depends on it, so "
        "nothing is recalculated afterwards."
    ),
    module="trd365_data_purge.case",
    impact=Impact.DESTRUCTIVE,
    databases=("maindb", "orgdb"),
    parameters=(
        Parameter(
            name="account_id",
            type=ParameterType.STRING,
            help=(
                "The account the case belongs to, as its reference number (ACC-00459) "
                "or its rid. The case's rows live in that account's org schema."
            ),
            required=True,
        ),
        Parameter(
            name="case_rid",
            type=ParameterType.STRING,
            help="The rid of the case to purge, from the org schema's cases table.",
            required=True,
        ),
        *COMMON_PARAMETERS,
    ),
    notes=(
        "Dry run by default; --apply writes. Three manifest tables carry no case link "
        "at all and are always reported unscoped and left untouched: case_timeline_old, "
        "case_projects_by_region, case_history_submission."
    ),
)


PURGE_INTERACTION = Utility(
    id="purge-interaction",
    title="Purge interaction",
    description=(
        "Delete one interaction and the subtree it owns: its rows in the account's "
        "org schema, then the interaction-owned rows in the shared main schema. A "
        "pure subtree delete, with no recompute."
    ),
    module="trd365_data_purge.interaction",
    impact=Impact.DESTRUCTIVE,
    databases=("maindb", "orgdb"),
    parameters=(
        Parameter(
            name="account_id",
            type=ParameterType.STRING,
            help=(
                "The account the interaction belongs to, as its reference number "
                "(ACC-00459) or its rid."
            ),
            required=True,
        ),
        Parameter(
            name="interaction_rid",
            type=ParameterType.STRING,
            help="The rid of the interaction to purge, from the org schema's interactions table.",
            required=True,
        ),
        *COMMON_PARAMETERS,
    ),
    notes=(
        "Dry run by default; --apply writes. chat_sessions is never touched: it "
        "carries an interaction_rid without being owned by the interaction, and a "
        "conversation outlives the interaction it was started from."
    ),
)


def register(registry: Registry | None = None) -> Registry:
    """Add the purge utilities to a registry (the shared one by default)."""
    target = default_registry if registry is None else registry
    target.register(PURGE_ACCOUNT)
    target.register(PURGE_CASE)
    target.register(PURGE_INTERACTION)
    return target


register()
