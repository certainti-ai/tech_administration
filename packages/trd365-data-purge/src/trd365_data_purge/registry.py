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


def register(registry: Registry | None = None) -> Registry:
    """Add the purge utilities to a registry (the shared one by default)."""
    target = default_registry if registry is None else registry
    target.register(PURGE_ACCOUNT)
    return target


register()
