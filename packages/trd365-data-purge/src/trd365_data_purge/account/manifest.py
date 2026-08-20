"""
The account deletion manifest — the FK-safe table order, per database.

Extracted by the original author from the vendor SECTION files (ORGDB SECTION2,
MAINDB SECTION3, TRD365AI SECTION7), preserving the exact child-before-parent
order those files rely on. The lists are reproduced here **unchanged**: they are
data, and the one thing worse than a stale ordering is a re-derived one that
looks right and is not.

The static order is a fast path, not the guarantee. The engine defers and
retries anything still foreign-key blocked, so a schema newer than this file
still completes — it just takes more passes.

Execution order across databases: ORG -> MAIN -> AI.

======  ==========  ==========================  =================================
step    db_key      schema                      keyed by
======  ==========  ==========================  =================================
org     orgdb       the account's org schema    account_rid, or a parent's rid
main    maindb      ``trd365``                  account_rid
ai      trd365ai    ``public``                  the captured project-fiscal set
======  ==========  ==========================  =================================
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from trd365_core.datamodel import DEFAULT_MAIN_SCHEMA, TENANT_SCHEMA_LIKE

if TYPE_CHECKING:  # pragma: no cover - typing only
    from trd365_core.model_snapshot import ModelSnapshot

# ---------------------------------------------------------------------------
# ORG DB — the account's own per-account schema
# ---------------------------------------------------------------------------

ORG_TABLES: list[str] = [
    "case_timeline_old", "rd_credit_processing_status", "rd_credit_state_calculations",
    "rd_credit_country_calculations", "case_project_task", "case_project_resource_fiscal",
    "case_project_resource", "case_project_fiscal_region", "case_projects",
    "case_projects_by_region", "case_task_dependency_mapping", "case_task", "case_team",
    "case_milestone", "case_key_contact_details", "case_technical_summary", "signoff_details",
    "dossier_form", "checklist_items", "checklists", "comments_attachments", "case_history",
    "case_timeline", "cases", "interaction_items", "interaction_history", "otp_entries_history",
    "otp_entries", "interactions", "four_part_assessment", "project_task_timeline", "project_task",
    "project_resource_fiscal_region", "project_resource_fiscal", "project_resource",
    "ai_technical_summary", "ai_assessment_audit", "ai_assessment_error", "ai_assessment_qre",
    "autosend_interaction_audit", "project_qre_adjustment_history", "project_fiscal_region",
    "project_history", "project_timeline", "project_timeline_old", "account_timeline",
    "project_fiscal_history", "project_fiscal", "key_contact_details", "project", "resource_skill",
    "resource_cost", "resource_fiscal_region", "resource_fiscal", "resources_history",
    "resources_timeline", "resources", "chat_answers", "chat_attachments", "chat_audit_log",
    "chat_branches", "chat_messages", "chat_questions", "chat_sessions", "kafka_events", "import",
    "document", "attachment_timeline", "attachments", "notes_timeline", "notes",
    "activity_history",
    "activity_attachments", "meeting_summary", "activities", "account_interactions",
    "clientfirm_document_template_metadata", "clientfirm_document_template",
    "account_fiscal_region",
    "account_fiscal", "account_timeline_old", "interaction_attachments",
    "interaction_response_history", "interaction_status_history", "interaction_timeline",
    "case_history_submission", "history_staging_project", "history_staging_resource",
    "history_staging_interaction", "history_staging_case", "history_staging_account",
    "history_staging_document", "account_details",
]

# ---------------------------------------------------------------------------
# MAIN DB — the shared schema; every table here is keyed by account_rid
# ---------------------------------------------------------------------------

MAIN_SCHEMA = DEFAULT_MAIN_SCHEMA

MAIN_TABLES: list[str] = [
    "rd_credit_calculations_summary", "case_summary", "send_email_info", "ai_trigger_records",
    "interactions_summary", "rule_engine_records", "rule_engine_notification_records",
    "control_center_execution", "user_group_entity_access", "project_fiscal_summary",
    "chat_assistance_session", "attachment_summary", "notes_summary", "meeting_summary",
    "task_summary", "project_summary", "customisation_checks", "subscription_renewal_records",
    "user_group_account_mapping", "account_fiscal_summary", "account_allowed_domains", "account",
]

# ---------------------------------------------------------------------------
# TRD365AI — no link back to the org schema; keyed by the project-fiscal set
# ---------------------------------------------------------------------------

AI_SCHEMA = "public"

AI_TABLES: list[str] = [
    "master_project_ai_summary_logs", "master_project_ai_summary_sections",
    "master_project_ai_summary", "master_project_ai_interaction", "master_project_ai_assessment",
    "master_ai_request", "master_ai_llm_logs", "master_ai_knowledge_base", "master_project_details",
    "four_part_assessments",
]

#: The column spellings trd365ai uses for a project fiscal, in preference order.
#: The database is not consistent about the casing, so all three are tried.
AI_FISCAL_COLUMNS: tuple[str, ...] = ("projectId", "projectid", "project_fiscal_rid")

#: ``(step_key, db_key, schema_kind, tables)`` in execution order.
STEPS: list[tuple[str, str, str, list[str]]] = [
    ("org_delete", "orgdb", "org", ORG_TABLES),
    ("main_delete", "maindb", "main", MAIN_TABLES),
    ("ai_delete", "trd365ai", "ai", AI_TABLES),
]


# ---------------------------------------------------------------------------
# org schema naming
# ---------------------------------------------------------------------------

#: Derived from the one place the tenant-schema shape is defined, so the purge
#: and the data-model analysis cannot drift apart on what an org schema is
#: called. ``TENANT_SCHEMA_LIKE`` is an SQL LIKE pattern (``trd365\_%``).
TENANT_SCHEMA_PREFIX = TENANT_SCHEMA_LIKE.replace("\\", "").removesuffix("%")

#: Account reference numbers are stored with this prefix; the schema name drops it.
R_NUMBER_PREFIX = "ACC-"


def org_schema_for(r_number: str | None) -> str:
    """The org schema belonging to an account reference number."""
    return TENANT_SCHEMA_PREFIX + (r_number or "").replace(R_NUMBER_PREFIX, "")


# ---------------------------------------------------------------------------
# reconciliation against the shared data model
# ---------------------------------------------------------------------------


def reconcile(model: ModelSnapshot, org_schema: str) -> dict[str, list[str]]:
    """
    Compare the static org manifest with the current data-model snapshot.

    This is how a re-run of the data-model analysis reaches the purge (PRD
    FR-1.9/1.10): tables the model knows reference an account but this file has
    never heard of are returned in ``missing_from_manifest``, and the scoper
    adds them to the worklist rather than silently leaving their rows behind.

    Only the org step is covered — the snapshot captures tenant schemas, and
    the main and ai steps are reconciled against the live catalog instead.

    A snapshot that does not contain ``org_schema`` yields empty lists: an
    account whose schema was created after the last analysis is a reason to
    re-run the analysis, not a reason to refuse, and live discovery still runs.
    """
    known = set(ORG_TABLES)
    try:
        present = set(model.schema(org_schema).table_names)
        referencing = set(model.tables_referencing(org_schema, "account"))
    except Exception:  # noqa: BLE001 — schema absent from this snapshot
        return {"missing_from_manifest": [], "absent_from_model": []}

    return {
        "missing_from_manifest": sorted(referencing - known),
        "absent_from_model": sorted(known - present),
    }
