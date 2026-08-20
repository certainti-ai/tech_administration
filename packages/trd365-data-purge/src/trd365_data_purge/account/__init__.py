"""Account purge: manifest, scoping, and the ``python -m`` entry point."""

from .manifest import AI_SCHEMA, AI_TABLES, MAIN_SCHEMA, MAIN_TABLES, ORG_TABLES, STEPS
from .scoping import AccountScoper, ResolvedAccount, capture_id_sets, resolve_account

__all__ = [
    "AI_SCHEMA",
    "AI_TABLES",
    "MAIN_SCHEMA",
    "MAIN_TABLES",
    "ORG_TABLES",
    "STEPS",
    "AccountScoper",
    "ResolvedAccount",
    "capture_id_sets",
    "resolve_account",
]
