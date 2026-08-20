# Knowledge Base — trd365 maintenance estate

Everything learned about the existing scripts, the databases they touch, and the
traps in them. Written for someone who has never seen this code.

Source material: `legacy/trd365_maintenance/` (114 files, vendored verbatim from
the operator's workspace on 2026-08-17, secrets already replaced with
`CHANGE_ME`).

---

## 1. The databases

Three Postgres instances, all currently Production:

| Key | Host | Database | User | Reached via |
|---|---|---|---|---|
| `maindb` | `prod-thinkrd365-psqlserver-centralus-pvt-main.postgres.database.azure.com` | `thinkrd365_pvt_main` | `adminUser` | **SSH bastion** |
| `orgdb` | `prod-thinkrd365-psqlserver-centralus-pvt-org.postgres.database.azure.com` | `thinkrd365_pvt_org` | `adminUser` | **SSH bastion** |
| `trd365ai` | `4.246.251.140` | `trd365ai` | `aiadmin` | direct |

Bastion: `172.203.151.166:22`, user `thinkrd_DevOps`, **password** auth (not a
key). `maindb` and `orgdb` are Azure private endpoints — their hostnames do not
resolve outside the VNet, which is why the tunnel exists.

`sslmode` is `require` for main/org, `prefer` for trd365ai.

### Why two databases matter

`maindb` and `orgdb` are **separate Postgres servers**, so no single transaction
can span them. This is the central constraint of the whole estate: every purge
and every correction has to sequence writes across servers and cope with
partial failure. It is the stated reason `manual-rd-percent-update` exists as a
program rather than a `.sql` file.

`orgdb` is multi-tenant by **schema** — each account has its own schema. Tools
routinely resolve "account → schema name" before doing anything.

### Identifier vocabulary

Recurring terms in the CLIs; getting these wrong is the usual source of
confusion:

- **Account ID** — the customer-facing `r_number`.
- **`*_rid`** — internal row id (`account_rid`, `case_rid`, `project_rid`,
  `project_fiscal_rid`, `interaction_rid`). Most tools accept either the
  friendly id or the rid, and resolve one to the other.
- **project code + fiscal year** → resolves to a `project_fiscal` row. Projects
  are versioned per fiscal year; `project_fiscal` is the thing most operations
  actually target.

## 2. The utilities

Nine top-level modules, 22 CLI entry points.

### `data_purge/` — the consolidated purge suite (**the good one**)

Sub-tools: `account`, `case`, `interaction`, `project`, `project_fiscal`.
Shared `engine/` provides `core.py`, `db.py`, `db_pfy.py`, `report.py`,
`section_runner.py`, `subtree_purge.py`.

All five use `--apply` (dry run by default) and share the same argument shape:
`--config`, `--account-id` / `--account-rid`, a target rid, `--chunk-size`,
`--apply`. Each carries a `DELETION_ORDER.md` documenting the order rows must be
removed in to satisfy foreign keys — **this is the most valuable documentation
in the estate; do not lose it.**

This module is the template the others should be refactored towards.

**Ported** to `packages/trd365-data-purge/` (session 4), `account` first. The
engine's own docstring is accurate — "This module is entity-agnostic… Nothing
here knows what an 'account' or a 'case' is" — so it was a port, not a rewrite.
Read that package's README for the deliberate deviations.

One real bug found while reading it, fixed in the port and **still present in
`legacy/`**: `engine/core.py` caches column and foreign-key metadata in
module-level dicts keyed by `(schema, table)` — not by database — and the
`clear_caches()` it defines is never called anywhere in the tree. In a one-shot
CLI that is nearly harmless. Under a long-running service running many purges it
means metadata read from one database can be served for another that happens to
share a schema and table name, and a schema change between jobs is never
noticed. `orgdb` and `maindb` do share table names (`meeting_summary`,
`notes`, `attachments`), so this is reachable, not theoretical.

### `project_fiscal_year_deletion/` — **duplicate, delete it**

Byte-identical to `data_purge/project_fiscal/`:

