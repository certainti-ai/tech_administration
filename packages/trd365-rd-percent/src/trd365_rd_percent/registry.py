"""Registration of the R&D percentage utility with the shared catalogue."""

from __future__ import annotations

from trd365_core.registry import Impact, Parameter, ParameterType, Registry, Utility
from trd365_core.registry import registry as default_registry

RD_PERCENT_UPDATE = Utility(
    id="rd-percent-update",
    title="Correct R&D percentages",
    description=(
        "Correct one project fiscal's R&D percentages and everything the application "
        "would recompute from them: QRE dollars per component, qualification, the case "
        "module's copies, the shared main-database summary, and the audit trail. "
        "Reproduces the write path of the application's own updateQreAdjustment "
        "mutation across both database servers."
    ),
    module="trd365_rd_percent",
    # Not DESTRUCTIVE — it deletes nothing — but it rewrites financial figures,
    # which is why every changed row is snapshotted first.
    impact=Impact.WRITES,
    databases=("maindb", "orgdb"),
    parameters=(
        Parameter(
            name="account_id",
            type=ParameterType.STRING,
            help="Account ID from the product UI, e.g. ACC-00459 (not the internal rid).",
            required=True,
        ),
        Parameter(
            name="project_code",
            type=ParameterType.STRING,
            help="The project's code. Must identify exactly one fiscal under this account.",
            required=True,
        ),
        Parameter(
            name="fiscal_year",
            type=ParameterType.INTEGER,
            help="The fiscal year to correct.",
            required=True,
        ),
        Parameter(
            name="potential_ai",
            type=ParameterType.STRING,
            help="rd_percent_potential_ai to store. Must be >= 0.",
            required=True,
        ),
        Parameter(
            name="adjustment",
            type=ParameterType.STRING,
            help="rd_percent_adjustment — the delta, which may be negative.",
            required=True,
        ),
        Parameter(
            name="final",
            type=ParameterType.STRING,
            help="rd_percent_final. Must equal potential_ai + adjustment.",
            required=True,
        ),
        Parameter(
            name="comments",
            type=ParameterType.STRING,
            help="Free text recorded on the adjustment history row.",
        ),
        Parameter(
            name="out_dir",
            type=ParameterType.PATH,
            help="Where to write the run report.",
            default="reports",
        ),
    ),
    supersedes="manual-rd-percent-update",
    notes=(
        "Dry run by default and a dry run here is genuinely free — it resolves, computes "
        "and reports without opening a write transaction. Sub-contractor QRE is capped at "
        "the project's jurisdiction percentage; the legacy Node tool omitted that cap and "
        "overstated sub-contractor QRE, typically by half again. Overwritten rows are "
        "snapshotted into <schema>.rd_percent_backup in the same transaction as the change."
    ),
)


def register(registry: Registry | None = None) -> Registry:
    target = default_registry if registry is None else registry
    target.register(RD_PERCENT_UPDATE)
    return target


register()
