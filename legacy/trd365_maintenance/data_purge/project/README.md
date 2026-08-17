# Project purge sub-module

Delete a **whole project** (all its fiscal years) across ORG + MAIN + TRD365AI,
**with parent-aggregate recompute**, backup, and audit.

## How it works

A project deletion = deleting each of the project's project-fiscals in turn, using
the vetted vendor `SECTION 1–8` flow (`../project_fiscal/base_sql/`), with
`is_last_fiscal=TRUE` on the **final** fiscal so its run also removes the
project-level rows and recomputes the account-level aggregates.

> The financial **recompute** (account_fiscal, project rollups, resource_fiscal,
> case_projects, project_summary, account totals) is reused **verbatim** from the
> vendor SQL — not re-derived — which is what keeps totals correct. This module is
> the orchestration + resolution + reporting layer on top of that proven SQL.

## Usage

```bash
cd data_purge/project

# DRY RUN (default) — runs every section against real data but ROLLS BACK; nothing persists
python purge_project.py --account-id ACC-00459 --project-rid P001-…

# LIVE — backup + delete + recompute, committed per section
python purge_project.py --account-id ACC-00459 --project-rid P001-… --apply

# resolve the project by code/name instead of rid
python purge_project.py --account-rid P001-… --project-code "Infosys FY25 Project 1" --apply
```

## Phases (per fiscal, via the vendor sections)

| phase | sections | does |
|---|---|---|
| 1 Analyse | 1 (ORG), 6 (AI) | pre-delete counts (the whole run in `--dry-run`) |
| 2 Backup | inside 2/3/7 | copy impacted rows into `data_purge.bak_org_/bak_main_/bak_ai_<table>` |
| 3 Delete | 2 (ORG), 3 (MAIN), 7 (AI) | children→parents; fiscal row last; project row on final fiscal |
| 4 Recompute | inside 2/3 | account_fiscal, project, resource_fiscal, case_projects, project_summary, account |
| 5 Audit+Report | 4 (ORG), 5 (MAIN), 8 (AI) | post-delete diffs + `reports/project_<rid>_<ts>.{txt,json}` |

## Notes

- **Backups** accumulate in the shared `data_purge` schema of each DB, tagged with
  `_backup_project_fiscal_id` / `_backup_run_at`.
- **Dry-run** runs all 8 sections (so you see real counts + recompute) and rolls
  back every DB at the end of each fiscal — nothing is written.
- **Stops on first failing fiscal** (FK integrity); committed fiscals persist, so a
  re-run continues with the remaining ones.
- Deleting a single fiscal instead of the whole project → use
  [`../project_fiscal/purge_project_fiscal.py`](../project_fiscal/purge_project_fiscal.py).
- Table order: see [`../project_fiscal/DELETION_ORDER.md`](../project_fiscal/DELETION_ORDER.md).