- all 8 `base_sql/*.sql` files (verified by md5)
- `engine/db.py` ≡ `data_purge/engine/db_pfy.py`
- `engine/runner.py` ≡ `data_purge/engine/section_runner.py`

It also has extra entry points (`run.py`, `impact_report.py`) with richer flags
(`--sections`, `--concurrency`, `--heartbeat`, `--backup-schema`, `--limit`).
**Check whether those flags exist in the `data_purge` version before deleting**
— the deletion is safe only if no capability is lost.

`run.py` here is one of the two **destructive-by-default** tools.

### `account_deletion/` — deletes whole accounts

`preview.py` (safe) and `run.py` (destructive by default, `--dry-run` to
preview). Takes `--input` (a file of accounts) or `--accounts`. Has
`--chunk-size` and `--full-counts`. `engine/engine.py` is the largest single
Python file in the estate (25 KB) and holds the deletion logic;
`deletion_manifest.py` describes what gets removed.

Overlaps conceptually with `data_purge/account/` — **whether these are two
implementations of the same thing is an open question** (see HANDOFF).

### `data_model_analysis/` — read-mostly schema analysis

`analyze.py`, `model_analysis.py`, `schema_orphan_report.py`,
`remediate_orphans.py` (writes, `--apply`), `reclassify_deviations.py`,
`gen_report.py`, `gen_er_explorer.py` (31 KB — generates an ER diagram
explorer). Operates per-schema with `--all-org-schemas` to sweep the tenants.

This is the natural source of **health metrics** for the dashboard: orphan
counts and schema deviations per tenant are exactly the numbers FR-4.5 wants.

### `reference_table_corrections/`

`correct.py` (writes, `--apply`) plus `discover.py`, `discover2.py`,
`discover3.py`, `discover_interactions.py`, `profile_resp.py`. The numbered
`discover*` files are **scratch iterations** — they should be consolidated into
one discovery tool or dropped. Confirm with the author which is current.

### `manual-rd-percent-update/` — **the JavaScript one**

The only non-Python module. Node + `pg` + `tunnel-ssh`. Three entry points:
`index.js` (42 KB, applies updates), `rollback.js`, `cleanup-backups.js`.

What it does, per its README — this is the behaviour the Python port must
preserve exactly:

1. Resolve account by `r_number` → tenant schema.
2. Resolve project by **code + fiscal year** → `project_fiscal` row.
3. Validate `rd_percent_final = rd_percent_potential_ai + rd_percent_adjustment`
   and **refuse to run** if inconsistent.
4. Recalculate QRE dollar amounts and `is_qualified = rd_percent_final > 0` from
   the project's cost basis.
5. Snapshot every row it will touch into a backup table, then write to
   `project_fiscal`, `project_resource_fiscal`, case-module tables (if the
   tenant uses them), the audit timeline, QRE adjustment history, and
   `maindb.project_fiscal_summary`.

The header comment in `index.js` cites exact file/line references into the
product's `entity-module` — **read those before porting**; they are the
specification.

This module touches money. The port needs characterisation tests, not a
line-by-line translation taken on faith.

### `sharepoint_migration/`

MSAL + Microsoft Graph. `engine/auth.py`, `client.py`, `resolve.py`.
Destructive-by-default (`--dry-run`). Config holds Azure `tenant_id`/`client_id`
(identifiers, kept deliberately) and `client_secret` (sanitized).

### `interactions_dashboard/`

`dashboard.py` (18 KB) builds and serves a **static HTML dashboard** of
interactions. Prior art for the new UI — worth reading for the metrics it
already computes before designing FR-4.5.

### `task_deletion_by_milestone/`

`base_sql/base_sql.sql` (18 KB) and nothing else. **Orphaned SQL with no
runner.** Either it is dead, or someone runs it by hand. Needs an owner
decision.

## 3. Cross-cutting problems

### 3.1 Write-gating is inconsistent — the headline safety bug

