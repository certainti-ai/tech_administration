"""
The interaction deletion manifest — the FK-safe table order, per database.

Reproduced unchanged from ``legacy/trd365_maintenance/data_purge/interaction/
scoping_interaction.py``, which follows the vendor's SECTION-2 interaction block.
``DELETION_ORDER.md`` beside this file is the same thing in prose.

An interaction purge is a **pure subtree delete: there is no recompute.** Nothing
that survives the interaction aggregates it, and the summary rows that mention it
(``interactions_summary``, ``interaction_age_records``) are its own.

Execution order across databases: ORG -> MAIN.
"""

from __future__ import annotations

from trd365_core.datamodel import DEFAULT_MAIN_SCHEMA

MAIN_SCHEMA = DEFAULT_MAIN_SCHEMA

# ---------------------------------------------------------------------------
# ORG DB — children first, ``interactions`` (the anchor) last
# ---------------------------------------------------------------------------

ORG_TABLES: list[str] = [
    "interaction_attachments", "interaction_response_history", "interaction_items",
    "interaction_timeline", "interaction_history", "interaction_status_history",
    "interaction_send_history", "otp_entries_history", "otp_entries", "interactions",
]

# ---------------------------------------------------------------------------
# MAIN DB — interaction-owned rows in the shared schema
# ---------------------------------------------------------------------------

MAIN_TABLES: list[str] = [
    "send_email_info", "interaction_age_records", "interactions_summary",
]

#: ``(step_key, db_key, schema_kind, tables)`` in execution order.
STEPS: list[tuple[str, str, str, list[str]]] = [
    ("org_delete", "orgdb", "org", ORG_TABLES),
    ("main_delete", "maindb", "main", MAIN_TABLES),
]

#: ``chat_sessions`` carries an ``interaction_rid`` and is **not** owned by the
#: interaction — no foreign key, a soft reference from a conversation that
#: outlives the interaction it was started from. It is excluded from the manifest
#: deliberately, and named here so that the exclusion is a decision on the record
#: rather than an omission somebody later "fixes".
#:
#: This is why the interaction scoper does not discover tables by looking for an
#: ``interaction_rid`` column: that search finds exactly this table.
NOT_OWNED: frozenset[str] = frozenset({"chat_sessions"})
