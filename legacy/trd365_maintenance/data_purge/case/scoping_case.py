"""
Case scoping — delete one case (a credit study) and its subtree. Pure subtree
delete: no account-level aggregate depends on a case (verified: no case-count
columns on account/account_fiscal; case_summary etc. are the case's OWN rows and
are deleted). So there is NO recompute — just children-first backup + delete.

STEPS: ORG case_* / rd_credit_* / checklists / signoff / dossier (children first,
`cases` last) → MAIN case-owned summaries. The engine's multi-pass FK deferral
handles any ordering the static list misses.
"""

from engine.core import _q, table_exists, columns, single_col_fks

MAIN_SCHEMA = "trd365"

# ORG — children first, `cases` (anchor) last. Vendor-derived order (account
# deletion manifest, case portion).
ORG_TABLES = [
    "case_timeline_old", "rd_credit_processing_status", "rd_credit_state_calculations",
    "rd_credit_country_calculations", "case_project_task", "case_project_resource_fiscal",
    "case_project_resource", "case_project_fiscal_region", "case_projects",
    "case_projects_by_region", "case_task_dependency_mapping", "case_task", "case_team",
    "case_milestone", "case_key_contact_details", "case_technical_summary", "signoff_details",
    "dossier_form", "checklist_items", "checklists", "comments_attachments", "case_history",
    "case_history_submission", "case_timeline", "cases",
]
# MAIN — case-owned rows (keyed by case_rid).
MAIN_TABLES = ["rd_credit_calculations_summary", "chat_assistance_session", "case_summary"]

STEPS = [
    ("case_org",  "orgdb",  "org",  ORG_TABLES),
    ("case_main", "maindb", "main", MAIN_TABLES),
]
SCHEMA_FOR = {"main": MAIN_SCHEMA}  # 'org' filled per-account


class CaseScoper:
    def __init__(self, case_rid):
        self.rid = case_rid

    def discover(self, conn, schema, kind, manifest_tables):
        # be conservative: no auto-discovery of extra case-scoped tables
        return []

    def predicate(self, conn, schema, table, kind):
        rid = self.rid
        cols = columns(conn, schema, table)
        if table == "cases":
            return "rid = %s", [rid]
        if "case_rid" in cols:
            return "case_rid = %s", [rid]
        # checklist_items: no case_rid — scope via checklists
        if table == "checklist_items" and table_exists(conn, schema, "checklists"):
            return (f'checklist_rid IN (SELECT rid FROM {_q(schema)}.checklists WHERE case_rid = %s)', [rid])
        # generic: FK to a case_rid-bearing parent
        conds, params = [], []
        for local_col, ref_table, ref_col in single_col_fks(conn, schema, table):
            if not local_col or ref_table == table:
                continue
            if "case_rid" in columns(conn, schema, ref_table):
                conds.append(f'{_q(local_col)} IN (SELECT {_q(ref_col)} FROM '
                             f'{_q(schema)}.{_q(ref_table)} WHERE case_rid = %s)')
                params.append(rid)
        if conds:
            return " OR ".join(conds), params
        return None