| Convention | Tools |
|---|---|
| `--apply` to write (safe) | `data_purge/{account,case,interaction,project,project_fiscal}`, `data_model_analysis/remediate_orphans`, `reference_table_corrections/correct` |
| **Writes by default**, `--dry-run` to preview | `account_deletion/run.py`, `project_fiscal_year_deletion/run.py`, `sharepoint_migration/migrate.py` |

Account deletion and fiscal-year deletion — the two most destructive tools —
are in the dangerous group. Standardising on `--apply` is FR-1.2. Note this
**changes muscle memory**: an operator who habitually types `--dry-run` will,
after the change, be passing an unknown flag. Make the old flag an explicit
error, never a silent no-op.

### 3.2 The connection layer is copy-pasted four times

`engine/db.py` is byte-identical in `account_deletion`, `data_model_analysis`,
`data_purge`, `reference_table_corrections`. It provides `load_config()` and
`ConnectionPool` with per-DB SSH tunnels, retry with backoff (4 attempts, 5s×n),
and tunnel teardown on failure. It is decent code — the problem is only that
there are four copies. It becomes `trd365-core`.

Credential resolution order in the existing pool, worth preserving:
config value → `PG_<KEY>_PASSWORD` env → interactive prompt. The Key Vault work
replaces the first, and the prompt should probably go in a service context.

### 3.3 Config duplication

Five copies of `config/db_config.json`, each with inline passwords. Replaced by
Key Vault (`docs/secrets.md`) + a per-environment config resolver.

### 3.4 No tests anywhere

Zero test files across 58 Python modules. Anything refactored needs
characterisation tests written *first*, from observed behaviour.

The ported packages carry their own (371 tests across the three so far). Because
no Claude session can reach the databases, they run against in-memory fakes with
real transaction semantics — see `packages/trd365-data-purge/tests/fakes.py`.
That proves the logic, not the SQL: **integration testing against a real
database is still outstanding**, and is the first thing to do on the VM.

## 4. Mapping to the Key Vault secrets

`db_config.json` maps 1:1 onto the environment variables already inventoried in
`scripts/secrets/manifest.mjs`:

| Config path | Env var / vault secret |
|---|---|
| `maindb.host` … `maindb.password` | `MAINDB_HOST` … `MAINDB_PASSWORD` → `maindb-host` … |
| `maindb.ssh_tunnel.*` | `MAINDB_SSH_HOST`, `MAINDB_SSH_PORT`, `MAINDB_SSH_USER`, `MAINDB_SSH_PASSWORD` |
| `orgdb.*` | `ORGDB_*` |
| `trd365ai.*` | `TRD365AI_*` (no tunnel) |

So `trd365-core`'s config loader can build the legacy `db_config` shape directly
from the vault, which keeps the migration of each utility to a one-line change.

Two data problems found while inventorying (also in `docs/secrets.md`):

- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` hold the **same 14-character
  value** with no `AKIA`/`ASIA` prefix — not working credentials.
- `MAINDB_*` and `ORGDB_*` share bastion host, port, user **and password**, and
  share a database user.

## 5. Environment access from Claude Code sessions

The sandbox **cannot reach the databases**. Verified 2026-08-17:

- `MAINDB_HOST` does not resolve (private endpoint).
- Bastion resolves to `172.203.151.166` but TCP :22 times out.
- The agent proxy refuses `CONNECT` to :22, and blocks `vault.azure.net` and
  `management.azure.com` (403).
- `psql` is installed; there is no `ssh` client.

**This is a limitation of the development sandbox, not of the product.** The
maintenance VM sits inside the VNet and reaches all three databases directly;
that is the whole reason for a dedicated VM (PRD FR-5.1).

Two consequences, and only two:

1. Code written in a Claude session is verified by unit tests and fakes.
   Integration testing happens on the VM. Do not promise verification that
   cannot happen here.
2. Nothing in the design should work around the sandbox. Injecting `connect`
   and `tunnel_factory` into `ConnectionPool` is good practice for testability;
   it is not a workaround, and the production path is the plain default.
