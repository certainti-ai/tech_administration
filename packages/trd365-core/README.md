# trd365-core

The shared foundation every maintenance utility builds on. Nothing here talks
to a specific business entity; everything here is what all the utilities needed
and each had been re-implementing.

```bash
pip install -e "packages/trd365-core[dev]"
pytest packages/trd365-core
```

## What it provides

| Module | Responsibility |
|---|---|
| `environments` | The four environments and how credentials resolve |
| `db` | Connections, SSH tunnels, reads that cannot hang |
| `datamodel` | The application data model every utility must know |
| `cli` | Argument conventions, including the `--apply` safety rule |
| `audit` | Append-only record of who ran what, where, and what changed |
| `registry` | The catalogue the Phase-2 API and Phase-3 UI generate from |
| `model_snapshot` | The discovered model: produced by analysis, consumed by all |

## The data model

Every utility needs the same facts about the application's schema, and each
script previously rediscovered them — slightly differently. `datamodel` holds
them once, lifted from `data_model_analysis/model_analysis.py`:

```python
from trd365_core import datamodel as dm

dm.entity("case").table          # "cases"  — entity singular, table plural
dm.entity("account").is_cross_db # True     — lives in maindb, referenced from orgdb
dm.is_polymorphic("entity_rid")  # True     — no single parent, by design
dm.is_backup_table("bak_project")# True     — excluded from analysis and purges

catalog = dm.load_catalog(pool.fetcher(), "orgdb", "trd365_00042")
for ref in dm.references(catalog):
    print(ref.from_table, ref.column, "->", ref.to_table, ref.note)
```

The conventions encoded: primary keys are `rid`; foreign keys are
`{prefix}_rid`; parent tables are plural-aware (`resource_rid` → `resources`);
`account_rid` is a cross-database edge into `maindb` that no foreign key
enforces; org is multi-tenant by `trd365_*` schema.

The pure functions take catalogs rather than connections, so resolution is
fully testable without a database.

## Environments

```python
from trd365_core import Environment, ConnectionPool

with ConnectionPool(Environment.PROD) as pool:
    print(pool.verify("maindb"))
```

Credentials resolve from `TRD365_<ENV>_<DBKEY>_<FIELD>`, falling back to the
legacy unscoped names (`MAINDB_HOST`, …) **for prod only** — so the existing Key
Vault inventory works today without a rename.

Dev, QA and Stage are placeholders until real credentials arrive. They are
deliberately unusable: `connection_settings` raises rather than returning them,
naming the exact variables that would fix it. A half-configured environment
fails immediately instead of connecting somewhere unintended.

## The CLI safety rule

```python
from trd365_core import build_parser, common_args, confirm_production, describe_mode

parser = build_parser("Purge an account and everything beneath it.")
parser.add_argument("--account-rid", required=True)
args = common_args(parser.parse_args())

print(describe_mode(args, "purge-account"))
confirm_production(args, "purge-account")
```

Three rules, applied identically everywhere:

1. `--env` is required, with no default.
2. Writes happen only with `--apply`; the default is a dry run.
3. `--dry-run` is a **hard error**, not a silent no-op.

Rule 3 matters more than it looks. Three legacy tools — including account
deletion and fiscal-year deletion — wrote *by default* and used `--dry-run` to
preview. Reversing that is correct, but an operator with the old habit would
otherwise type `--dry-run`, have it rejected as an unknown flag, and watch the
tool delete for real. It fails loudly and explains the change instead.

## Audit

```python
from trd365_core import AuditedRun

with AuditedRun("purge-account", args.env, applied=args.apply) as run:
    run.record_rows("trd365_00042.project", deleted)
```

One record per invocation: who, what, where, when, arguments, outcome, and rows
affected per table. Written on success, failure **and** cancellation — a purge
that died halfway is exactly the run you need the record for. Credential-shaped
arguments are redacted before they reach the sink.

## Model propagation

`datamodel` holds the *conventions* — they are rules and do not change when a
database does. The *discovered* model does change, and it has one producer and
many consumers:

```python
# Producer — the data-model analysis utility, and only it.
snapshot = build_snapshot(pool.fetcher(), args.env, generated_by="model-analysis")
version = FileModelStore().save(snapshot)

# Consumer — every other utility.
model = require_model(FileModelStore(), args.env, utility="purge-account")
for table in model.tables_referencing("trd365_00042", "project"):
    ...
```

Re-running the analysis writes a new snapshot, and every other utility picks it
up on its next run — no code change, no rebuild, no regeneration step.

Snapshots are per environment, immutable, and versioned; writes are atomic and
the `latest` pointer moves last, so a consumer reading mid-analysis sees the
previous model rather than a half-written one. Previous versions are kept, and
`diff_snapshots()` reports what changed — the schema-drift signal for the
dashboard.

`require_model` **fails** on a missing or stale snapshot rather than falling
back:

```
purge-account found a data-model snapshot for prod that is 30 day(s) old (limit 7).
Re-run the data-model analysis, or pass a longer max_age if that is deliberate.
```

A purge running against an out-of-date understanding of the schema is the exact
failure this design exists to prevent, so staleness is an error, not a warning.

## Testing note

The pool takes its `connect` and `tunnel_factory` as constructor arguments so
the class can be driven by fakes. The maintenance VM reaches the databases
directly — this is for unit testing, not a workaround; the production path is
the plain default.
