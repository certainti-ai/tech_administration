# trd365-data-purge

Delete every record belonging to one entity, across the three trd365 databases,
with a backup, an audit and a report.

Ported from `legacy/trd365_maintenance/data_purge/`. That module was already the
right shape — an entity-agnostic engine plus one manifest and scoper per entity —
so this is a port, not a rewrite. What changed is listed under
[What changed in the port](#what-changed-in-the-port).

**Built:** `purge-account`.
**Not yet ported:** case, interaction, project, project fiscal.

## Running it

```bash
python -m trd365_data_purge.account --env dev --account-rid P001-abc            # dry run
python -m trd365_data_purge.account --env dev --account-rid P001-abc --apply    # writes
```

Dry run is the default and `--apply` writes. This reverses the original tool,
which wrote unless it was given `--dry-run`; typing `--dry-run` now produces an
explanation rather than being ignored as an unknown flag.

| Exit code | Meaning |
|---|---|
| 0 | completed (or, in a dry run, analysed) with a clean audit |
| 1 | the purge failed, or the audit found something |
| 2 | bad invocation |
| 3 | the target does not exist and there is nothing saved to resume |

## What it does

Five phases, per entity:

1. **Resolve.** Find the entity and the org schema its rows live in. An account
   with `storage_type = store_in_parent` has no schema of its own — its rows sit
   in its parent's, distinguished only by `account_rid`.
2. **Capture.** Read the id-sets the later steps need, *while the rows still
   exist*. trd365ai has no path back to the org schema, and by the time its step
   runs the org rows are gone, so its scope has to be taken up front.
3. **Back up and delete.** In committed chunks, children before parents. The
   backup insert and the delete run in the **same transaction**, so a backup row
   exists if and only if the source row was removed. Anything still foreign-key
   blocked is deferred and retried on a later pass.
4. **Audit.** Read-only. Per processed table: no in-scope rows remain, rows
   backed up equals rows deleted, and the table's total fell by exactly the
   number deleted — the last catches rows lost to an unexpected cascade.
5. **Report.** A text and a JSON report in `--out-dir` (default `./reports`).

Backups land in the `data_purge` schema of the *same* database as their source,
one `bak_<table>` per source table, every row tagged with `_purge_run_id`,
`_purge_entity` and `_purge_entity_rid`. Many purges therefore coexist in one
backup schema. **Nothing removes them** — retention is a separate, deliberate
decision, not a side effect of purging.

## Scoping, and what it refuses to guess

A table belongs to the account if it carries `account_rid`, or has a foreign key
into a table that does, or carries one of a small set of unambiguous `*_rid`
columns whose parent does. Conditions are combined with `OR`: a row qualifies if
*any* link ties it to the account, because requiring all of them would leave rows
behind whenever one link is null.

A table satisfying none of those is reported as **unscoped** and left completely
untouched. `project_rid` is deliberately not in the fallback list: depending on
the table it means either a project or a project fiscal, and picking wrong would
scope a delete by an unrelated row's identifier.

## Resuming

A killed run leaves a checkpoint in `$TRD365_STATE_DIR` (default
`~/.trd365/state`), holding the completed tables **and the captured id-sets**.
Re-running the same command continues from where it stopped; `--restart`
discards the checkpoint.

Two details make the difference between recoverable and stranded:

- The saved id-sets win over re-reading them. After a partial purge a re-read
  comes back short or empty, which would silently leave the trd365ai rows.
- The account row itself is deleted during the main step, before the ai step.
  A run that died in between cannot resolve its own target any more, so it
  rebuilds it from the checkpoint rather than reporting "not found".

A dry run never resumes and never writes a checkpoint: it reports what the
database holds *now*, and skipping tables an earlier run completed would
under-report what the next `--apply` would do.

## The shared data model

Every utility works from the model produced by the data-model analysis
(PRD FR-1.9/1.10), so re-running that analysis propagates into the purge without
anyone editing a manifest. Specifically, `AccountScoper.discover()` unions live
introspection with the snapshot's account-referencing tables, and any drift
between the manifest and the model is logged and written into the audit record.

Applying **requires** a snapshot: purging against a stale idea of the schema is
the failure the shared model exists to prevent. A dry run proceeds without one,
with a warning, so an operator can preview before the first analysis has run.
`--ignore-model` overrides this and is recorded in the audit trail.

```
--model-max-age-days N   how old the snapshot may be (default 7; 0 accepts any)
--ignore-model           run without it
```

## The manifest is data

`account/manifest.py` reproduces the vendor's SECTION-file ordering unchanged.
It is not derived, and it should not be re-derived: the order is what stands
between a purge and a wall of foreign-key violations. `tests/test_manifest.py`
compares it against the legacy file line for line, so an edit has to be
deliberate.

The static order is a fast path, not the guarantee — the engine defers and
retries anything still blocked, so a newer schema still completes.

## What changed in the port

- **Schema metadata is no longer shared between databases.** The original cached
  columns and foreign keys in module-level dicts keyed by `(schema, table)` only,
  and `clear_caches()` was never called anywhere in the tree. In a one-shot CLI
  that is nearly harmless; under the long-running orchestrator it means one
  database's metadata can be served for another that shares a table name, and a
  schema change between jobs is never noticed. The cache is now keyed by database
  and owned by a `SchemaCache` scoped to a single run.
- **Dry run is the default** (see above).
- **A stuck run stops early.** If every remaining table is foreign-key blocked
  and none moved, retrying cannot help; the original would spin to the pass
  limit.
- **Every run is audited** through `trd365_core.audit`, with row counts recorded
  per table as the run proceeds rather than at the end, so a crashed run still
  has a record of what it removed.
- **Production needs a confirmation**, and without a terminal it refuses instead
  of hanging. The orchestrator passes `--yes` because it has already taken a
  second approval.
- **Batch mode is gone.** The original accepted a CSV of accounts and wrote
  statuses back. One invocation now purges one entity and produces one audit
  record; running a list of them is the orchestrator's job, where each becomes a
  separate job with its own approval, log and outcome.

## Tests

```bash
pip install -e packages/trd365-core -e "packages/trd365-data-purge[dev]"
cd packages/trd365-data-purge && pytest -q
```

No Claude Code session can reach the real databases, so the engine is exercised
against `tests/fakes.py` — a small in-memory Postgres stand-in with real
transaction semantics, which implements only what the purge actually issues and
raises `NotImplementedError` for anything else. Scoping is asserted on the SQL
and parameters it produces rather than on the effect of running it.

**This has never run against a real database.** That is the next thing that
should happen to it — see `docs/HANDOFF.md`.
