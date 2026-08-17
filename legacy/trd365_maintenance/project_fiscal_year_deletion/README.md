# project_fiscal_year_deletion — batch runner for the SECTION 1–8 scripts

Runs the hand-written `base_sql/` deletion scripts (SECTION 1 → 8) for **many
projects in sequence**, reading the project list from an input CSV. It automates
the manual steps you'd otherwise do by hand: filling in each script's
`FILL IN` variables, running each section against the correct database in order,
and **carrying SECTION 1's announced backup-schema name into sections 2–8**.

Database connection handling (per-DB SSH tunnels, connect retry/backoff,
connection logging) and the CSV-with-status / dry-run / per-item report workflow
are inherited from `account_deletion/`.

## What the SQL looks like
Each `base_sql/NN_..._SECTIONn.sql` is one PL/pgSQL `DO` block with a small block
of `FILL IN` variable declarations at the top, e.g.

```sql
v_schema_name       TEXT    := 'trd365_01379';
v_account_rid       TEXT    := 'D001-…';
v_project_rid       TEXT    := 'D001-…';
v_project_fiscal_id TEXT    := 'D001-…';
v_is_last_fiscal    BOOLEAN := FALSE;
```

Sections 2–8 need SECTION 1's `v_backup_schema` value pasted into their own
`v_backup_schema`. The runner uses **one backup schema for the whole execution**
(every project in a single `python run.py` run backs up into it) and forces that
name into all 8 sections — including overriding SECTION 1's own per-project
computed name. All projects share one `bak_<table>` per source table; rows are
tagged with `_backup_project_fiscal_id` / `_backup_run_at` so they coexist.

### Section → database routing (inferred from the filename token)
| Sections | DB key (`db_config.json`) |
|---|---|
| 1, 2, 4 | `orgdb` |
| 3, 5 | `maindb` |
| 6, 7, 8 | `trd365ai` |

The first section to touch a database creates the backup schema there; later
sections on the same DB reuse it.

## Setup
```bash
cd project_fiscal_year_deletion
pip install -r requirements.txt
# config/db_config.json is pre-filled (copied from the working config).
# Passwords via the file, or env vars PG_ORGDB_PASSWORD / PG_MAINDB_PASSWORD /
# PG_TRD365AI_PASSWORD and SSH_TUNNEL_PASSWORD, or you'll be prompted.
```

## Input file — `input/projects.csv`
```csv
schema_name,account_rid,project_rid,project_fiscal_id,fiscal_year,is_last_fiscal,status,processed_at,note,backup_schema,report
trd365_01379,D001-…,D001-…,D001-…,2024,FALSE,To be Processed,,,,
```
One row per project-fiscal. Column → SQL variable mapping:

| CSV column | feeds SQL variable(s) |
|---|---|
| `schema_name` | `v_schema_name` |
| `account_rid` | `v_account_rid` |
| `project_rid` | `v_project_rid` |
| `project_fiscal_id` | `v_project_fiscal_id`, `v_project_fiscal_rid`, `v_lookup_project_fiscal_id/_rid` |
| `fiscal_year` | `v_fiscal_year` (SECTION 3) |
| `is_last_fiscal` | `v_is_last_fiscal` (`TRUE`/`FALSE`) |

Only rows with status **`To be Processed`** (or **`Failed`**, for a re-run) are
picked up. The runner writes back `status`, `processed_at`, `note`,
`backup_schema` (the value SECTION 1 produced) and `report` (report filename).

## Run
```bash
# 1) DRY RUN first — runs every section but rolls back; nothing is committed.
python run.py --dry-run

# 2) Live run — commits each section, updates status, writes reports.
python run.py

# options
python run.py --projects D001-abc… D001-def…   # only these project_fiscal_ids
python run.py --sections 1 2 3                  # only these sections (debug)
python run.py --verbose                         # stream each section's NOTICE output
python run.py --heartbeat 30                     # progress tick every 30s (0 = off; default 15)
python run.py --backup-schema my_backup_2026    # name the execution's backup schema
python run.py --input input/projects.csv --config config/db_config.json
```

### What a project run does
For each picked-up row, sections 1→8 run in order:
1. The row's values are substituted into the section's `FILL IN` variables.
2. The section's `DO` block is executed against its database.
3. The execution-wide **backup schema** name is forced into every section, so
   all projects and all their impacted tables land in that one schema.
4. **Live:** each section is committed on success. **Dry-run:** nothing is
   committed — one connection per DB is reused so later same-DB sections still
   see the earlier (uncommitted) backup schema, then every connection is rolled
   back at the end of the project.

If a section fails, the project stops there, all connections roll back, the row
is marked **`Failed`** with the failing section in `note`, and the batch moves
on to the next project.

## Live progress / commentary
Each section is a single `DO` block, so `execute()` blocks until it finishes. To
show what's happening without waiting for the whole run, the console prints:
- a per-project banner with **`PROJECT i/N`**, batch elapsed time, and running
  `processed`/`failed`/`remaining` counts;
- a per-section start line (`SECTION n [db] … (started HH:MM:SS UTC)`);
- a **heartbeat** every `--heartbeat` seconds (default 15) while a section runs:
  `[HH:MM:SS] SECTION n [db] still running… 45s | <latest NOTICE>`. The elapsed
  time is always live; the trailing `<latest NOTICE>` shows the most recent
  message the server has emitted so far (blank until the driver surfaces one).
- on completion, `done in Xs (committed / dry-run: uncommitted)`; add `--verbose`
  to also dump each section's full `NOTICE` output.

## Post-delete verification (sections 4 / 5 / 8)
After the deletes, sections 4 (ORG), 5 (MAIN) and 8 (AI) diff each table's
pre-count (captured by sections 1/3/6) against a fresh post-count and print
`table | pre | post | diff | result`:
- **PASS** — a fiscal-scoped table went to 0 (deleted as expected);
- **SKIP (not last fiscal)** — a project-scoped parent row left intact (correct
  when `is_last_fiscal = FALSE`);
- **FAIL** — a table that should have been emptied still has rows (investigate).

These sections resolve the pre-snapshot's `run_at` dynamically from the backup
schema (`max(run_at)` for the fiscal), so verification works whether sections are
run one-per-transaction by the runner or manually — in both live and dry-run.

## Dry-run vs live
- **`--dry-run`** exercises the full backup + delete logic and rolls it all back.
  Use it to confirm the scripts run cleanly for every project before committing.
  It does **not** change the CSV status.
- **Live** commits section-by-section. Because the work spans three databases,
  a failure partway leaves earlier committed sections in place. Re-running a
  `Failed` row restarts at SECTION 1 and backs up into the **same** execution's
  backup schema (`--backup-schema` to reuse a prior run's name); the deletes are
  re-scoped by the same ids, so already-deleted rows simply match nothing and no
  duplicate backup rows are written.

## Outputs
- `reports/<project_fiscal_id>_<ts>.txt` / `.json` — per-project report: section
  order, DB, status, timings, and the full captured `NOTICE` output.
- Input CSV updated in place with status / backup_schema / report per row.
