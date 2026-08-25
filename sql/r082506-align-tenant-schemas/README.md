# r082506 — aligning tenant schemas to `trd365_00440`

Generated 2026-08-25 from the live definition of the production org database.
Baseline `trd365_00440`; `trd365_00042` excluded by request.

**Nothing here has been run.** These are scripts to review, not a change that has
happened.

## What to run, in order

```bash
psql "$ORGDB" -f 01_backup_all.sql     # or 01_backup/trd365_00399.sql for one schema
psql "$ORGDB" -f 02_align_all.sql
# if it goes wrong
psql "$ORGDB" -f 03_undo_all.sql       # or 03_undo/<schema>.sql
```

Every schema is one transaction with `ON_ERROR_STOP`, so a failure rolls that
schema back and stops the run. The per-schema files are the unit — run one, all,
or any subset.

Backups are `<schema>.r082506_<table>`, a straight copy of the data taken before
anything is altered. The backup script fails rather than overwrites if a copy of
that name already exists, and refuses to finish unless every row count matches.

## What is aligned, and what is not

134 of 387 differences are applied. The rest are held back on purpose.

| Tier | Count | Applied | Why |
|---|---|---|---|
| `add` | 3 | yes | A column the baseline has and this schema lacks. Added nullable. |
| `widen` | 34 | yes | `varchar(50)` → `varchar(255)` and similar. Nothing can fail. |
| `loosen` | 2 | yes | Dropping a `NOT NULL` the baseline does not have. |
| `default` | 19 | yes | Tenant-neutral defaults only — in practice `now()`. |
| `tighten` | 76 | yes, guarded | Adding `NOT NULL`. Each is preceded by a check that raises if the column still holds nulls. |
| `narrow` | 12 | **no** | Would lose data. See `held_back.sql`. |
| `identity` | 241 | **no** | Tenant-identity defaults. See `NOT-ALIGNED.md`. |

### Three things worth knowing before you run this

**The baseline is not always the better shape.** Twelve changes would *narrow* a
column to match 00440 — `varchar(120)` → `varchar(50)`, `numeric` → `integer`,
and two that would drop the time zone from a `timestamptz`. That last pair is the
opposite of what the drift report recommends. They are in `held_back.sql` with a
read-only query each that says whether the narrowing is safe today.

**241 default differences must never be aligned.** They encode which tenant the
row belongs to — a schema-named sequence, or a literal `'P001-'` prefix. Copying
00440's version into another schema would point that tenant's ids at 00440's
counter. `NOT-ALIGNED.md` has the detail.

**`project_timeline.rid` defaults to `'${ENV_PREFIX}' || gen_random_uuid()` in 24
of 26 schemas.** An unsubstituted template variable, estate-wide. Every row
inserted there without an explicit rid gets a literal `${ENV_PREFIX}-<uuid>`.
That is not drift and this change set does not touch it — it is a provisioning
defect to fix everywhere at once.

## Undo

`03_undo/<schema>.sql` restores the column definitions exactly as they were read
today, in reverse order. It does not restore data: if a type conversion mangled
values, the pre-change rows are in `r082506_<table>` and putting them back is a
deliberate act, spelled out at the foot of each undo file.

## Regenerating

`generate.py` builds every file from `changes.json`, which comes from
`information_schema` on the live database. Re-read and re-run it rather than
editing the SQL by hand — the risk tiers are computed, not annotated.
