# data_purge — id-based deletion sub-modules

A unified framework for **deleting all data belonging to one entity**, by its id,
across the three databases (ORG `thinkrd365_org`, MAIN `thinkrd365_main`,
TRD365AI), with backup, audit, and a summary report.

Planned sub-modules (one per entity root):

| sub-module | delete by | status |
|---|---|---|
| `account/` | account rid | ✅ built (pure delete — whole account) |
| `project/` | project rid | ✅ built (delete **+ recompute**) |
| `project_fiscal/` | project_fiscal rid | ✅ built (delete **+ recompute**) |
| `case/` | case rid | ✅ built (pure subtree delete) |
| `interaction/` | interaction rid | ✅ built (pure subtree delete) |
| `resource/` | resource rid | ⏳ deferred — needs app QRE re-aggregation (see note) |

**Two flavours of sub-module:**
- *Whole-entity* (account): the entity and everything under it goes — pure
  backup → delete → audit (no surviving parent to recompute).
- *Sub-entity* (project, project_fiscal, …): the parent survives, so the run also
  **recomputes** parent aggregates. These reuse the vetted
  `project_fiscal_year_deletion` SECTION SQL verbatim (delete + recompute) —
  orchestrated per fiscal — rather than re-deriving the financial math.

Each sub-module runs the **same five phases** (see `engine/core.py`):

1. **Analyse** — resolve the entity, capture id-sets, count impacted rows per
   table across all impacted DBs. `--dry-run` (the default) stops here.
2. **Backup** — copy impacted rows into the shared **`data_purge`** schema of
   each impacted DB (`data_purge.bak_<table>`), tagged with `_purge_run_id` /
   `_purge_entity` / `_purge_entity_rid` / `_purge_run_at`.
3. **Delete** — chunked, committed, **children-before-parents**; any table still
   FK-blocked is deferred and retried (multi-pass) until the order is satisfied.
4. **Audit** — verify **only intended rows were removed**: 0 residual in-scope
   rows, `backed_up == deleted`, and `total_after == total_before − deleted`
   (no collateral rows lost to an unexpected cascade).
5. **Report** — JSON + text summary in the sub-module's `reports/`.

## Layout

```
data_purge/
├── config/db_config.json     # DB connections (shared)
├── engine/
│   ├── db.py                 # connection pool + SSH tunnels
│   ├── core.py               # generic backup+delete+multi-pass+audit
│   └── report.py             # 5-phase summary report
├── account/                  # ← account sub-module
│   ├── manifest.py           # FK-safe table order (ORG/MAIN/AI)
│   ├── scoping.py            # resolve + id-sets + per-table predicate
│   ├── purge_account.py      # CLI entry (the 5 phases)
│   ├── DELETION_ORDER.md     # tables in deletion order (summary file)
│   └── reports/ , state/
└── reports/
```

## Design notes

- **Backups go to the source row's own DB.** `data_purge` is created (if absent)
  in each of the three databases; a backup row exists **iff** its source row was
  deleted in the same committed batch — so `data_purge` is a faithful, resumable
  undo log across runs and entities.
- **Children-first, then multi-pass.** The static manifest encodes the vendor's
  FK-safe order; the engine additionally defers+retries any table a real FK
  constraint still blocks, so it is correct even under schema drift.
- **Dry-run first.** The default mode performs the analysis only (no writes) —
  always preview before `--apply`.
- **Referenced sources:** `account_deletion/` (engine + manifest),
  `project_fiscal_year_deletion/` (section order), and the data-model analysis in
  `data_model_analysis/` (entity/FK graph).

> `config/db_config.json` holds **live production credentials** — every apply run
> writes to production. Back up (automatic) + audit (automatic) + dry-run first.
