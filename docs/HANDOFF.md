# Handoff

**Read this first.** It is the resume point for anyone — human or another Claude
session — picking this work up cold.

Last updated: 2026-08-20, session 5.
Branch: `claude/certainti-tech-admin-y4c4ul`.

---

## 1. Sixty-second orientation

Certainti's platform maintenance is a pile of hand-run scripts. We are turning
them into a tested Python monorepo, then putting a FastAPI + React application
on top so operators invoke them safely, with audit and per-environment access
control, from a dedicated maintenance VM.

Three documents, and you want all three:

| Document | What it is for |
|---|---|
| `docs/PRD.md` | What we are building and why. Requirements, phases, settled decisions. |
| `docs/knowledge-base.md` | What the existing scripts do, and every trap in them. |
| `docs/HANDOFF.md` (this) | Where we are, what to do next, what not to break. |

Supporting: `docs/secrets.md` (Key Vault, already built and working).

## 2. What exists right now

### Done and verified

- **Web app scaffold** (`apps/web/`) — Next.js 15 + React 19 + TypeScript +
  Tailwind. Dashboard, assets, licences, people, access requests, backed by an
  in-memory store. 49 tests. This is Phase-0 work and will be **ported into the
  new SPA in Phase 3**, not kept as-is.
- **Key Vault secrets tooling** (`scripts/secrets/`) — manifest of all 33
  credentials, push/pull/check CLIs, `load.sh`. 29 tests. Fully documented in
  `docs/secrets.md`. **Not yet run against a real vault** — the sandbox cannot
  reach Azure.
- **Monorepo restructure** — `apps/web/` (app), `scripts/` (repo tooling),
  `packages/` (Python), `legacy/` (vendored source scripts).
- **CI** — `.github/workflows/ci.yml` runs Node tooling tests, the web app
  (lint/typecheck/test/build), and a Python job that installs each
  `packages/*/` and runs ruff plus that package's own pytest config.
- **`packages/trd365-core`** — environments, connections, the shared data model,
  CLI conventions, audit, model snapshots, registry. 168 tests.
- **`packages/trd365-orchestrator`** — FastAPI service, job store, approvals,
  subprocess runner, per-environment write lock, health. 71 tests.
- **`packages/trd365-data-purge`** — the engine plus `purge-account`. 132 tests.
  See its README for the port's deliberate deviations from the original.
  **Never run against a real database.**
- **`packages/trd365-analysis`** — `data-model-analysis`, the producer of the
  shared model snapshot, plus orphan detection and cross-schema deviation
  classification. 73 tests. **Never run against a real database.**

### Vendored, untouched

`legacy/trd365_maintenance/` — all 114 files of the operator's original scripts,
exactly as supplied, secrets already replaced with `CHANGE_ME`. **This is source
material. Do not edit it in place** — refactor *out* of it into `packages/`, so
the original stays available for comparison.

