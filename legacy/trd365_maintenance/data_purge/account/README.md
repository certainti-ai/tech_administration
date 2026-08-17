# Account purge sub-module

Delete **all data for one or more accounts** across ORG, MAIN, and TRD365AI —
backup → delete (children-first) → audit → report.

See [`DELETION_ORDER.md`](DELETION_ORDER.md) for the exact table order.

## Usage

```bash
cd data_purge/account

# DRY RUN (default) — read-only analysis: resolves the account, counts impacted
# rows per table across all 3 DBs, writes a report. No writes.
python purge_account.py --account-rid P001-abc...

# LIVE — backup into data_purge.bak_<table>, delete, audit, report
python purge_account.py --account-rid P001-abc... --apply

# Batch from a CSV that has an `account_rid` column (status written back)
python purge_account.py --csv input/accounts.csv --apply --chunk-size 2000
```

## The five phases

1. **Analyse** — `resolve_account` (SECTION-1 logic: `store_in_parent` accounts
   resolve to the parent's schema) + `capture_id_sets` (cases/fiscals/projects/
   resources/interactions — needed to scope tables lacking `account_rid` and to
   reach TRD365AI after ORG is gone). Dry-run stops here.
2. **Backup** — into `data_purge.bak_<table>` in the same DB, tagged by run id.
3. **Delete** — chunked + committed, children-before-parents, multi-pass on FK.
4. **Audit** — 0 residual in-scope rows, backups == deletes, no collateral.
5. **Report** — `reports/account_<rid>_<ts>.{txt,json}`.

## Resume & safety

- **Resumable:** a checkpoint in `state/<rid>.json` records completed tables and
  the captured id-sets; re-running continues from where it stopped (and resumes
  even if the `account` row itself was already deleted).
- **UNSCOPED tables** (no way to scope to an account) are reported and left
  untouched — never blind-deleted.
- **Rollback:** every deleted row is in `data_purge.bak_<table>` with its
  `_purge_run_id`; restore by re-inserting those rows (drop the audit columns).
