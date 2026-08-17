"""
Interaction scoping — delete one interaction and its subtree. Pure subtree delete
(no recompute — no surviving aggregate depends on a single interaction; its own
summary rows are deleted).

Owned children only. IMPORTANT: `chat_sessions` has an `interaction_rid` column
but NO FK and is NOT owned by the interaction (it's a soft reference) — so it is
deliberately EXCLUDED from the manifest and never deleted here.

Ordering follows the vendor SECTION-2 interaction block (children first,
`interactions` last). interaction_timeline is scoped via `entity_rid`;
interaction_response_history via its own interaction_rid AND the item path.
"""

from engine.core import _q, table_exists, columns

MAIN_SCHEMA = "trd365"

ORG_TABLES = [
    "interaction_attachments", "interaction_response_history", "interaction_items",
    "interaction_timeline", "interaction_history", "interaction_status_history",
    "interaction_send_history", "otp_entries_history", "otp_entries", "interactions",
]
# MAIN — interaction-owned rows (keyed by interaction_rid).
MAIN_TABLES = ["send_email_info", "interaction_age_records", "interactions_summary"]

STEPS = [
    ("interaction_org",  "orgdb",  "org",  ORG_TABLES),
    ("interaction_main", "maindb", "main", MAIN_TABLES),
]
SCHEMA_FOR = {"main": MAIN_SCHEMA}


class InteractionScoper:
    def __init__(self, interaction_rid):
        self.rid = interaction_rid

    def discover(self, conn, schema, kind, manifest_tables):
        return []

    def predicate(self, conn, schema, table, kind):
        rid = self.rid
        cols = columns(conn, schema, table)
        if table == "interactions":
            return "rid = %s", [rid]
        if table == "interaction_timeline":
            # timeline rows point at the interaction via entity_rid
            return "entity_rid = %s", [rid]
        if table == "interaction_response_history":
            # reachable directly (interaction_rid) OR via interaction_items
            sql = "interaction_rid = %s"
            params = [rid]
            if table_exists(conn, schema, "interaction_items"):
                sql += (f' OR interaction_item_rid IN (SELECT rid FROM '
                        f'{_q(schema)}.interaction_items WHERE interaction_rid = %s)')
                params.append(rid)
            return sql, params
        if "interaction_rid" in cols:
            return "interaction_rid = %s", [rid]
        return None
