# 01_account_deletion — chunked, resumable account deletion

A new deletion runner that processes accounts listed in an input CSV, deleting
each account's data across the three databases **in small committed chunks**,
backing up first, resuming intelligently after failures, and producing a
detailed metrics report per account. It does **not** touch the existing
`account_deletion/` code.

## How it differs from the old approach
| | old `account_deletion/` | this `01_account_deletion/` |
|---|---|---|
| Input | one account per run (`--accounts`) | CSV list with a `status` column |
| Delete size | whole section in one transaction | **1,000-row chunks with commits** |
| Restart | re-run section from scratch | **resumes at the failed table; deletes only remaining rows** |
| Status | manual | auto-updates CSV `To be Processed` → `Processed`/`Failed` |
| Metrics | NOTICE text | **structured report**: rows before/after/deleted per table, batches, time per table & step, totals, top/slowest tables |

## Setup
```bash
pip install -r requirements.txt
# config/db_config.json is pre-filled (copied from the working config).
# Passwords via the file, or env vars PG_MAINDB_PASSWORD / PG_ORGDB_PASSWORD /
# PG_TRD365AI_PASSWORD and SSH_TUNNEL_PASSWORD, or you'll be prompted.
```

## Input file
`input/accounts.csv`:
```csv
account_rid,status,processed_at,note,report
P001-xxxx...,To be Processed,,,
P001-yyyy...,To be Processed,,,
```
Only rows with status **`To be Processed`** are picked up. The runner updates each
row's `status` (`Processed` / `Failed` / `Not Found`), `processed_at`, `note`, and
`report` (report filename) in place.

## Run
```bash
cd 01_account_deletion

# 1) DRY RUN first — read-only. Counts what WOULD be deleted per table and flags
#    any table it can't scope to the account. No backups, no deletes, no status change.
python run.py --dry-run

# 2) Live run — chunked backup + delete, updates status, writes reports.
python run.py

# options
python run.py --chunk-size 1000          # rows per delete batch (default 1000)
python run.py --accounts P001-abc...      # limit to specific rids (must be in CSV)
python run.py --full-counts               # also record whole-table counts (slower)
```

## What it does per account
1. **Resolve** the account (r_number, org schema, `store_in_parent` handling). If the
   rid isn't in `trd365.account`, marks it `Not Found` and moves on.
2. **Capture id-sets** from the org schema (cases / project_fiscal / project /
   resources / …) *before* deleting — these scope child tables that lack
   `account_rid`, and the fiscal set scopes trd365ai. Persisted for resume.
3. For each step (**org → main → trd365ai**), walk the vendor-derived table order
   (children before parents) and for each table:
   `count → back up + delete in 1,000-row committed chunks → count remaining`.
4. **Checkpoint** after every table (`state/<rid>.json`). Re-running skips completed
   tables and reprocesses an interrupted one against only its remaining rows.
5. **Report** to `reports/<rid>_<ts>.txt` and `.json`, and set CSV status.

## Safety
- Every deleted row is copied first into a per-account backup schema
  `del_backup_<r_number>` (`bak_<table>` + `_backup_run_at` / `_backup_account_rid`).
- Deletes are scoped strictly by the account (via `account_rid` or captured id-sets).
- **Always `--dry-run` first.** If the dry-run report lists any **UNSCOPED** tables
  (a table with no account-scope column the engine recognizes), stop and review —
  those are left untouched by design rather than risk a wrong delete.

## Outputs
- `state/<rid>.json`   — checkpoint (resume + raw metrics)
- `reports/<rid>_<ts>.txt` / `.json` — human + machine metrics report
