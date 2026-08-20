# trd365-analysis

Discover the data model, publish it for every other utility, and report on its
health.

This is the **producer** of the shared model snapshot (PRD FR-1.9/1.10). Nothing
else writes one. Every destructive utility is a consumer: it calls
`require_model()` and refuses to `--apply` against a model that is missing or
stale. So an environment that has never been analysed here cannot be written to
by the other tools — that is deliberate, and it is why this is the first thing
to run against a new environment.

Ported from `legacy/trd365_maintenance/data_model_analysis/`.

## Running it

```bash
python -m trd365_analysis --env dev                        # analyse and report
python -m trd365_analysis --env dev --apply                # …and publish the model
python -m trd365_analysis --env dev --schemas trd365_00042
python -m trd365_analysis --env dev --no-orphans           # structure only, much cheaper
python -m trd365_analysis --env dev --all-entities         # widen the orphan scan
```

It is read-only against the databases. `--apply` does not write to any database
— it publishes the snapshot. That still needs the flag, because replacing the
model every other utility trusts is consequential, and a snapshot should not be
overwritten as a side effect of somebody looking.

| Exit code | Meaning |
|---|---|
| 0 | analysed, and published if asked |
| 1 | a schema could not be scanned, or there was nothing to analyse |
| 2 | bad invocation |

Exit 1 with a published model is a real and correct outcome: the structural
model is complete and consumers need it, but the orphan figures are incomplete
and reporting them as fact would be a lie.

## What it produces

**The snapshot** — tables, `_rid` columns, resolved references, and naming
deviations, per tenant schema, content-fingerprinted so a consumer can tell
whether the model actually changed. Stored under `$TRD365_MODEL_DIR` (default
`~/.trd365/model`), one directory per environment, with `latest.json` rewritten
last so a reader never sees a half-written model.

**Orphan rows** — child rows whose `{entity}_rid` names a parent that no longer
exists. Most of these relationships have no foreign-key constraint, and
`account_rid` cannot have one because it crosses databases, so nothing prevents
orphans and only a scan finds them. Reported to `orphans_*.csv`.

**Naming deviations** — why a `_rid` column did not resolve, in
`deviations_*.csv`. Four classifications, only one of which is a defect:

| | |
|---|---|
| `typo` | resembles a real table name. **The one worth acting on.** |
| `global-lookup` | a shared entity whose parent lives in another schema |
| `polymorphic` | names its parent's type in a companion column; no single parent |
| `unknown` | rare, resembles nothing, needs a person |

## What changed in the port

- **Deviations are classified across schemas, not per schema.** The legacy tree
  carried a separate `reclassify_deviations.py` whose docstring explains why:
  *"The per-schema classifier … can mislabel a global-lookup reference as a typo
  when that reference happens to appear in only 1-2 tables in a single schema."*
  That is right, and it is a scope problem rather than a post-processing one.
  Tenant schemas are near-identical copies of one model, so the evidence is
  spread across all of them, and a snapshot already holds all of them. The
  classification now runs over the whole snapshot before it is saved, so
  consumers read the good answer and nobody has to remember a second script over
  a pair of CSVs. Withdrawn false alarms are counted in the report.

  Distinct `(schema, table)` pairs are counted, not rows: forty tenants carrying
  the same table is one fact about the model repeated forty times, and counting
  it forty times would make every rare prefix look global as the estate grew.

- **The structural analysis lives in `trd365_core.datamodel`**, where every
  utility can reach it, rather than in this tool. This package adds what is
  genuinely its own: orphan detection, cross-schema classification, and
  publishing.

- **`--apply` is required to publish.** The original wrote CSVs and had no
  shared model to overwrite.

- **A failed edge is recorded, not fatal**, and a schema that could not be
  scanned fails the run rather than quietly reporting a low count.

- **The `analyze.py` stub is not ported.** It was scaffolding with
  `TODO: analysis logic to be provided next` where the logic goes;
  `model_analysis.py` is the real tool.

### Carried over unchanged

The **global-lookup exclusion**, which the original found the hard way: some
parent tables are empty in a tenant schema because the real rows live in a
master table in main — `interaction_type` is the example it calls out — so every
child row looks orphaned. A parent that is empty here *and* exists in main is
excluded from the scan and named in the report. Without this, `--all-entities`
reports thousands of orphans that are all fine.

## Not yet ported

- `remediate_orphans.py` — the destructive counterpart. Backs up and deletes
  orphan rows with the same validate-before-commit discipline as the purge
  engine. Next, and it should reuse that engine rather than repeat it.
- `schema_orphan_report.py` — adds a **main-side** check the sweep does not do:
  rows in `trd365` belonging to this schema's accounts that reference org
  entities which no longer exist. Genuinely additional.
- `gen_report.py`, `gen_er_explorer.py` — HTML generators, superseded by the
  Phase-3 dashboard.
- `reclassify_deviations.py` — **folded into this package**, see above.

## Tests

```bash
cd packages/trd365-analysis && pytest -q
```

73 tests against an in-memory stand-in (`tests/fakes.py`) that implements only
the reads this package issues. **Nothing here has run against a real database.**
`certainti-ai/rdcredits_platform_db_scripts` holds the real DDL and would let
these conventions be checked statically — see `docs/HANDOFF.md` §9.
