"""
The R&D percentage arithmetic, as the application actually does it.

This is the money. Every number written by this utility comes from here, and the
whole point of the utility is to leave the database in a state the application
itself could have produced — so this file reproduces
``entity-module/src/services/schemaService.ts`` rather than deriving anything
afresh.

The source of truth, with line references into
``certainti-ai/rdcredits_platform_be`` at 6e16f32:

* ``schemaService.ts:4240`` — ``existingPercent = rd_percent_potential_ai ?? 0``
* ``schemaService.ts:4244`` — the guard: a valid number ``>= 0``
* ``schemaService.ts:4245`` — ``netQre = qreAdjustment + existingPercent``
* ``schemaService.ts:4266-4268`` — the three cost components
* ``schemaService.ts:4269`` — ``qreFinalCost = fte + subcon + nonlabor``
* ``schemaService.ts:4271`` — ``isQualified = netQre > 0``

## Two places the legacy JS tool disagrees with the application

Both were found by reading the application source next to the tool, and both
overstate money. They are the reason this port does not simply transcribe the
JavaScript.

**1. The sub-contractor cap is missing.** The application caps sub-contractor QRE
at the jurisdiction's configured percentage (TRDV2-451)::

    qreSubconCost = totalSubconCost * (netQre / 100) * (subConPercent / 100)

``legacy/trd365_maintenance/manual-rd-percent-update/index.js:553`` computes::

    qreSubconCost = totalSubconCost * (netQre / 100)

With the default cap of 65% that writes roughly 1.54x the sub-contractor QRE the
application would write. The cap is resolved per project from its country's
Federal R&D Credit configuration — see :mod:`trd365_rd_percent.subcon`.

**2. ``qre_final`` is derived from a different column.** The application sums the
three components it just computed. The legacy tool uses a fourth column::

    qreFinalCost = totalCost * (netQre / 100)     # index.js:551, total_cost_prj

Those agree only when ``total_cost_prj`` happens to equal the sum of the three
component costs *and* the sub-con cap is 100%. Neither is guaranteed.

## Floats, deliberately

The application is TypeScript and does this arithmetic in IEEE-754 doubles.
Python floats are the same doubles, so plain float arithmetic reproduces the
application's results bit for bit. Decimal would be more defensible in the
abstract and would produce values the application never writes, which is the one
thing this utility must not do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trd365_core.errors import Trd365Error

#: Applied when no jurisdiction configuration can be resolved.
#: ``entity-module/src/utils/constants.ts:41`` (``FALLBACK_SUB_CON_PERCENT``).
FALLBACK_SUB_CON_PERCENT = 65.0


class InconsistentInput(Trd365Error):
    """The percentages given cannot describe a state the application produces."""


@dataclass(frozen=True)
class Costs:
    """The cost totals a project fiscal carries, before any percentage applies."""

    fte: float = 0.0
    subcon: float = 0.0
    nonlabor: float = 0.0

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Costs:
        """
        Read the totals off a ``project_fiscal`` row.

        ``?? 0`` in the application, so NULL is zero rather than an error
        (``schemaService.ts:4247-4249``).
        """
        return cls(
            fte=_number(row.get("total_cost_fte_prj")),
            subcon=_number(row.get("total_cost_subcon_prj")),
            nonlabor=_number(row.get("total_cost_nonlabor_prj")),
        )


@dataclass(frozen=True)
class Qre:
    """Everything the write path needs, and nothing it has to work out itself."""

    #: The stored ``rd_percent_potential_ai`` this was computed against.
    potential_ai: float
    #: The delta the operator is applying.
    adjustment: float
    #: ``potential_ai + adjustment``. Written to every ``rd_percent_final``.
    net_percent: float
    #: The cap that was applied to sub-contractor cost, as a percentage.
    sub_con_percent: float
    fte: float
    subcon: float
    nonlabor: float
    final: float
    is_qualified: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "rd_percent_potential_ai": self.potential_ai,
            "rd_percent_adjustment": self.adjustment,
            "rd_percent_final": self.net_percent,
            "sub_con_percent": self.sub_con_percent,
            "qre_fte": self.fte,
            "qre_subcon": self.subcon,
            "qre_nonlabor": self.nonlabor,
            "qre_final": self.final,
            "is_qualified": self.is_qualified,
        }


def _number(value: Any) -> float:
    """``parseFloat`` with the application's ``?? 0``."""
    if value is None or value == "":
        return 0.0
    return float(value)


def compute(
    *,
    potential_ai: float,
    adjustment: float,
    costs: Costs,
    sub_con_percent: float = FALLBACK_SUB_CON_PERCENT,
) -> Qre:
    """
    The application's calculation, given the percentage it should be based on.

    ``potential_ai`` is what ``rd_percent_potential_ai`` will hold. In the live
    application it is the value *already stored* on the project fiscal; this
    utility also writes it, because its purpose is to apply a correction to both
    at once — which the application has no single endpoint for. That difference is
    the reason this utility exists and is the only place it does more than the
    application does.
    """
    if potential_ai < 0:
        # schemaService.ts:4244 — the app's guard. It silently does nothing when
        # the check fails; refusing is more useful to somebody running this by
        # hand, who would otherwise see success and no change.
        raise InconsistentInput(
            f"rd_percent_potential_ai must be >= 0, got {potential_ai}. The application "
            f"guards on this and silently does nothing; this refuses instead."
        )

    net = adjustment + potential_ai
    fte = costs.fte * (net / 100)
    subcon = costs.subcon * (net / 100) * (sub_con_percent / 100)
    nonlabor = costs.nonlabor * (net / 100)

    return Qre(
        potential_ai=potential_ai,
        adjustment=adjustment,
        net_percent=net,
        sub_con_percent=sub_con_percent,
        fte=fte,
        subcon=subcon,
        nonlabor=nonlabor,
        # The sum of the parts, not a fourth cost column. See the module docstring.
        final=fte + subcon + nonlabor,
        is_qualified=net > 0,
    )


#: How far the supplied final percentage may sit from the derived one. A hundredth
#: of a percentage point: enough to absorb a value rounded for display, not enough
#: to absorb a typo.
CONSISTENCY_TOLERANCE = 0.01


def check_consistent(potential_ai: float, adjustment: float, final: float) -> None:
    """
    Refuse a set of three percentages the application could never have produced.

    The application derives the final percentage rather than accepting one, so a
    caller supplying all three can supply a combination that does not hold. Left
    unchecked, that writes a project whose final percentage does not equal its own
    potential plus its own adjustment — a state no code path can create and no
    reader can interpret.
    """
    derived = potential_ai + adjustment
    if abs(derived - final) > CONSISTENCY_TOLERANCE:
        raise InconsistentInput(
            f"rd_percent_final ({final}) is not rd_percent_potential_ai + "
            f"rd_percent_adjustment ({potential_ai} + {adjustment} = {derived}). The "
            f"application always derives it that way (schemaService.ts:4245), so writing "
            f"this would produce a state it could never produce."
        )
