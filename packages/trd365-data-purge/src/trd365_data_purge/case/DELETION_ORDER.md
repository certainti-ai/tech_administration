# Case purge — table deletion order

Tables deleted when purging one **case**, in execution order (children → parents;
`cases` anchor last). Scoped by `case_rid` (`checklist_items` via `checklists`).
Pure subtree delete — **no recompute**. Every table backed up into
`data_purge.bak_<table>` before deletion.

## 1. ORG DB — `thinkrd365_org.<account_schema>`

| # | table | scope |
|---|-------|-------|
| 1 | rd_credit_processing_status | case_rid |
| 2 | rd_credit_state_calculations | case_rid |
| 3 | rd_credit_country_calculations | case_rid |
| 4 | case_project_task | case_rid |
| 5 | case_project_resource_fiscal | case_rid |
| 6 | case_project_resource | case_rid |
| 7 | case_project_fiscal_region | case_rid |
| 8 | case_projects | case_rid |
| 9 | case_task_dependency_mapping | case_rid |
| 10 | case_task | case_rid |
| 11 | case_team | case_rid |
| 12 | case_milestone | case_rid |
| 13 | case_key_contact_details | case_rid |
| 14 | case_technical_summary | case_rid |
| 15 | signoff_details | case_rid |
| 16 | dossier_form | case_rid |
| 17 | checklist_items | via checklists (case_rid) |
| 18 | checklists | case_rid |
| 19 | comments_attachments | case_rid |
| 20 | case_history | case_rid |
| 21 | case_timeline | case_rid |
| 22 | **cases** | rid (anchor — last) |

## 2. MAIN DB — schema `trd365`

| # | table | scope |
|---|-------|-------|
| 23 | rd_credit_calculations_summary | case_rid |
| 24 | chat_assistance_session | case_rid |
| 25 | case_summary | case_rid |

**Left untouched (no case link in schema — reported as UNSCOPED):**
`case_timeline_old`, `case_projects_by_region` (no `_rid` columns),
`case_history_submission` (account/geography-scoped, not per-case).

*Order is a fast-path; the engine additionally defers+retries any table a real FK
still blocks (multi-pass), so it is correct even under schema drift.*
