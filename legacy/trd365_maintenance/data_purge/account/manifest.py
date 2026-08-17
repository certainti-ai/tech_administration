"""
Account deletion manifest — the vendor-derived, FK-safe table order.

Extracted from the vendor SECTION files (ORGDB SECTION2 / MAINDB SECTION3 /
TRD365AI SECTION7), preserving the exact child-before-parent order the vendor
relies on to satisfy foreign keys. The engine keeps this order and additionally
defers+retries any table still FK-blocked (schema drift / newer releases), so the
static order is a fast-path, not the sole guarantee.

Execution order across DBs: ORG (2) -> MAIN (3) -> TRD365AI (7).
    org_delete   -> per-account org schema  (thinkrd365_org)
    main_delete  -> shared schema 'trd365'  (thinkrd365_main)
    ai_delete    -> schema 'public'         (trd365ai)
"""

# ── ORG DB — schema is the account's per-account org schema ────────────────────
ORG_TABLES = [
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
    "document", "attachment_timeline", "attachments", "notes_timeline", "notes", "activity_history",
    "activity_attachments", "meeting_summary", "activities", "account_interactions",
    "clientfirm_document_template_metadata", "clientfirm_document_template", "account_fiscal_region",
    "account_fiscal", "account_timeline_old", "interaction_attachments", "interaction_response_history",
    "interaction_status_history", "interaction_timeline", "case_history_submission",
    "history_staging_project", "history_staging_resource", "history_staging_interaction",
    "history_staging_case", "history_staging_account", "history_staging_document", "account_details",
]

# ── MAIN DB — shared schema 'trd365'; all keyed by account_rid ─────────────────
MAIN_SCHEMA = "trd365"
MAIN_TABLES = [
    "rd_credit_calculations_summary", "case_summary", "send_email_info", "ai_trigger_records",
    "interactions_summary", "rule_engine_records", "rule_engine_notification_records",
    "control_center_execution", "user_group_entity_access", "project_fiscal_summary",
    "chat_assistance_session", "attachment_summary", "notes_summary", "meeting_summary",
    "task_summary", "project_summary", "customisation_checks", "subscription_renewal_records",
    "user_group_account_mapping", "account_fiscal_summary", "account_allowed_domains", "account",
]

# ── TRD365AI — schema 'public'; keyed by project fiscal (projectId) ────────────
AI_SCHEMA = "public"
AI_TABLES = [
    "master_project_ai_summary_logs", "master_project_ai_summary_sections", "master_project_ai_summary",
    "master_project_ai_interaction", "master_project_ai_assessment", "master_ai_request",
    "master_ai_llm_logs", "master_ai_knowledge_base", "master_project_details", "four_part_assessments",
]

# Steps in execution order: (step_key, db_key, schema_kind, tables)
STEPS = [
    ("org_delete",  "orgdb",    "org",  ORG_TABLES),
    ("main_delete", "maindb",   "main", MAIN_TABLES),
    ("ai_delete",   "trd365ai", "ai",   AI_TABLES),
]