- **`packages/trd365-core`** — the shared foundation. 163 tests, ruff clean.
  Seven modules: `environments`, `db`, `datamodel`, `model_snapshot`, `cli`,
  `audit`, `registry`.
  See its README for usage. Highlights:
  - **`datamodel`** carries the application schema knowledge every utility
    needs (owner's requirement): `rid` primary keys, `{prefix}_rid` foreign
    keys, plural-aware parent resolution, the four primary entities, the
    cross-database `account_rid` edge, polymorphic columns, backup-table
    exclusion, tenant-schema discovery. Lifted from `model_analysis.py` so no
    utility re-derives it.
  - **`cli`** enforces the safety fix: `--env` required, `--apply` gates
    writes, `--dry-run` is a hard error that explains the change.
  - **`environments`** has all four environments; dev/qa/stage are
    placeholders that refuse to connect and name the variables that would fix
    them.
  - **`model_snapshot`** makes the discovered model a shared artefact with one
    producer and many consumers, so re-running the analysis propagates a new
    model everywhere (owner's requirement). Snapshots are per environment,
    versioned, immutable, atomically written, and diffable. `require_model`
    refuses a missing or stale model rather than falling back to an assumed
    one.

- **`packages/trd365-orchestrator`** — the Phase-2 service. 68 tests, ruff
  clean. FastAPI: job execution, per-environment write serialisation, the
  production approval workflow, cancellation that lets a utility roll back,
  health, model drift, and a read-only audit endpoint. Entry point
  `trd365_orchestrator.app:app`, which is what the systemd unit runs.
- **`infra/`** — Terraform for the maintenance VM, plus `deploy.sh` and
  `verify.sh`, and a manual-dispatch deploy workflow. **Never applied.**
  Format-checked and the cloud-init renders to valid YAML, but `terraform
  validate`/`plan` could not run here (the sandbox blocks
  `registry.terraform.io`). Needs `terraform.tfvars` filled in — blocked on
  open question 7. See `infra/README.md`.

### Not started

The utility packages themselves — the registry is empty until they land, so the
orchestrator currently has nothing to run. Phases 3 and 4 are ahead. See §4.

## 3. Decisions already taken — do not relitigate

Settled with the product owner on 2026-08-17:

1. **Monorepo, separate installable packages** (not one package, not many repos).
2. **FastAPI + React SPA as a single service** (not Next.js + separate API).
   The existing Next.js pages get ported into the SPA.
3. **Entra ID SSO + per-environment RBAC + second approver for Prod**
   destructive actions.
4. **Phase 1 (Python consolidation) first.**

Also settled earlier in the session:

5. **Azure Key Vault is the secrets source of truth**, not GitHub secrets —
   Actions secrets are readable only inside workflow runs, so they cannot serve
   sessions, laptops, or the VM.
6. **The Azure service principal stays out of the vault** it unlocks; it is the
   one bootstrap credential per context.

Settled 2026-08-20:

7. **This application is independent of the existing estate.** It creates its
   own resource group, network, vault and host; it modifies no existing Azure
   resource, no existing repository, and no database schema. It *reads and
   writes application data* in the platform's databases — that is its entire
   purpose — over the public endpoints the operator scripts already use. The
   product repositories are attached for understanding only; never open a PR
   against one.

## 4. Next task — start here

The producer/consumer loop is closed: `data-model-analysis --apply` publishes a
snapshot and `purge-account --apply` accepts it. Both are discovered by the
service through their entry points and invocable through the API.

### Step 1 — `remediate_orphans`

The destructive counterpart to the analysis, and the natural next utility: the
analysis now finds orphan rows and nothing removes them.

- It should **reuse `trd365_data_purge.engine`** rather than repeat it. The
  legacy tool has its own backup/delete/validate loop with the same shape —
  back up and delete in one transaction, verify only the intended rows went —
  and there is no reason for two of those.
- Its input is the analysis output: scope each delete to the captured orphan
  rids, exactly as the legacy tool does.
- `Impact.DESTRUCTIVE`, dry run by default, and it must `require_model()`.

### Step 2 — the remaining purge entities

**`case` and `interaction` are done** (`purge-case`, `purge-interaction`, both
registered). They were cheap, as predicted: pure subtree deletes, so the shared
engine did all the work and each entity is a manifest, a scoper and an entry
point. What they share now lives in `trd365_data_purge/subtree.py`.

The one thing to know about them: `follow_foreign_keys` is a per-entity decision,
not a default. A case follows them; an interaction does not, because
`chat_sessions` carries an `interaction_rid` it does not own and any rule general
enough to reach FK-linked tables reaches that one too. Three tests hold the line,
and the guard was verified by adding `chat_sessions` to the manifest and watching
two of them fail with two rows deleted.

**`project` and `project_fiscal` remain, and they are a different animal.** They
do not enumerate rows; they run the vendor's eight PL/pgSQL SECTION files, which
delete *and recompute the financial aggregates* that survive — account fiscal
totals, project rollups, QRE dollars. `trd365_data_purge/sections.py` is that
runner and is built and tested (32 tests); the eight SQL files moved across
unchanged. What is left is the entity layer: resolve a project fiscal, compute
`is_last_fiscal`, iterate a project's fiscals, and report.

#### The thing to know before touching those two

**The vendor SQL is not a template.** Its FILL IN block contains real production
identifiers — tenant schema `trd365_01379`, plus live account, project and
project-fiscal rids, 23 occurrences across the eight files. They are not
placeholders like `<schema>`; they are values that resolve. A substitution that
fails to match therefore does not error and does not no-op — the section runs,
succeeds, and deletes a fiscal year belonging to whoever those identifiers point
at.

The legacy runner checked that every value it was *given* got used. It did not
check that every value in the *file* got replaced, and that is the direction the
danger runs in: a renamed declaration is silent. `sections.prepare()` now refuses
to return SQL containing any identifier-shaped literal it did not put there,
anywhere in the file. Do not relax that check.

**A dry run of these sections is not free.** Everywhere else in this package a dry
run counts rows without touching them. Here it *executes* the deletes and the
recompute inside a transaction that is then discarded — same locks, same work,
result thrown away. It is the only way to dry-run SQL that recomputes, and an
operator should be told so before running one against production.

#### The legacy flags: what happens to each

Decided rather than dropped silently, as the earlier note asked.

| Flag | Decision |
|---|---|
| `--sections` | **Keep.** Re-running just the audit sections (4, 5, 8) after a failure is genuinely useful. |
| `--heartbeat` | **Keep.** A `DO` block emits nothing for minutes; without it an operator cannot tell slow from hung. Implemented as `on_progress` in `sections.execute`. |
| `--backup-schema` | **Keep.** Needed to resume into the schema an earlier run created. |
| `--verbose` | **Keep.** Full NOTICE output rather than the summary lines. |
| `--last-fiscal` / `--not-last-fiscal` | **Keep.** Decides whether the project row itself goes. |
| `--concurrency` | **Drop.** It parallelised across projects in a CSV batch. One invocation is one target here, and running projects concurrently while they recompute *shared* account-level aggregates is a correctness hazard, not a feature. |
| `--limit`, `--projects`, `--input` | **Drop.** CSV-batch flags. Batching is the orchestrator's job, where each target is a job with its own approval, log and outcome — the same decision already taken for the account purge. |

### Step 3 — validate the conventions against the live schema **on the VM**

`trd365_core.datamodel`'s conventions — `rid` primary keys, `_rid` foreign keys,
the `trd365` main schema — were inferred from reading the maintenance scripts and
have never been checked against a database. That is the largest standing
assumption in this repository.

`tools/extract_reference_schema.py --env <env> --schema trd365` reads the live
catalog with the same query the analysis uses and writes a small fixture of table
and column names, which a test can then assert against.

**Take the DDL from the database, not from a checked-in dump.** The owner was
explicit about this (2026-08-20), and it is right: `rdcredits_platform_db_scripts`
holds a `pg_dump` that reflects what someone intended at some point, and the two
drift. The tool has a `--from-dump` mode for reading one you already have, and it
stamps `_authoritative: false` on the output so nothing downstream mistakes it
for the real thing. **This step needs database access, so it runs on the VM.**

### Step 4 — the remaining modules: decided

**Eight utilities are registered and this list is closed.** What is left in
`legacy/` is there because a decision was taken, not because nobody looked.

| Legacy module | Decision |
|---|---|
| `data_purge/{account,case,interaction,project,project_fiscal}` | **Ported.** `purge-account`, `purge-case`, `purge-interaction`, `purge-project`, `purge-project-fiscal`. |
| `data_model_analysis` | **Ported** as `trd365-analysis` / `data-model-analysis`. |
| `manual-rd-percent-update` | **Ported** as `trd365-rd-percent` / `rd-percent-update`, with two of its money bugs fixed — see below. |
| `task_deletion_by_milestone` | **Ported** as `purge-milestone-tasks`. It was 18 KB of SQL with no runner; `sections.py` was already a runner, so the SQL moved unchanged and got driven properly. |
| `account_deletion` | **Kept**, alongside `purge-account`. The owner deferred the decision; `PURGE_ACCOUNT.supersedes` records the relationship so the UI can show it without either being deleted. |
| `project_fiscal_year_deletion` | **Superseded.** Its `base_sql/` is byte-identical to the ported copy (`diff -rq`), so it is a CSV batch runner over the same SQL. `PURGE_PROJECT.supersedes` records it. Safe to delete. |
| `reference_table_corrections` | **Not ported.** `correct.py` describes itself as "the reusable plumbing only" and the three `discover*.py` files are scratch exploration. There is no finished tool here to port — only connection handling the core package already has. |
| `sharepoint_migration` | **Not ported.** Cross-tenant Microsoft Graph file copying between two Azure AD tenants. Nothing to do with the database estate this platform administers, and untestable without two sets of live tenant credentials. If it is still needed it belongs somewhere else. |
| `interactions_dashboard` | **Not ported, worth revisiting.** A read-only reporting tool that renders interaction metrics as a self-contained HTML page. Genuinely useful and genuinely safe, but it is *reporting*, and the console is now the place reporting belongs — port it as a view rather than as a utility. |
| `schema_orphan_report` | **Folded in.** The orphan sweep in `trd365-analysis` covers it; the main-side check it added is in `orphans.py`. |

### What porting the R&D percentage tool found

Two disagreements with the application, both overstating money, both now fixed
and pinned as tests. Read `packages/trd365-rd-percent/src/trd365_rd_percent/
calculation.py` before touching that utility.

1. **The sub-contractor cap was missing.** The application caps sub-contractor QRE
   at the project's jurisdiction percentage (TRDV2-451). The legacy tool omitted
   the factor entirely, writing ~1/0.65 — half again — too much at the default cap.
2. **`qre_final` came from the wrong column.** The application sums the three
   components it just computed; the legacy tool used `total_cost_prj`.

### And what porting the SECTION SQL found

**The vendor SQL is not a template.** Both families of section files ship with real
production identifiers in the variables a human was told to edit — tenant
`trd365_01379` and live rids in the project sections, tenant `trd365_00414` and a
live case rid in the milestone script. A substitution that fails to match does not
error: it runs against whoever those identifiers belong to. `sections.prepare()`
refuses to return SQL where any identifier-shaped literal it did not put there
survives, scanning with comments stripped so a documented example is not a false
alarm. **Do not relax that check.**

### Step 5 — flip the three destructive-by-default tools

`account_deletion/run.py`, `project_fiscal_year_deletion/run.py` and
`sharepoint_migration/migrate.py` currently write by default. Once on
`trd365_core.cli` they invert automatically, and `--dry-run` becomes the hard
error that explains the change. Announce this to operators before it ships.

## 5. Things that will bite you

- **A Claude session cannot reach the databases; the VM can.** Private
  endpoints do not resolve from the sandbox and the proxy blocks TCP :22 and
  `vault.azure.net`. That is a development-sandbox limit, not a product one —
  the maintenance VM sits in the VNet and connects directly. So: verify with
  unit tests and fakes here, integration-test on the VM, and do not design
  around the sandbox.
- **`legacy/` is reference, not a working tree.** Refactor out of it.
- **The purge SQL is data, not code to rewrite.** `base_sql/*.sql` files encode
  foreign-key deletion order. Move them unchanged. `DELETION_ORDER.md` in each
  purge module is the most valuable documentation in the estate.
- **`--dry-run` → `--apply` changes muscle memory.** Make the old flag an
  explicit error with a clear message. A silent no-op here deletes production
  data.
- **`manual-rd-percent-update` touches financial calculations.** Its
  `index.js` header cites exact file/line references into the product's
  `entity-module` — that is the specification. Read it before porting.
- **Only Prod database details are known.** Dev/QA/Stage connections have not
  been discovered yet (§6).
- **Secrets:** all 33 live in the Claude Code environment config today. Key
  Vault tooling is built but the migration has not been run. Until it is, the
  vault is not yet the source of truth.
- **A new environment must be analysed before it can be written to.**
  `data-model-analysis --env X --apply` publishes the snapshot that every
  destructive utility requires. Until that has run against X, dry runs work
  there and `--apply` refuses. That is the design, not a gap.
- **The environment's network policy is what blocks deployment**, and it is a
  setting, not a limitation of the code. See §10 for the host-by-host evidence
  and the exact allowlist that fixes it.
- **No preview means no deployment.** `tools/preview/` renders a page from real
  utility output so the owner can see the system without one existing. It is
  generated, never hand-written, and it states plainly that nothing has been
  deployed or connected to a database. Regenerate it after any change that alters
  what the utilities produce.
- **The product repos are attached to this session and answer several open
  questions.** `certainti-ai/rdcredits_platform_iac` and
  `certainti-ai/rdcredits_platform_db_scripts` are cloned under `/workspace/`;
  more can be attached with `add_repo`. See §9.
- **Utility packages are found by entry point**, not by a list in the service.
  A new package that forgets its `[project.entry-points."trd365.utilities"]`
  block installs cleanly, passes its own tests, and is simply invisible in the
  API. `create_app()` reports what it loaded at `GET /`.

## 6. Open questions — need the product owner

Ask these before building past them:

1. **Dev/QA/Stage database connections.** *Owner will supply later.* Until then
   they resolve to placeholders that refuse to connect. Nothing is blocked —
   supply `TRD365_DEV_MAINDB_HOST` and friends and they light up with no code
   change. `trd365_core.configuration_status()` reports which are ready.
2. ~~**`account_deletion/` vs `data_purge/account/`.**~~ **Decided:** keep both
   for now, decision deferred. Record the relationship with
   `Utility.supersedes` rather than deleting either.
3. **`reference_table_corrections/discover{,2,3}.py`.** Three scratch
   iterations. Which is authoritative?
4. **`task_deletion_by_milestone/`.** 18 KB of SQL with no runner. Dead, or run
   by hand? Does it need a Python wrapper?
5. **`project_fiscal_year_deletion` extra flags** — are they still needed?
   (Blocks the de-duplication in §4.2.)
6. **AWS credentials are broken** — `AWS_ACCESS_KEY_ID` and
   `AWS_SECRET_ACCESS_KEY` hold the same 14-character value with no `AKIA`
   prefix. What were they for? Fix or drop.
7. ~~**Maintenance VM — which subnet?**~~ **Closed 2026-08-20, and the question
   dissolved.** The owner's constraint is that this application runs
   independently, with no link to and no change to existing infrastructure. That
   turns out to be the *simpler* design, not a compromise: every database is
   already reachable over a public endpoint — `maindb`/`orgdb` through the
   bastion tunnel, `trd365ai` directly — which is how the operator scripts
   connect from a laptop today. So the stack creates its own VNet and subnet,
   peers with nothing, and needs only outbound internet. `subnet_id` is now an
   opt-out, not a requirement, and the eastus/centralus disagreement is a
   latency choice rather than a peering constraint. The Terraform identity still
   needs User Access Administrator alongside Contributor, since two RBAC role
   assignments are created. See `infra/terraform/PREFLIGHT.md`.
8. ~~**Which platform workspace is Stage?**~~ **Answered 2026-08-20: `preprod`.**
   Recorded as `Environment.platform_workspace` in `trd365_core.environments`,
   with a test, rather than only in prose — anything naming a platform resource
   has to translate, and Dev is `development` there too.
9. **Entra ID** — which tenant and app registration should the SPA use, and
   which groups map to `viewer`/`operator`/`approver`/`admin`?

## 7. Working agreements for this repo

- Branch: `claude/certainti-tech-admin-y4c4ul`. Do not push elsewhere without
  asking.
- No PR has been opened. The owner has not asked for one.
- Keep CI green. It runs on every push.
- Never commit a real secret. `.gitignore` covers `.env*`; `scripts/secrets/`
  refuses to write into non-ignored paths.
- Update this file at the end of a working session. It is the contract with
  whoever comes next.

## 8. Session log

### Session 1 — 2026-08-17

Built the web app scaffold; built the Key Vault secrets tooling after
establishing that GitHub secrets cannot serve the stated goal; reviewed all 114
maintenance scripts; agreed the four architecture decisions in §3; restructured
into a monorepo and vendored the legacy scripts.

Two bugs found and fixed in the scaffold, both caught by driving the real UI
rather than trusting the build: a submit button's `name`/`value` was not
reaching the server action, and `lib/store.ts` was instantiated twice because
Next compiles server actions into a separate bundle from pages.

Phase 1 not started — `packages/` is empty.

### Session 2 — 2026-08-17

Owner directives: placeholder credentials for dev/qa/stage (real ones later),
keep both account-deletion implementations, and **every script must share the
application data model that the data-model-analysis script derives**.

Built `packages/trd365-core` — 128 tests, ruff clean. The third directive drove
the design: `datamodel.py` lifts the schema conventions out of
`model_analysis.py` into tested shared code, so no utility re-derives them.
`environments.py` carries all four environments with dev/qa/stage as
placeholders that refuse to connect rather than failing obscurely. `cli.py`
implements the `--apply` reversal with `--dry-run` as a hard error.

One real bug caught by the tests: `confirm_production` had `stream=sys.stderr`
as a default argument, which binds stderr at import time and breaks redirection
and capture. Resolved inside the function instead.

Owner then confirmed the app deploys to a VM with direct database access, and
required that re-running the data-model analysis propagate the new model to the
other scripts. Added `model_snapshot`: one producer, many consumers, versioned
immutable snapshots per environment, atomic writes with the `latest` pointer
moved last, diffing for drift, and a hard refusal on missing or stale models.
163 tests.

Owner asked whether the VM could be spun up and the application deployed. No,
on two independent grounds, both verified: the sandbox blocks
`management.azure.com` and `graph.microsoft.com` so no VM can be created from a
session, and there is nothing deployable yet — `trd365-core` is a library with
no entry point and the Phase-2 service does not exist. Wrote `infra/` instead so
the VM can be stood up by hand, which is worth doing early: it is the only host
that can reach the databases, and `verify.sh` proves that before any application
depends on it.

### Session 3 — 2026-08-17

Built Phase 2, `packages/trd365-orchestrator`. Three bugs found by testing
rather than review: sync FastAPI endpoints run in a threadpool with no event
loop, so `asyncio.create_task` raised — the endpoints that schedule work are now
`async def`; `pytest packages/` from the repo root silently ignores each
package's own config, so CI now runs pytest per package; and `AuditedRun` needed
explicit `mark_cancelled`/`mark_failed` because signalling outcome by raising
`KeyboardInterrupt` would have escaped the task as a `BaseException`.

**Resume at §4 — build `packages/trd365-data-purge`.** The orchestrator's
registry is empty until utility packages register themselves, so nothing is
runnable through the API yet.

### Session 4 — 2026-08-20

Built `packages/trd365-data-purge`: the entity-agnostic engine plus
`purge-account`, 132 tests, ruff clean. It is a **port, not a rewrite** — the
legacy engine was already the right shape and the manifest is vendor-derived
data, reproduced verbatim and guarded by a test that diffs it against the legacy
file.

Four things worth knowing:

- **A legacy cache bug is fixed in the port.** `engine/core.py` cached column and
  foreign-key metadata in module-level dicts keyed by `(schema, table)` only, and
  `clear_caches()` was never called anywhere in the tree. Harmless in a one-shot
  CLI; under the long-running orchestrator it means one database's metadata can
  be served for another sharing a table name. The cache is now keyed by database
  and scoped to a single run. **The legacy file still has the bug** — it is
  reference material and was deliberately not edited.
- **Utilities are discovered, not listed.** `trd365_core.registry` gained
  `load_installed_utilities()`, which loads the `trd365.utilities` entry-point
  group; `create_app()` calls it. Adding a utility means installing a package,
  not editing the service. `Registry.register` is now a no-op for an identical
  descriptor (a package registers on import *and* advertises an entry point) and
  still refuses a *different* utility under an existing id.
- **A production run through the API would have hung forever.**
  `confirm_production` prompts on stdin, which a subprocess does not have. It now
  refuses without a terminal instead of hanging, `--yes` moved into the shared
  `build_parser`, and `build_argv` passes it for a production apply because the
  service has already required a second approver. Also fixed: `input_fn=input` as
  a default argument bound the builtin at import time — the same class of bug as
  the `stream=sys.stderr` default fixed in session 2.
- **`--apply` requires a data-model snapshot**, and nothing produces one yet.
  That is why `data_model_analysis` is now Step 1 rather than fourth in the
  queue.

**Resume at §4 Step 1 — port `data_model_analysis`.**

---

## 9. The product repositories

This session can attach any repo in the `certainti-ai` org with `add_repo`.
Two are already cloned; a third is wanted and not yet pulled.

### `rdcredits_platform_iac` — `/workspace/rdcredits_platform_iac`

The platform's own Terraform, and it answers the question that has been blocking
`infra/terraform/`: **which VNet the maintenance VM belongs in.**

- `modified_network.tf` defines one VNet per Terraform workspace,
  `<workspace>-thinkrd365-vnet`, in resource group
  `thinkrd365_assist_resource_group`, with `/24` subnets carved out of
  `local.vnet_cidr` — etl (.1), backend (.2), redis (.3), appgw (.4).
- Postgres sits in a **separate** VNet, `<workspace>-thinkrd365-vnet-pg`, with
  `postgres_subnet` and private DNS zones (`new_rds_dns_zone.tf`); the two are
  joined in `new_vnet-peering.tf`. That is why the databases are unreachable
  from anywhere outside these VNets, and why the maintenance VM has to live in
  one of them.
- The workspaces are `development`, `qa`, `preprod`, `prod` — so our **Stage
  maps to `preprod`**, which is worth confirming before wiring Stage credentials.
- `local.location = "eastus"`. Our Terraform defaults to `centralus`, inferred
  from the production database hostnames. **These disagree and it matters** —
  a VM in the wrong region cannot peer cheaply and adds latency to every query.
  Resolve before applying.

**We do not touch any of this.** The owner's constraint (2026-08-20) is that the
maintenance application runs independently, changing nothing that exists. Our
Terraform therefore builds its own network and reaches the databases over their
public endpoints. This repo is read here for *understanding* — what the estate
looks like, what a workspace is called, why the databases are unreachable from
an arbitrary network — and for nothing else. Do not open a PR against it.

### `rdcredits_platform_db_scripts` — `/workspace/rdcredits_platform_db_scripts`

Flyway-style DDL: `baseline/`, `migrations/`, `seed/`, 50 SQL files, versioned
`V4.1.0` → `V5.0.0`.

This is what makes it possible to **validate `trd365_core.datamodel` against the
real schema without a database** — the standing gap that nothing built so far
has touched one. A test that parses the baseline DDL and asserts the
conventions (`rid` primary keys, `_rid` foreign keys, the `trd365` main schema)
would turn assumptions into checks. Worth doing before the VM exists.

### `rdcredits_platform_be` — not yet cloned

Contains `entity-module`, which the `manual-rd-percent-update` JS tool cites by
file and line. That is the specification for the port (§4 Step 3.6). Attach it
when that port starts, not before — it is large and the port is not next.

### Session 5 — 2026-08-20

Built `packages/trd365-analysis` — `data-model-analysis`, the producer of the
shared model snapshot. 73 tests, ruff clean. **The producer/consumer loop is
closed**: verified end to end against fakes that `--apply` publishes a snapshot
and `purge-account --apply` then picks up that exact fingerprint and proceeds,
where before it refused.

- **A whole legacy script was folded in rather than ported.**
  `reclassify_deviations.py` existed because the per-schema classifier mislabels
  a shared entity as a typo when it appears in one or two tables per schema.
  That is a scope problem, not a post-processing one: a snapshot already holds
  every schema, so the classification now runs across the whole snapshot before
  it is saved. Consumers read the good answer and there is no second script to
  remember. It counts distinct `(schema, table)` pairs, not rows — forty tenants
  carrying the same table is one fact repeated, and counting it forty times
  would make every rare prefix look global as the estate grows.
- **The global-lookup exclusion was carried over verbatim.** Some parent tables
  are empty per tenant because the rows live in a master in main
  (`interaction_type`), so every child looks orphaned. Without the exclusion,
  `--all-entities` reports thousands of orphans that are all fine. The original
  found this the hard way; there was no reason to find it again.
- **`--apply` publishes rather than writes.** The utility is read-only against
  the databases, but replacing the model every other tool trusts is
  consequential, so it takes the same gate. A run whose orphan scan broke still
  publishes the model and exits 1: the structure is complete and consumers need
  it, but reporting the orphan counts as fact would be a lie.
- **Stage maps to `preprod`** on the platform (owner, this session), and Dev to
  `development`. Recorded as `Environment.platform_workspace` with a test.

**Resume at §4 Step 1 — `remediate_orphans`**, reusing the purge engine rather
than repeating it. Step 3 (validating the datamodel conventions against the real
DDL, now that the repo is attached) is cheap and worth doing early.

---

## 10. The deployment blocker, and how it was resolved

Terraform cannot reach Azure from a Claude session in this project's environment.
The code is not the problem: `infra/terraform/` needs no required inputs and
creates everything it uses.

Cloud environments carry a **Network access** level. This one is on **Trusted**,
whose allowlist matches *exact hosts* unless an entry begins `*.`. That accounts
for every result observed on 2026-08-20:

| Host | In the Trusted list? | Observed |
|---|---|---|
| `login.microsoftonline.com` | yes, via `*.microsoftonline.com` | 302 — a service-principal token was obtained |
| `releases.hashicorp.com` | yes | the Terraform binary downloaded |
| `management.azure.com` | **no** — only `azure.com`, `portal.azure.com`, `dev.azure.com` | 403 at CONNECT |
| `registry.terraform.io` | **no** | 403 — cannot download the azurerm provider |
| `checkpoint-api.hashicorp.com` | **no** — `hashicorp.com` does not cover subdomains | 403 |
| `vault.azure.net` | **no** | 403 — the secrets tooling cannot reach the vault |

So a token can be obtained and then used against nothing.

### What the sibling session does — three theories, all wrong

Deployment has been misdiagnosed three times. Recording all three so nobody
spends a fourth round on it.

1. *"Its environment permits Azure and this one does not."* **Disproved
   2026-08-21:** the owner read the field. `incentiwise-beta` was on **Trusted**,
   the same level as this environment.
2. *"A human ran `tofu apply` locally."* Its `deploy/azure/README.md` does
   document `az login` + `tofu apply` as a human step — but its HANDOFF records
   ARM credentials "injected as env vars", a subscription "verified via ARM
   REST", and a guardrail deliberately changed to **allow agent IaC apply** for
   non-prod. The owner also says they did not run it.
3. *"Its sandbox had freer egress."* Its own journal says the opposite:
   `api.github.com` proxy-blocked, Maven Central not allowlisted, web search 403,
   container registry pulls 403. It was **more** restricted than this one.

What remains is measurable and what is left is not:

**Measured here, repeatably.** `tools/check_azure_reachability.sh` mints a valid
1,872-character token from the service principal in `ARM_*`, then fails to reach
ARM with it — `curl` exit 56, no HTTP response. The proxy's own words:

```
management.azure.com:443   gateway answered 403 to CONNECT (policy denial …)
registry.terraform.io:443  gateway answered 403 to CONNECT
vault.azure.net:443        gateway answered 403 to CONNECT
graph.microsoft.com:443    gateway answered 403 to CONNECT
```

Good credentials, no route.

**Unexplained, and not worth more effort.** Both environments were on Trusted,
yet one has a HANDOFF claiming a live VM at `20.228.194.61`. The likeliest
reconciliation is that the Trusted allowlist itself changed between 2026-08-17
and now — it is Anthropic's list, not ours, and `azure.com` appearing in it
without a wildcard is exactly the kind of entry that gets tightened. That cannot
be confirmed from here, the claim cannot be verified without ARM access, and
nothing about this project depends on the answer. **Let it go.**

### The change that was made

The owner set this environment's **Network access** to **Full** on 2026-08-21.

Full permits any domain. A narrower **Custom** list would be preferable for a
host that can purge production databases — the list is in the next section, and
switching to it later costs nothing — but Full unblocks the work now, and that
was the owner's call to make.

**The policy is enforced live at the gateway, and takes effect without a new
session.** This was measured twice, and the first reading was misleading:

| When | `example.com` | ARM | Level in force |
|---|---|---|---|
| After the change, first check | blocked | 403 | Trusted |
| After the change, second check — **same container** | reachable | **200, 51 resource groups** | **Full** |

Nothing was restarted between those two readings. So the earlier conclusion —
that a session captures its environment's configuration at creation and a new
session is required — was **wrong**; the change simply had not propagated to the
gateway yet when first tested. Give it a few minutes, then re-check. Do not start
a new session on the strength of one failed reading.

`tools/check_azure_reachability.sh` reports which level is actually in force, by
asking for a domain that only Full permits. Run it before concluding anything:
"the dialog says Full" and "this session is on Full" are different claims, and
only the second one matters.

### The narrower alternative, if you want it later

Full is set and works. If you would rather this host reach only what it needs,
set **Network access** to **Custom** instead.

At [claude.ai/code](https://claude.ai/code), open the environment selector — the
cloud icon showing the environment name, in the row above the message box; there
is no settings URL for it. Hover **certainti_tech_administration**, select the
settings icon, set **Network access** to **Custom**, and put this in **Allowed
domains**, one host per line:

```
management.azure.com
*.vault.azure.net
graph.microsoft.com
registry.terraform.io
checkpoint-api.hashicorp.com
*.blob.core.windows.net
*.frame.claudeusercontent.com
```

Then tick **Also include default list of common package managers** — without it,
npm, pip and GitHub stop working.

Why each: ARM is the entire API the azurerm provider talks to; the vault data
plane is what `scripts/secrets/` reads and writes; Microsoft Graph is needed for
role assignments and any Entra ID group work; the registry is where providers
come from; the checkpoint host is only Terraform's version check, and setting
`CHECKPOINT_DISABLE=1` avoids needing it; blob storage matters only if Terraform
state moves to an Azure backend; and the last is required for a session to read
published artifacts, such as the preview page.

**Custom, not Full.** This host can purge production databases. An explicit list
is auditable; Full is not.

**Start a new session afterwards.** An environment's configuration is applied
when a session's VM is provisioned, and a running session keeps what it started
with. A fresh container inside an existing session is not enough — confirmed on
2026-08-20, when a 31-minute-old container was still refused.

On a Team or Enterprise plan the same fields exist for organization-shared
environments, under **Cloud environments** in
[admin settings](https://claude.ai/admin-settings).

---

## 11. Deploying, end to end

### Step 1 — apply the Terraform, once

With **Full** network access (§10) a session can do this itself. Check first:

```bash
bash tools/check_azure_reachability.sh
```

Proceed only if it says *"This session CAN deploy"*.

**State comes first.** `backend "azurerm" {}` is deliberately partial — this
configuration generates the VM's SSH private key and writes it to Key Vault, so
the state file is itself a secret (SECURITY.md), and local state in an ephemeral
container is worse than inconvenient: when the container is reclaimed the VM still
exists and nothing can manage or destroy it. That is how infrastructure gets
orphaned and billed indefinitely.

```bash
bash infra/terraform/bootstrap-state.sh
```

It creates a resource group, a private storage account with blob versioning, and
a container, talking to ARM directly with the service principal — something has
to make the state store before Terraform can keep state there. Idempotent. It
prints the `terraform init` line and the access key to export.

```bash
cd infra/terraform
export ARM_ACCESS_KEY='<from the bootstrap output>'
terraform init \
  -backend-config="resource_group_name=trd365-tfstate" \
  -backend-config="storage_account_name=<from the bootstrap output>" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=maintenance-vm.tfstate"
terraform plan     # no variables are required
```

**Read the plan before applying.** It is the last point at which nothing has been
created, and it is the review a human should actually do — roughly 19 resources,
all new, none touching anything that already exists.

Note that `terraform apply` creates real, billed infrastructure, and a session
running in auto mode may have that call refused by the harness. That is the guard
working. Approve it deliberately rather than looking for a way around it.

```bash
terraform apply
terraform output next_steps
```

The stack creates its own resource group, virtual network, subnet, NSG, Key
Vault, managed identity, SSH key and VM. `ARM_CLIENT_ID` / `ARM_CLIENT_SECRET` /
`ARM_TENANT_ID` / `ARM_SUBSCRIPTION_ID` are already in the environment, so the
azurerm provider authenticates without `az login` — which matters, because
`az login` is interactive and no session can complete it.

Two things to know before applying:

- **Quota bites.** The sibling project found `Dsv5` quota was **0** in its
  region and had to fall back to `Dsv3`. `vm_size` here defaults to
  `Standard_D2s_v3` for that reason. If apply fails on quota, that is why.
- **`prevent_destroy` guards the vault and the resource group.** Deliberate: a
  resource-group destroy takes the vault's secrets with it. Removing the guard
  should be a conscious act.
- **One step needs the Key Vault *data* plane.** `ssh.tf` writes the generated
  private key to the vault, which talks to `<vault>.vault.azure.net`, not ARM.
  Two things can make that specific resource fail on a first apply: the host not
  being allowed by the network policy, and Azure's own RBAC propagation lag
  between the role assignment and data-plane access. Both look the same. Re-run
  `terraform apply` — everything else is already created and the run is
  idempotent — and only investigate if it fails twice.

### Step 2 — the VM keeps itself current

`trd365-deploy.timer` fires every three hours (`auto_deploy_schedule`, a systemd
`OnCalendar` expression; `""` disables it). Each run:

1. fetches the deployed branch and hard-resets to it — the VM is a deployment
   target, so local divergence is corruption, not work;
2. installs every package;
3. **runs the full test suite**;
4. restarts the service only if the suite passed.

If the suite fails, or the service does not come up, the checkout is rolled back
to the revision that was serving and the running service is never touched. That
gate is the point: this host holds credentials that can delete production data,
and an unattended deploy means code arrives with nobody watching. A VM sitting on
last week's good commit is a nuisance; a VM running a broken build against
production is not.

To deploy immediately rather than waiting for the timer:

```bash
az vm run-command invoke -g <rg> -n <vm> --command-id RunShellScript \
  --scripts 'sudo -u trd365 /opt/trd365/deploy.sh'
```

`--skip-tests` forces a deploy past the gate. It exists for the case where the
suite is broken and you know why; it is not a normal option.

### Step 3 — prove it can see the databases

```bash
sudo -u trd365 /opt/trd365/verify.sh
```

Read-only. It checks the managed identity can read the vault and that all three
databases answer. This is the first moment anything in this project touches a
real database, so expect to learn something here.

### Confirming it, either way

```bash
bash tools/check_azure_reachability.sh
```

Read-only. It distinguishes the two failures that have been confused for each
other all along: a bad credential (the token step fails) from no route (the token
succeeds and ARM does not answer). If it ends with *"This session CAN deploy"*,
then `cd infra/terraform && terraform init && terraform apply` — no variables
required.

### Session 6 — 2026-08-21

Deployment. Three wrong diagnoses, then a measurement (§10). The owner read the
sibling environment's setting and it was **Trusted**, the same as this one, which
disproved the last surviving theory; they then set this environment to **Full**.
Re-tested immediately: still 403, because an environment's configuration applies
when a session's VM is provisioned. **A new session can deploy. This one cannot.**

Built this session:

- `tools/check_azure_reachability.sh` — mints a token from the service principal
  and then uses it against ARM, because those two steps fail for unrelated
  reasons with unrelated fixes. Run it before anything else.
- **Self-updating deploys.** `deploy.sh` was idempotent but nothing ever invoked
  it. `trd365-deploy.timer` now runs it every three hours, gated on the full test
  suite, rolling the checkout back if the suite fails or the service does not come
  up. That gate is load-bearing: the deploy is unattended and the host holds
  credentials that can delete production data.
- **The Terraform is self-contained** — its own VNet and subnet, no required
  variables, nothing existing touched.
- `tools/check_terraform.py`, because `terraform validate` needs a registry no
  session could reach. Catches the cloud-init input that `templatefile()` forgets
  to supply, which otherwise fails at apply time with resources already created.
- A real engine defect: absent tables were reported as "UNSCOPED — needs manual
  review", about eighty per run, burying the few that genuinely need a human.
- `tools/preview/` and a published preview page, rendered from real utility output.

**Resume at §11 — deploy.** It unblocks everything that has been waiting on a
real database: the live-schema extraction (§4 Step 3), the first
`data-model-analysis --apply`, and integration testing at all.

---

## 12. The deployment, as it actually happened (2026-08-21)

**The VM is live and serving.** `trd365-maint-vm`, private IP `10.80.1.4`, in
`trd365-maintenance` / `centralus`, subscription `b8e81c74…` "Certainti.Ai -
Platform". Nothing pre-existing was touched.

```
GET / ->  {"service":"trd365 orchestrator",
           "environments":["dev","qa","stage","prod"],
           "utilities":2,"discovered":["analysis","data-purge"]}
GET /api/health -> 200
```

Entry-point discovery works in production: the service found both utility
packages without a list naming them. The deploy ran the **full test suite on the
VM** and only then restarted the service. `trd365-deploy.timer` is enabled, next
run three-hourly.

State lives in `trd365-tfstate` / `trd365tfstated82a2003` / `tfstate`, blob
versioning on. The account key printed during bootstrap was rotated afterwards.

### Network reachability, measured from the VM

The thing no Claude session could ever test:

| Target | Result |
|---|---|
| IMDS managed identity | **200** — the identity works |
| SSH bastion `172.203.151.166:22` | **open** |
| `trd365ai` `4.246.251.140:5432` | **open** |
| `maindb` private endpoint, DNS | does not resolve — expected, hence the bastion |

**So the path to every database exists from this host.** What is missing is
credentials: `configuration_status` reports every database unconfigured in all
four environments, because no passwords have been supplied anywhere yet. That is
the Key Vault's job, and it is the one thing still blocked.

### RBAC and the vault — resolved 2026-08-21

The first apply left three resources uncreated, all failing on
`Microsoft.Authorization/roleAssignments/write`: the service principal held
**Contributor**, which by design cannot create role assignments. The owner
granted **User Access Administrator**, and the remaining apply completed.

All 16 resources now exist. Verified end to end **from the VM**, using its own
managed identity (`395de63d-…`) against the vault data plane:

```
IMDS token for vault.azure.net   2048 chars
GET /secrets                     200  ['maintenance-vm-ssh-private-key']
GET /secrets/maintenance-vm-…    200
```

So the credential chain works: VM -> managed identity -> Key Vault -> secret.

**The vault now holds the real database credentials.** `scripts/secrets/` ran
against a live vault for the first time and wrote 26 secrets: the full maindb,
orgdb and trd365ai sets. The Azure service principal is excluded by design — it
authenticates to the vault, so it cannot live inside it.

Two things were deliberately held back:

- **`aws-*`.** `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` hash to the
  *identical* digest, so both variables hold the same value and at least one is
  wrong. This is open question 6 in §6, now with evidence. Pushing a
  known-broken secret is worse than leaving the slot empty.
- **`tf-var-repo-pat`.** The repository is public, so nothing needs it.

### The databases are reachable — 2026-08-21

`trd365_core.vault` closed the last link, and `verify.sh` on the VM now reports:

```
== managed identity can read the vault ==
  ok    IMDS token
== database reachability (prod) ==
[tunnel] maindb: 127.0.0.1:40637 -> prod-…-pvt-main.postgres.database.azure.com:5432
  ok    maindb: thinkrd365_pvt_main as adminUser
[tunnel] orgdb: 127.0.0.1:34179 -> prod-…-pvt-org.postgres.database.azure.com:5432
  ok    orgdb: thinkrd365_pvt_org as adminUser
  ok    trd365ai: trd365ai as aiadmin

All checks passed.
```

**That is the first real database connection this project has ever made.** SSH
tunnels through the bastion, credentials from Key Vault via the managed identity,
and the connection pool — all working, on a host built from this repository.

Credential readiness resolved from the vault:

```
  dev    maindb=--  orgdb=--  trd365ai=--
  qa     maindb=--  orgdb=--  trd365ai=--
  stage  maindb=--  orgdb=--  trd365ai=--
  prod   maindb=ok  orgdb=ok  trd365ai=ok
```

Dev, QA and Stage are still genuine placeholders — those credentials have never
been supplied (§6 open question 1). Prod resolves fully.

**Production has 26 tenant schemas** (`trd365_00042`, `trd365_00353`, …), read
from the live catalog. That is the first fact about the real database anything
here has established.

### Two more bugs that only a live run could find

Both passed 482 unit tests, lint and static analysis.

1. **`paramiko.DSSKey` no longer exists.** `sshtunnel` 0.4.0 names `RSAKey`,
   `DSSKey` and `ECDSAKey` directly; paramiko 4 removed DSA, and unpinned pip
   installs paramiko 5. Every tunnel failed — and maindb and orgdb are only
   reachable through one. Pinned `paramiko>=3.4,<4`, and
   `tests/test_dependencies.py` now exercises the imports the fakes stand in for,
   because faking the tunnel is right and makes a broken dependency *combination*
   invisible.
2. **A deploy runs the previous revision's `deploy.sh`.** The snapshot is taken
   before the fetch, so a change to the deploy script itself takes effect on the
   *next* run. Correct, and surprising: expect to run a deploy twice when the
   change is to `deploy.sh`.

### The model, from production

`data-model-analysis --env prod --apply --no-orphans` has run. The current
snapshot is `0c0f5d1129eab815`.

```
schemas     : 26
tables      : 2791
references  : 8518
deviations  : 878   (global-lookup 107, typo 33, unknown 738)
```

The first run told a different and wrong story — 5,273 references and 1,650
deviations — and correcting it found two real defects, described below. Both are
fixed, and the numbers above are after.

### What the first production run exposed

**1. Only one cross-database edge was known.** `references()` special-cased
`account_rid` and treated every other reference to a table outside the tenant
schema as unresolvable. That accounted for 1,165 "unknown" deviations, led by
`status_rid` (691 columns), `country_rid` (461), `region_rid` (349) and
`currency_rid` (323).

A query against the live databases settled it: `country`, `currency`, `industry`,
`interaction_level`, `interaction_status`, `project_classification`,
`project_type`, `resource_type`, `state`, `status` and `task_type` are all real
tables in `maindb.trd365`, and **none of them exists in any tenant schema**. They
are shared lookups referenced from all 26 tenants — structurally identical to
`account_rid`. `interaction_status_rid` had even been flagged as a likely typo,
when `interaction_status` is simply a main-schema table.

Resolution now falls back to the main schema. References went 5,273 -> **8,518**.

**2. The report recomputed deviations and ignored the fix.** With references
corrected, the deviation count did not move — the analysis derives deviations from
the tenant catalog alone rather than from what the snapshot resolved. So the
snapshot was right and the report was still wrong. Deviations then went 1,650 ->
**878**, and likely-typos 66 -> **33**.

This matters beyond tidiness: deviations are the health signal the Phase-3
dashboard is built on (FR-4.5), and a signal that is 70% correct cross-database
references is not a signal.

### The next clear improvement — qualified prefixes

Reading what remains, one pattern accounts for a large share: a column whose
prefix is a *qualified* form of the table name.

```
old_status_rid, new_status_rid          -> status
parent_case_rid                        -> cases
parent_interaction_rid                 -> interactions
current_branch_rid                     -> branch
assigned_skill_role_type_rid           -> skill_role_type
case_owner_rid, sent_by, uploaded_by_user -> a person/user table
```

`resolve_parent_table` tries only the bare prefix and its plurals. Stripping a
short list of qualifiers — `old_`, `new_`, `parent_`, `current_`, `source_`,
`target_`, `assigned_` — and retrying would resolve well over a hundred more.
Worth doing, and worth doing carefully: a wrong qualifier rule invents a parent
that is not there, which is worse than reporting the column unresolved.

Genuinely unexplained and worth a human: `session` (208 columns) and `task` (179)
resolve nowhere — not in any tenant schema and not in the main schema.

### Four bugs the first live deploy found that no test could

Each of these passed lint, static analysis and 452 unit tests, and each broke on
a real machine. Worth remembering before trusting the next untested path.

1. **`deploy.sh` was never on the VM.** The unit ran
   `ExecStart=/opt/trd365/deploy.sh`, but that file lives in the repository, and
   the repository is cloned *by* `deploy.sh`. Circular; the box could never
   deploy itself. cloud-init now makes the first clone.
2. **`app_branch` defaulted to `main`, which does not exist** on the remote. The
   clone would have failed outright — hidden until something actually cloned.
3. **The service account could not restart the service it deploys.** No sudo
   rights. Now scoped to exactly two verbs on exactly that one unit.
4. **`deploy.sh` rewrote itself mid-run.** Bash reads a script incrementally, so
   after `git reset` replaced the file, bash continued reading the *new* bytes
   from the *old* offset — executing a splice of two versions. This is why a
   fixed install step kept failing with the pre-fix error message on a VM that
   had already fetched the fix. The script now re-execs from a `/tmp` snapshot.

Plus two ordering faults: the packages depend on each other, so installing them
one at a time in directory order sent pip to PyPI for `trd365-core`; and the
"already at this revision" fast path skipped install and tests on a fresh box
where cloud-init had cloned the same commit.

---

## 13. The live site

**https://52-173-109-182.nip.io/** — `demo` / `admin`.

Real Let's Encrypt certificate (`CN=52-173-109-182.nip.io`, expires 2026-11-19),
no browser warning.

`/` is the operator console. It was the service description as JSON for a while,
which meant anyone who signed in saw a JSON object and reasonably concluded there
was no application; the description now lives at `/api`, where a machine-readable
root belongs. `/docs` is still FastAPI's interactive Swagger UI against the live
service.

The console is one dependency-free HTML file served from the package
(`trd365_orchestrator/web/index.html`). There is no Node on the VM and no build
step in the deploy, so a bundler would mean either committing build output or
installing a toolchain on a host that holds production credentials. **The React
SPA of Phase 3 replaces this** — until then this is the whole client, and it is a
read-only view: environments and their per-database reachability, the utility
catalogue with impact and approval rules, the data-model snapshot summary, jobs,
and the audit trail.

Two details worth keeping if it is rewritten. The environment pill follows
`status` off the health payload rather than recomputing it in the browser, which
is how a dashboard ends up disagreeing with the API it reads — a test derives
that vocabulary from `EnvironmentHealth` so adding a status fails the suite
instead of shipping an unlabelled pill. And status is never colour alone: every
pill carries a glyph and a word, and a failing database is named in the card
text, not just tinted red.

`/api/me` exists for the console's benefit: it reports what the current sign-in
may do, so the page can say "read-only access" instead of offering controls that
would 403.

**What the console shows as empty, and why.** The data-model panel says no
snapshot has been captured. That is accurate — the production snapshot
(`0c0f5d1129eab815`: 26 schemas, 2,791 tables, 8,518 references, 878 deviations)
was produced in a working session and lives there, not in `/var/lib/trd365/model`
on the VM. Running `python -m trd365_analysis --env prod --apply` on the host
would fill the panel, the audit trail and the jobs list with real figures in one
pass. It is read-only against the databases; it is the snapshot it writes.

Provisioned by `terraform apply -var expose_publicly=true -var demo_password=…`.

### Why exposing this host is defensible

Not because of the login. Because of what the login is allowed to become.

Caddy authenticates and then injects `X-Dev-Roles: viewer` and nothing else. The
service requires operator or admin to start any utility that writes, and every
registered utility writes. Verified against the live site:

```
GET  /                     -> 200, with credentials; 401 without
GET  /api/utilities        -> 200, the real catalogue
GET  /api/audit            -> 200
POST /api/jobs (purge)     -> "demo needs the operator role to run purge-account."
:8080 from the internet    -> refused; only 80 and 443 are open, Caddy proxies
                              over loopback and uvicorn binds 127.0.0.1
```

So the exposed surface reads everything and runs nothing, by construction rather
than by trusting a shared password.

**It is still a demonstration posture, and should be turned off when the demo is
over.** One shared secret, no record of who used it, and an authenticator the
service ships for development. Entra ID SSO (FR-3.x) is the real answer. To
close it: `terraform apply` with `expose_publicly=false`, which removes the
public IP and the inbound rules.

### Four failures getting Caddy up, all environmental

Each one is the kind that only appears on a real host.

1. **A dpkg conffile prompt.** cloud-init wrote `/etc/caddy/Caddyfile` before the
   package existed. `apt-get install caddy` asked whether to keep it, found no
   stdin, and dpkg aborted — binary unpacked, package unconfigured, unit never
   enabled. The config is now staged at `/etc/trd365/Caddyfile` and installed
   after the package, with `--force-confold` as a second guard.
2. **`$` in a bcrypt hash.** The setup script sourced the credential file under
   `set -u`; a hash is literally `$2a$14$…`, so bash tried to expand `$2a` and
   aborted. The values are passed to `caddy validate` directly and nothing is
   sourced. systemd's `EnvironmentFile` does no expansion, so the file was never
   the problem.
3. **A log file it could not open.** The packaged unit sandboxes the filesystem,
   so `/var/log/caddy/access.log` was "permission denied" no matter who owned it.
   Access logs go to the journal now: `journalctl -u caddy -f`.
4. **A hundred round trips for nothing.** The first call to
   `/api/health/environments` timed out. Readiness across four environments and
   three databases asks for well over a hundred secret names, and dev, QA and
   stage have no credentials, so nearly all were absent — each its own request.
   The vault is listed once now; that endpoint answers in about 8 seconds.
