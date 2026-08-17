# Case purge sub-module

Delete one **case** (credit study) and its whole subtree across ORG + MAIN, with
backup + audit. **Pure subtree delete — no recompute** (verified: no account-level
aggregate depends on a case; `case_summary`/`rd_credit_calculations_summary` are
the case's *own* rows and are deleted).

## Usage

```bash
cd data_purge/case
python purge_case.py --account-id ACC-00459 --case-rid P001-…            # DRY RUN
python purge_case.py --account-id ACC-00459 --case-rid P001-… --apply
```

## Scope

Children-first, `cases` (anchor) last, then MAIN case-owned summaries. Scoped by
`case_rid`; `checklist_items` via `checklists`. Backups → shared `data_purge`
schema (`bak_<table>`), tagged with run id / entity / entity_rid.

| step | db | tables |
|---|---|---|
| case_org | ORG | rd_credit_*, case_project_*, case_projects(_by_region), case_task*, case_team, case_milestone, case_key_contact_details, case_technical_summary, signoff_details, dossier_form, checklist_items→checklists, comments_attachments, case_history(_submission), case_timeline, **cases** |
| case_main | MAIN | rd_credit_calculations_summary, chat_assistance_session, case_summary |

**UNSCOPED tables** (e.g. `case_timeline_old`, `case_projects_by_region`,
`case_history_submission`) have no case link in the schema and are reported +
left untouched — never blind-deleted.

## Phases

analyse → backup → delete (multi-pass FK) → audit (0 residual in-scope,
backups==deletes, no collateral) → report (`reports/case_<rid>_<ts>.{txt,json}`).
