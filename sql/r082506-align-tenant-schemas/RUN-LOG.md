# r082506 — execution record

Applied against the **production** org database (`thinkrd365_pvt_org`) on
2026-08-25, one schema at a time, each step individually approved.

Baseline: `trd365_00440`.  Every schema was backed up (`r082506_<table>`) with a
row-count assertion inside the same transaction before any `ALTER` ran, and
verified against the baseline afterwards.

Full psql transcript: `/var/lib/trd365/reports/r082506-run.log` on the
maintenance VM.

## Order and outcome

Schemas were run in ascending order of change count.

| # | Schema | Stmts | Result |
|---|--------|-------|--------|
| 1 | `trd365_00397` | 1 | aligned |
| 2–9 | `trd365_00399` `00408` `00413` `00414` `00416` `00431` `00436` `00445` | 1 each | aligned |
| 10 | `trd365_00462` | 2 | aligned |
| 11–14 | `trd365_00385` `00386` `00388` `00393` | 4 each | aligned |
| 15 | `trd365_00468` | 7 | aligned |
| 16 | `trd365_00476` | 7 | aligned |
| 17–20 | `trd365_00375` `00377` `00378` `00381` | 29 each | aligned |
| 21–22 | `trd365_00353` `00363` | 37 each | aligned |

`trd365_00411`, `trd365_00428` and `trd365_00453` needed no changes.

82 `r082506_` backup tables were created across the estate.  Every script
exited 0; none was retried, and no transaction rolled back.

## Held back

Nothing that narrows a column or weakens a constraint was applied.

- **12 `narrow` statements** — 4 each in `trd365_00353`, `trd365_00363` and
  `trd365_00042`.  These shorten `varchar`, convert `numeric(18,2)` to
  `integer`, or drop a time zone, and can lose data.
- **2 `enum` statements** — `webhook_email_history.status` in `trd365_00353`
  and `trd365_00363`.  Discovered during the run: the column is the enum
  `enum_webhook_email_history_status` there and `varchar(20)` in the baseline.
  The generator had misfiled it as a widening because
  `character_maximum_length` goes from `NULL` to `20`; converting it would drop
  the enum's value constraint.  See `held_back.sql`.
- **241 tenant-identity defaults** — `nextval`, `'P001-' || …`, `${ENV_PREFIX}`.
  These must never be copied between schemas.

## Known gaps after the run

- **`case_technical_summary.r_number` has no default in 6 schemas**
  (`trd365_00353` `00363` `00385` `00386` `00388` `00393`).  The column is
  `varchar(20) NULL` in all 27 schemas, so only the default differs.  It was
  excluded from the change set because the generator treats every `nextval`
  default as tenant-specific.  Which sequence to use is a decision, not a
  mechanical fix: 7 schemas (including the baseline) draw from
  `case_technical_summary_seq`, and 13 draw from `interaction_history_seq`.
- **`trd365_00042` is still present** in the database with 41 differences from
  the baseline.  It was excluded from the change set on the understanding that
  it had been dropped.  Nothing in this run touched it.

## Reverting

`03_undo/<schema>.sql` reverses one schema; `03_undo/undo_all.sql` reverses the
estate.  The `r082506_` copies hold the pre-change rows and are not dropped by
the undo — remove them deliberately once the change is accepted.
