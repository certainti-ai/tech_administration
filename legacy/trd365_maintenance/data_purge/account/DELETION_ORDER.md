# Account purge — table deletion order

Every table touched when purging **one account**, in the exact order the
sub-module deletes them. Deletes run **children → parents** so foreign keys are
satisfied; the account's anchor rows (`account_details` in ORG, `account` in
MAIN) are removed last in their database. Order is driven by the vendor SECTION
files; any table still FK-blocked at its position is automatically **deferred and
retried** after its children are gone (multi-pass), so newer/renamed tables not
in this static list are still handled safely.

Execution across databases: **ORG → MAIN → TRD365AI**. Each table's impacted rows
are backed up into `data_purge.bak_<table>` (same DB) **before** deletion.

Scope: a row belongs to the account if its own `account_rid` matches, or any of
its foreign keys points at a row of an account-scoped parent (resolved by the
*actual* FK target, not the column name). A handful of tables are scoped via an
explicit parent link (see notes). Tables that cannot be scoped to an account are
reported as **UNSCOPED** and left untouched for manual review.

---

## 1. ORG DB — `thinkrd365_org.<account_schema>`

Deleted in this order (children first; `account_details` last):

| # | table | note |
|---|-------|------|
| 1 | case_timeline_old | |
| 2 | rd_credit_processing_status | |
| 3 | rd_credit_state_calculations | |
| 4 | rd_credit_country_calculations | |
| 5 | case_project_task | |
| 6 | case_project_resource_fiscal | |
| 7 | case_project_resource | |
| 8 | case_project_fiscal_region | |
| 9 | case_projects | |
| 10 | case_projects_by_region | |
| 11 | case_task_dependency_mapping | |
| 12 | case_task | |
| 13 | case_team | |
| 14 | case_milestone | |
| 15 | case_key_contact_details | |
| 16 | case_technical_summary | |
| 17 | signoff_details | |
| 18 | dossier_form | |
| 19 | checklist_items | |
| 20 | checklists | scoped via cases |
| 21 | comments_attachments | |
| 22 | case_history | |
| 23 | case_timeline | |
| 24 | cases | |
| 25 | interaction_items | |
| 26 | interaction_history | |
| 27 | otp_entries_history | |
| 28 | otp_entries | |
| 29 | interactions | |
| 30 | four_part_assessment | |
| 31 | project_task_timeline | |
| 32 | project_task | scoped via project_fiscal |
| 33 | project_resource_fiscal_region | |
| 34 | project_resource_fiscal | |
| 35 | project_resource | |
| 36 | ai_technical_summary | |
| 37 | ai_assessment_audit | |
| 38 | ai_assessment_error | |
| 39 | ai_assessment_qre | |
| 40 | autosend_interaction_audit | |
| 41 | project_qre_adjustment_history | |
| 42 | project_fiscal_region | |
| 43 | project_history | scoped via project_fiscal (actual FK target) |
| 44 | project_timeline | |
| 45 | project_timeline_old | |
| 46 | account_timeline | |
| 47 | project_fiscal_history | |
| 48 | project_fiscal | |
| 49 | key_contact_details | scoped via project + own account_rid |
| 50 | project | |
| 51 | resource_skill | |
| 52 | resource_cost | |
| 53 | resource_fiscal_region | |
| 54 | resource_fiscal | |
| 55 | resources_history | |
| 56 | resources_timeline | |
| 57 | resources | |
| 58 | chat_answers | scoped via chat_sessions |
| 59 | chat_attachments | scoped via chat_sessions |
| 60 | chat_audit_log | scoped via chat_sessions |
| 61 | chat_branches | scoped via chat_sessions |
| 62 | chat_messages | scoped via chat_sessions |
| 63 | chat_questions | scoped via chat_sessions |
| 64 | chat_sessions | |
| 65 | kafka_events | scoped via document / import |
| 66 | import | |
| 67 | document | |
| 68 | attachment_timeline | scoped via attachments (attach_to) |
| 69 | attachments | |
| 70 | notes_timeline | scoped via notes (attach_to) |
| 71 | notes | |
| 72 | activity_history | |
| 73 | activity_attachments | |
| 74 | meeting_summary | |
| 75 | activities | |
| 76 | account_interactions | |
| 77 | clientfirm_document_template_metadata | |
| 78 | clientfirm_document_template | |
| 79 | account_fiscal_region | |
| 80 | account_fiscal | |
| 81 | account_timeline_old | scoped via attach_to = account rid |
| 82 | interaction_attachments | |
| 83 | interaction_response_history | |
| 84 | interaction_status_history | |
| 85 | interaction_timeline | |
| 86 | case_history_submission | |
| 87 | history_staging_project | |
| 88 | history_staging_resource | |
| 89 | history_staging_interaction | |
| 90 | history_staging_case | |
| 91 | history_staging_account | |
| 92 | history_staging_document | |
| 93 | **account_details** | anchor row — deleted last in ORG |

## 2. MAIN DB — shared schema `trd365` (all keyed by `account_rid`)

| # | table | note |
|---|-------|------|
| 1 | rd_credit_calculations_summary | |
| 2 | case_summary | |
| 3 | send_email_info | |
| 4 | ai_trigger_records | |
| 5 | interactions_summary | |
| 6 | rule_engine_records | |
| 7 | rule_engine_notification_records | |
| 8 | control_center_execution | |
| 9 | user_group_entity_access | scoped via project_fiscal_summary / project_summary |
| 10 | project_fiscal_summary | |
| 11 | chat_assistance_session | |
| 12 | attachment_summary | |
| 13 | notes_summary | |
| 14 | meeting_summary | |
| 15 | task_summary | |
| 16 | project_summary | |
| 17 | customisation_checks | |
| 18 | subscription_renewal_records | |
| 19 | user_group_account_mapping | |
| 20 | account_fiscal_summary | |
| 21 | account_allowed_domains | |
| 22 | **account** | anchor row — deleted last in MAIN |

## 3. TRD365AI — schema `public` (keyed by `projectId` = project_fiscal rid)

Scoped by the fiscal id-set captured from ORG **before** deletion (this DB has no
link back to the org schema).

| # | table | note |
|---|-------|------|
| 1 | master_project_ai_summary_logs | |
| 2 | master_project_ai_summary_sections | |
| 3 | master_project_ai_summary | |
| 4 | master_project_ai_interaction | |
| 5 | master_project_ai_assessment | |
| 6 | master_ai_request | |
| 7 | master_ai_llm_logs | |
| 8 | master_ai_knowledge_base | |
| 9 | master_project_details | |
| 10 | four_part_assessments | |

---

*Auto-discovery:* before each DB step the sub-module also scans for account-scoped
tables **not** in the lists above (schema drift / new releases) and appends them,
letting the multi-pass ordering place them correctly.
