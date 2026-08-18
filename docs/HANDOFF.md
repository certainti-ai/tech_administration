# Handoff

**Read this first.** It is the resume point for anyone — human or another Claude
session — picking this work up cold.

Last updated: 2026-08-17, session 2.
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
  (lint/typecheck/test/build), and a Python job that self-skips until
  `packages/*/pyproject.toml` exists.

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

## 4. Next task — start here

**`trd365-core` is done.** Build the first utility package on top of it.

### Step 1 — `packages/trd365-data-purge`

Migrate `legacy/trd365_maintenance/data_purge/` first: it is the
best-structured module and becomes the template for the rest.

- Package layout mirroring `trd365-core` (`pyproject.toml`, `src/`, `tests/`),
  depending on `trd365-core`.
- Sub-commands `account`, `case`, `interaction`, `project`, `project_fiscal`.
- Replace `engine/db.py` with `trd365_core.ConnectionPool`, and any local
  schema assumptions with `trd365_core.datamodel`.
- Replace hand-rolled argparse with `trd365_core.cli.build_parser`. The five
  tools already default to dry run, so only `--env` is new to them.
- Wrap each run in `trd365_core.AuditedRun` and call `record_rows` per table.
- Register each sub-command in `trd365_core.registry` — the Phase-2 API and
  Phase-3 UI are generated from it.
- **Move `base_sql/*.sql` and `DELETION_ORDER.md` unchanged.** The SQL encodes
  foreign-key deletion order; it is data, not code to rewrite.

Consume the shared model rather than introspecting: call
`require_model(store, args.env, utility="purge-account")` and drive table
ordering from `model.tables_referencing(schema, entity)`.

### Step 2 — the remaining modules

3. `data_model_analysis` — the **producer** of the shared model. It must call
   `build_snapshot()` and `store.save()` on every run; that is what propagates
   a refreshed model to every other utility (FR-1.9/1.10). Port it onto
   `trd365_core.datamodel`, which already holds its conventions. Its orphan and
   deviation counts are the health metrics the Phase-3 dashboard needs
   (FR-4.5), and `diff_snapshots()` gives the drift signal.
4. `reference_table_corrections`, `sharepoint_migration`,
   `interactions_dashboard`.
5. `account_deletion` — **keep it**, alongside `data_purge/account`. The owner
   has deferred the decision; use `Utility.supersedes` to record the
   relationship so the UI can show it without either being deleted.
6. `project_fiscal_year_deletion` — delete **only** after confirming its extra
   flags (`--sections`, `--concurrency`, `--heartbeat`, `--backup-schema`,
   `--limit`) exist in the `data_purge` equivalent. Port them first if not.
7. Port `manual-rd-percent-update` JS → Python. Write characterisation tests
   from the JS behaviour *first*. It touches money.

### Step 3 — flip the three destructive-by-default tools

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
7. ~~**Maintenance VM**~~ — **effectively closed.** The Terraform now creates
   the resource group, Key Vault and SSH key, and takes auth, subscription and
   region from the environment. **One input remains: `subnet_id`**, which must
   reach the bastion and trd365ai — there is nothing sensible to guess, and a
   wrong subnet means a VM that sees nothing. The Terraform identity also needs
   User Access Administrator alongside Contributor, since two RBAC role
   assignments are created. See `infra/terraform/PREFLIGHT.md` and
   `SECURITY.md`.
8. **Entra ID** — which tenant and app registration should the SPA use, and
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
