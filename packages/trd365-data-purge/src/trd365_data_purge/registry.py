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


#: Shared by the two SECTION-driven purges. They take neither a chunk size nor a
#: checkpoint nor the data-model snapshot: none of those mean anything to SQL the
#: vendor wrote, which manages its own batching and its own backup schema.
SECTION_PARAMETERS: tuple[Parameter, ...] = (
    Parameter(
        name="sections",
        type=ParameterType.STRING,
        help="Run only these sections, e.g. \"4 5 8\" to re-run the audit after a failure.",
    ),
    Parameter(
        name="backup_schema",
        type=ParameterType.STRING,
        help="The schema every section backs up into. Override to resume into an earlier run's.",
        default="data_purge",
    ),
    Parameter(
        name="heartbeat_seconds",
        type=ParameterType.INTEGER,
        help="How often to report that a section is still running. Each one is a silent DO block.",
        default=15,
    ),
    Parameter(
        name="out_dir",
        type=ParameterType.PATH,
        help="Where to write the run report.",
        default="reports",
    ),
)

_NOT_FREE = (
    "A DRY RUN OF THIS UTILITY IS NOT FREE. It runs the vendor's delete-and-recompute "
    "SQL inside a transaction it then rolls back — same locks, same work, result "
    "discarded — because SQL that recomputes financial aggregates cannot be previewed "
    "any other way. In production a preview needs an approver for that reason."
)

PURGE_PROJECT_FISCAL = Utility(
    id="purge-project-fiscal",
    title="Purge project fiscal year",
    description=(
        "Delete one fiscal year of one project across all three databases, and "
        "recompute the financial aggregates that survive it — account fiscal totals, "
        "project rollups, QRE dollars. Runs the vendor's SECTION 1-8 SQL rather than "
        "enumerating rows, because the recompute must not be re-derived."
    ),
    module="trd365_data_purge.project_fiscal",
    impact=Impact.DESTRUCTIVE,
    databases=("maindb", "orgdb", "trd365ai"),
    dry_run_executes=True,
    parameters=(
        Parameter(
            name="account_id",
            type=ParameterType.STRING,
            help="The account, as its reference number (ACC-00459) or its rid.",
            required=True,
        ),
        Parameter(
            name="project_fiscal_rid",
            type=ParameterType.STRING,
            help="The rid of the project fiscal to delete.",
            required=True,
        ),
        Parameter(
            name="last_fiscal",
            type=ParameterType.BOOLEAN,
            help=(
                "Force is_last_fiscal. Leave unset to count the project's fiscals. "
                "Set when a previous failed run already removed a sibling and left the "
                "count misleading."
            ),
        ),
        *SECTION_PARAMETERS,
    ),
    notes=(
        "is_last_fiscal is TRUE only when this is the project's only remaining fiscal, "
        "in which case the project row goes too and the account totals are recomputed. "
        + _NOT_FREE
    ),
)

PURGE_PROJECT = Utility(
    id="purge-project",
    title="Purge project",
    description=(
        "Delete a whole project — every fiscal year, oldest first — with the final "
        "fiscal's run also removing the project row and recomputing the account "
        "totals. This is the project-fiscal purge repeated, which is what keeps "
        "deleting a project identical to deleting its years one at a time."
    ),
    module="trd365_data_purge.project",
    impact=Impact.DESTRUCTIVE,
    databases=("maindb", "orgdb", "trd365ai"),
    dry_run_executes=True,
    parameters=(
        Parameter(
            name="account_id",
            type=ParameterType.STRING,
            help="The account, as its reference number (ACC-00459) or its rid.",
            required=True,
        ),
        Parameter(
            name="project",
            type=ParameterType.STRING,
            help="The project, as its rid or its project code.",
            required=True,
        ),
        *SECTION_PARAMETERS,
    ),
    notes=(
        "Stops at the first failing fiscal by default: a failed fiscal means the "
        "recompute chain is already inconsistent, and pressing on compounds it. "
        + _NOT_FREE
    ),
    supersedes="project_fiscal_year_deletion",
)


def register(registry: Registry | None = None) -> Registry:
    """Add the purge utilities to a registry (the shared one by default)."""
    target = default_registry if registry is None else registry
    target.register(PURGE_ACCOUNT)
    target.register(PURGE_CASE)
    target.register(PURGE_INTERACTION)
    target.register(PURGE_PROJECT_FISCAL)
    target.register(PURGE_PROJECT)
    return target


register()
