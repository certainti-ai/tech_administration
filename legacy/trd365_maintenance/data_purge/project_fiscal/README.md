# Project-fiscal purge sub-module

Delete **one project fiscal-year** across ORG + MAIN + TRD365AI, **with
parent-aggregate recompute**, backup, and audit. This is the atomic unit the
[project sub-module](../project/) iterates.

Built **from the existing `project_fiscal_year_deletion` SQL** — the vetted
`base_sql/SECTION 1–8` scripts are reused verbatim (parameterised per fiscal) so
the financial recompute is exactly the app-traced logic, not a re-derivation.

## Usage

```bash
cd data_purge/project_fiscal

# DRY RUN (default) — runs all sections, rolls back; nothing persists
python purge_project_fiscal.py --account-id ACC-00459 --project-fiscal-rid P001-…

# LIVE
python purge_project_fiscal.py --account-id ACC-00459 --project-fiscal-rid P001-… --apply

# force the last-fiscal cascade on/off (default: auto — TRUE iff it's the only fiscal)
python purge_project_fiscal.py --account-rid P001-… --project-fiscal-rid P001-… --apply --not-last-fiscal
```

## `is_last_fiscal`

- **Auto** (default): TRUE only if this is the project's **only** remaining fiscal
  — then the parent `project` row and project-level children are also removed.
- **FALSE**: the parent `project` is **kept** and its rollups + the account-level
  aggregates are **recomputed** to exclude this fiscal.
- Override with `--last-fiscal` / `--not-last-fiscal`.

## Files

| file | role |
|---|---|
| `base_sql/` | the vendor SECTION 1–8 delete + recompute SQL (source of truth) |
| `fiscal_flow.py` | runs the 8 sections for one fiscal (shared with project/) |
| `resolve.py` | account / project / fiscal resolution + `is_last_fiscal` |
| `purge_project_fiscal.py` | CLI (single fiscal) |
| `DELETION_ORDER.md` | full table order (deleted + recomputed) |

Backups land in the shared `data_purge` schema (`bak_org_/bak_main_/bak_ai_<table>`),
tagged with `_backup_project_fiscal_id` / `_backup_run_at`.
