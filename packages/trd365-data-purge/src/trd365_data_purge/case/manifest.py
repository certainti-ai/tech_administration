"""
The case deletion manifest — the FK-safe table order, per database.

Reproduced unchanged from ``legacy/trd365_maintenance/data_purge/case/
scoping_case.py``, which took it from the vendor's account-deletion manifest (the
case portion of ORGDB SECTION2 and MAINDB SECTION3). The order is data, and a
re-derived one that looks right and is not would delete parents before children.

``DELETION_ORDER.md`` beside this file is the vendor-facing description of the
same thing and is the better document to read first.

A case purge is a **pure subtree delete: there is no recompute.** That was
verified when the legacy tool was written — no account-level or project-level
aggregate carries a case count, and the summary rows that mention a case
(``case_summary``, ``rd_credit_calculations_summary``) are the case's own rows and
are deleted with it. So unlike a project purge, nothing has to be recalculated
afterwards for the financial totals to stay correct.

Execution order across databases: ORG -> MAIN.

======  ==========  ==========================  =================================
step    db_key      schema                      keyed by
======  ==========  ==========================  =================================
org     orgdb       the account's org schema    case_rid, or a parent's rid
main    maindb      ``trd365``                  case_rid
======  ==========  ==========================  =================================
"""

from __future__ import annotations

from trd365_core.datamodel import DEFAULT_MAIN_SCHEMA

MAIN_SCHEMA = DEFAULT_MAIN_SCHEMA

# ---------------------------------------------------------------------------
# ORG DB — children first, ``cases`` (the anchor) last
# ---------------------------------------------------------------------------

ORG_TABLES: list[str] = [
    "case_timeline_old", "rd_credit_processing_status", "rd_credit_state_calculations",
    "rd_credit_country_calculations", "case_project_task", "case_project_resource_fiscal",
    "case_project_resource", "case_project_fiscal_region", "case_projects",
    "case_projects_by_region", "case_task_dependency_mapping", "case_task", "case_team",
    "case_milestone", "case_key_contact_details", "case_technical_summary", "signoff_details",
    "dossier_form", "checklist_items", "checklists", "comments_attachments", "case_history",
    "case_history_submission", "case_timeline", "cases",
]

# ---------------------------------------------------------------------------
# MAIN DB — the shared schema; case-owned rows, keyed by case_rid
# ---------------------------------------------------------------------------

MAIN_TABLES: list[str] = [
    "rd_credit_calculations_summary", "chat_assistance_session", "case_summary",
]

#: ``(step_key, db_key, schema_kind, tables)`` in execution order.
STEPS: list[tuple[str, str, str, list[str]]] = [
    ("org_delete", "orgdb", "org", ORG_TABLES),
    ("main_delete", "maindb", "main", MAIN_TABLES),
]

#: Three of the manifest tables carry no case link at all —
#: ``case_timeline_old`` and ``case_projects_by_region`` have no ``_rid`` columns,
#: and ``case_history_submission`` is scoped by account and geography rather than
#: by case. They are listed above deliberately: the engine reports them as
#: unscoped and leaves them untouched, which is a visible "a human should look at
#: this" rather than a silent omission from the manifest.
KNOWN_UNSCOPED: frozenset[str] = frozenset(
    {"case_timeline_old", "case_projects_by_region", "case_history_submission"}
)
