# Manual R&D Percent Update

A standalone ops tool for manually correcting a project's R&D assessment
percentages (`rd_percent_potential_ai`, `rd_percent_adjustment`,
`rd_percent_final`) directly in the database, reproducing exactly what the
application does when a user adjusts these values through the product UI —
including every downstream update (QRE dollar recalculation, qualification
status, case-module tables, audit trail, financial summary).

It exists because the platform's Main DB and Org DB are separate Postgres
servers, so a plain `.sql` script can't touch both in one transaction the
way the application's own service layer does.

## What it does

For each project you give it, the tool:

1. Resolves the account (by its **Account ID**, i.e. `r_number`) and its
   tenant schema.
2. Resolves the project (by **project code + fiscal year**) to its internal
   `project_fiscal` row.
3. Validates that `rd_percent_final = rd_percent_potential_ai + rd_percent_adjustment`
   (the same rule the application enforces) and refuses to run if the three
   numbers you gave it are inconsistent.
4. Recalculates QRE dollar amounts and the qualification flag
   (`is_qualified = rd_percent_final > 0`) from the project's cost basis.
5. Snapshots every row it's about to touch into a backup table, then writes
   the updates — to `project_fiscal`, `project_resource_fiscal`, the
   case-module tables (if the tenant uses them), the audit timeline, the
   QRE adjustment history, and the Main DB's `project_fiscal_summary`.

All of this is traced against the real application code — see the header
comment in `index.js` for exact file/line references into `entity-module`.

## Files

| File | Purpose |
| --- | --- |
| `index.js` | The main tool — applies the update(s). |
| `rollback.js` | Undoes a run, restoring every row it touched. |
| `cleanup-backups.js` | Deletes backup rows/tables once you no longer need rollback capability. |
| `db-config.js` | **Database connection details live here.** No `.env` file is used. |
| `sample-input.csv` | Example input file — copy and edit for a real batch. |
| `package.json` | One dependency: `pg`. |

## Setup

```bash
cd scripts/manual-rd-percent-update
npm install
```

Open `db-config.js` and fill in the `CHANGE_ME` placeholders under
`DB_CONFIG.main` and `DB_CONFIG.org` with the real Main DB / Org DB host,
port, database name, user, and password.

> **This file will then contain live production credentials.** Do not
> commit it in that state. Either revert the credentials before committing,
> or keep your filled-in copy out of git entirely, e.g.:
> ```bash
> git update-index --skip-worktree db-config.js
> ```
> (run that from the repo root, with the path adjusted accordingly.)

## Usage

### Single project

```bash
node index.js \
  --account-id A0000001 \
  --project-code PRJ-1001 \
  --fiscal-year 2023 \
  --rd-percent-potential-ai 12.50 \
  --rd-percent-adjustment 2.33 \
  --rd-percent-final 14.83 \
  --comments "Manual re-assessment after client documentation" \
  --dry-run
```

Drop `--dry-run` once the preview looks right.

### Batch, from a CSV

```bash
node index.js --csv sample-input.csv --dry-run
```

CSV columns (header row required, any order):

| Column | Required | Meaning |
| --- | --- | --- |
| `account_id` | yes | The account's **r_number** (e.g. `A0000001`) — not the internal `account_rid`. |
| `project_code` | yes | The project's code. |
| `fiscal_year` | yes | Integer fiscal year. |
| `rd_percent_potential_ai` | yes | New AI-generated potential percentage. |
| `rd_percent_adjustment` | yes | The adjustment delta applied on top of it. |
| `rd_percent_final` | yes | Must equal `rd_percent_potential_ai + rd_percent_adjustment`. |
| `comments` | no | Freeform note, stored in the QRE adjustment history audit row. Quote it if it contains a comma. |

`user_rid` is **not** an input — every audit column (`modified_by`,
`created_by`, the timeline entry) is hardcoded to the literal string
`"system"`, since this tool runs outside any real user's session.

Each row is processed independently in its own transaction pair (Org DB +
Main DB) — one bad row does not abort the rest of the batch.

### `--dry-run`

Always try this first. It resolves the account, project, and all
downstream lookups, prints what it computed, and performs **zero writes** —
no updates, no backups, no audit rows. Recommended before every real run.

## What you get back

Every run — single record or batch, dry-run or real — writes an **output
CSV** next to your input (or in the current directory for single-record
runs): `<input>.results.<timestamp>.csv`, one row per input record, with:

- `status` — exactly `success` or `failed`
- `error` — the error message if it failed, blank otherwise
- `project_fiscal_rid` — the internal id that was resolved and updated
- `dry_run`, `run_id` — for traceability

A real (non-dry-run) run also writes a **backup manifest**:
`<input>.backup-manifest.<run_id>.csv`, listing every backup table this run
wrote into (database, schema, table name, row count) — your checklist for
rollback/cleanup later.

## Backups

Before touching any row, the tool snapshots it (full row, as JSON) into a
`manual_rd_percent_backup` table — created automatically in every Org DB
tenant schema it touches, and in the Main DB's `trd365` schema. Every row
backed up in a run is tagged with that run's `run_id` (printed at startup
and in the output CSV/manifest).

The backup insert for a row happens in the **same transaction** as the
update that follows it — a backup and its corresponding change always
commit or roll back together.

## Rolling back a run

If a run's results don't look right:

```bash
node rollback.js --run-id <run_id>          # preview — lists what would be restored, no writes
node rollback.js --run-id <run_id> --yes    # actually restores every row to its pre-run state
```

It finds every schema the run touched automatically (no need to remember
which accounts were involved). If the same row was updated more than once
within a run, it restores to the *earliest* snapshot — the true pre-run
state. Backup rows are never deleted by this — they stay as an audit trail
even after a rollback.

## Cleaning up backups

Once you've confirmed a run is correct and no longer need to be able to
roll it back:

```bash
node cleanup-backups.js --run-id <run_id> --yes
```

Deletes just that run's backup rows, leaving the backup table (and any
other runs' history in it) intact.

If you're completely done with this tool and don't need rollback
capability for **any** past run:

```bash
node cleanup-backups.js --drop-tables --yes
```

Drops the `manual_rd_percent_backup` table entirely, in every schema that
has one — irreversible, only do this when you mean it. Both commands
preview by default (list what would be removed/dropped); pass `--yes` to
actually execute.

## Typical workflow

```bash
node index.js --csv my-batch.csv --dry-run        # 1. preview
node index.js --csv my-batch.csv                  # 2. run it, note the run_id printed
#    ... check the results CSV, spot-check the data ...
node rollback.js --run-id <run_id> --yes          # 3a. something's wrong -> undo it
#    -- or --
node cleanup-backups.js --run-id <run_id> --yes   # 3b. all good -> clean up the backup rows
```

## Notes

- Parameterized SQL is used throughout (no string-interpolated values in
  queries) to avoid injection, even though the original application code
  this tool mirrors does interpolate raw values in places.
- The Main DB and Org DB are treated as two separate Postgres connections
  and transactions, matching the live application's own behavior — there is
  no distributed transaction across them, so it is possible (as it is in
  the app itself) for the Org DB side of a record to commit while the Main
  DB side fails. The Main DB update is idempotent, so re-running that
  record is safe.
- See the header comment in `index.js` for full traceability back to the
  exact application source files and line numbers this tool's logic was
  derived from.
