"""Registration of the analysis utility with the shared catalogue."""

from __future__ import annotations

from trd365_core.datamodel import DEFAULT_MAIN_SCHEMA
from trd365_core.registry import Impact, Parameter, ParameterType, Registry, Utility
from trd365_core.registry import registry as default_registry

from .orphans import DEFAULT_SAMPLE

DATA_MODEL_ANALYSIS = Utility(
    id="data-model-analysis",
    title="Data-model analysis",
    description=(
        "Introspect every tenant schema into the shared data-model snapshot, find rows "
        "whose parent no longer exists, and classify foreign-key naming deviations. "
        "This is the only producer of the snapshot the other utilities read, so it has "
        "to run against an environment before anything there can write."
    ),
    module="trd365_analysis",
    # Read-only against the databases. --apply publishes the snapshot, which is
    # a write to the shared model rather than to any database, and is why this
    # is not READ_ONLY: replacing the model every other utility trusts is a
    # consequential act and deserves the same gate.
    impact=Impact.WRITES,
    databases=("maindb", "orgdb"),
    parameters=(
        Parameter(
            name="schemas",
            type=ParameterType.STRING,
            help="Tenant schemas to analyse. Leave empty for every trd365_* schema.",
        ),
        Parameter(
            name="main_schema",
            type=ParameterType.STRING,
            help="The shared schema holding the account table.",
            default=DEFAULT_MAIN_SCHEMA,
        ),
        Parameter(
            name="no_orphans",
            type=ParameterType.BOOLEAN,
            help="Skip the orphan scan. Structure and deviations only, and much cheaper.",
            default=False,
        ),
        Parameter(
            name="all_entities",
            type=ParameterType.BOOLEAN,
            help="Scan every resolved reference, not only the four primary entities.",
            default=False,
        ),
        Parameter(
            name="sample",
            type=ParameterType.INTEGER,
            help="Example rids to record per orphaned edge.",
            default=DEFAULT_SAMPLE,
        ),
        Parameter(
            name="out_dir",
            type=ParameterType.PATH,
            help="Directory for the reports.",
            default="reports",
        ),
    ),
    supersedes="data_model_analysis",
    notes=(
        "Read-only against the databases; --apply publishes the snapshot. Its orphan "
        "and deviation counts are the health metrics the dashboard reads (FR-4.5)."
    ),
)


def register(registry: Registry | None = None) -> Registry:
    target = default_registry if registry is None else registry
    target.register(DATA_MODEL_ANALYSIS)
    return target


register()
