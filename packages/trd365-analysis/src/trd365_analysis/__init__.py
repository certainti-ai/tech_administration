"""
trd365-analysis — the data model, as discovered from the databases.

``orphans``     rows whose parent no longer exists
``deviations``  why a foreign-key column did not resolve, judged across schemas
``reporting``   the CSVs and the summary
``cli``         the ``data-model-analysis`` utility

This package produces the :class:`~trd365_core.model_snapshot.ModelSnapshot`
that every other utility consumes. Nothing else writes one, so an environment
that has never been analysed here cannot be written to by the destructive
tools — they refuse a missing model rather than assuming one.
"""

from .deviations import GLOBAL_LOOKUP, POLYMORPHIC, TYPO, UNKNOWN, Reclassification
from .orphans import Orphan, SchemaScan, scan, totals
from .reporting import render_text, summary, write_reports

__version__ = "0.1.0"

# Side-effecting: importing this package registers its utility with the shared
# catalogue. Last, so the submodules above are bound first.
from . import registry as registry  # noqa: E402,F401

__all__ = [
    "GLOBAL_LOOKUP",
    "POLYMORPHIC",
    "Orphan",
    "Reclassification",
    "SchemaScan",
    "TYPO",
    "UNKNOWN",
    "__version__",
    "render_text",
    "scan",
    "summary",
    "totals",
    "write_reports",
]
