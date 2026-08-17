# Handoff

**Read this first.** It is the resume point for anyone — human or another Claude
session — picking this work up cold.

Last updated: 2026-08-17, end of session 1.
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
  `packages/` (empty, for Python), `legacy/` (vendored source scripts).
- **CI** — `.github/workflows/ci.yml` runs Node tooling tests, the web app
  (lint/typecheck/test/build), and a Python job that self-skips until
  `packages/*/pyproject.toml` exists.

### Vendored, untouched

`legacy/trd365_maintenance/` — all 114 files of the operator's original scripts,
exactly as supplied, secrets already replaced with `CHANGE_ME`. **This is source
material. Do not edit it in place** — refactor *out* of it into `packages/`, so
the original stays available for comparison.

### Not started

`packages/` is empty. Phases 1–4 are all ahead. See §4.

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

**Phase 1, step 1: build `packages/trd365-core`.**

Everything else depends on it. Suggested surface:

```
packages/trd365-core/
  pyproject.toml
  src/trd365_core/
    config.py     Environment resolution (dev/qa/stage/prod) -> connection settings.
                  Build the legacy db_config shape from env vars / Key Vault so
                  each utility migrates with a one-line change (see KB §4).
    db.py         ConnectionPool + SSH tunnels. Lift from
                  legacy/trd365_maintenance/data_purge/engine/db.py — it is
                  already decent; the fault is that there are four copies.
                  Preserve: retry 4x with 5s*n backoff, tunnel teardown on
                  failure, per-DB tunnels.
    cli.py        Shared argparse base. MUST enforce: --env is required with no
                  default; --apply gates all writes; --dry-run is a hard error
                  with a message pointing at the change (KB §3.1).
    audit.py      Append-only run records (FR-3). JSONL locally now; the
                  Phase-2 service swaps the sink.
    registry.py   Utility descriptors: id, description, typed parameters,
                  destructive flag, databases touched. Phase 2 API and Phase 3
                  UI are both generated from this — design it before writing
                  many utilities against it.
    reporting.py  Consolidate the three report.py copies.
```

Then, in order:

1. Migrate `data_purge/` onto core first — it is the best-structured module and
   the template for the rest.
2. Delete `project_fiscal_year_deletion/` **after** confirming its extra flags
   (`--sections`, `--concurrency`, `--heartbeat`, `--backup-schema`, `--limit`)
   exist in the `data_purge` equivalent. If they do not, port them across first.
3. Migrate the remaining modules.
4. Port `manual-rd-percent-update` JS → Python. Write characterisation tests
   from the JS behaviour *first*. It touches money.
5. Standardise every entry point on `--apply`.
6. Add the test that asserts *every* registered utility is dry-run by default —
   that is the regression guard for the headline safety bug.

## 5. Things that will bite you

- **You cannot reach any database from a Claude session.** Private endpoints do
  not resolve; the proxy blocks TCP :22 and `vault.azure.net`. Verified. Unit
  tests and fakes only — integration testing happens on the VM. Do not claim
  verification you cannot perform.
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

1. **Dev/QA/Stage database connections.** Only Prod is known. What are the other
   three environments' hosts/databases, and do they sit behind the same bastion?
   FR-1.3 and the whole multi-environment story block on this.
2. **`account_deletion/` vs `data_purge/account/`.** Two implementations that
   look like they do the same thing. Which is current? Can one be deleted?
3. **`reference_table_corrections/discover{,2,3}.py`.** Three scratch
   iterations. Which is authoritative?
4. **`task_deletion_by_milestone/`.** 18 KB of SQL with no runner. Dead, or run
   by hand? Does it need a Python wrapper?
5. **`project_fiscal_year_deletion` extra flags** — are they still needed?
   (Blocks the de-duplication in §4.2.)
6. **AWS credentials are broken** — `AWS_ACCESS_KEY_ID` and
   `AWS_SECRET_ACCESS_KEY` hold the same 14-character value with no `AKIA`
   prefix. What were they for? Fix or drop.
7. **Maintenance VM** — subscription, resource group, region, size, and which
   VNet(s) it must reach to see all four environments.
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

Phase 1 not started — `packages/` is empty. **Resume at §4.**
