# Certainti Tech Administration

Platform for administering Certainti's technical estate: maintenance utilities,
the databases they operate on, and the internal portal that runs them.

**New here? Read [`docs/HANDOFF.md`](docs/HANDOFF.md) first.**

## Documentation

| Document | Contents |
|---|---|
| [`docs/HANDOFF.md`](docs/HANDOFF.md) | **Start here.** Current state, next task, gotchas, open questions |
| [`docs/PRD.md`](docs/PRD.md) | Requirements, settled architecture decisions, phasing |
| [`docs/knowledge-base.md`](docs/knowledge-base.md) | The maintenance scripts, the databases, and the traps |
| [`docs/secrets.md`](docs/secrets.md) | Azure Key Vault as the credential source of truth |

## Layout

```
apps/web/       Next.js portal (Phase 0; ports into the Phase 3 SPA)
packages/       Python maintenance packages (core, orchestrator, data-purge, analysis)
infra/          Terraform for the maintenance VM, and deploy scripts
legacy/         Original operator scripts, vendored verbatim. Reference only.
scripts/        Repo-wide tooling (Key Vault secrets management)
docs/           PRD, knowledge base, handoff, secrets runbook
tests/          Tests for repo-wide tooling
```

## Getting started

```bash
npm install          # installs the workspace root and apps/web

npm test             # repo tooling tests
npm run web:dev      # http://localhost:3000
npm run web:test
npm run web:build
```

Python packages:

```bash
pip install -e packages/trd365-core \
            -e "packages/trd365-orchestrator[dev]" \
            -e "packages/trd365-data-purge[dev]" \
            -e "packages/trd365-analysis[dev]"

ruff check packages/
for pkg in packages/*/; do (cd "$pkg" && pytest -q); done
```

Run pytest **per package**, never `pytest packages/` — each package carries its
own config (`asyncio_mode`, `testpaths`) and a repo-root rootdir ignores it.

| Package | What it is | Tests |
|---|---|---|
| `trd365-core` | Environments, connections, data model, CLI conventions, audit, registry | 168 |
| `trd365-orchestrator` | FastAPI service: jobs, approvals, execution, health | 71 |
| `trd365-data-purge` | Purge engine and `purge-account` | 132 |
| `trd365-analysis` | `data-model-analysis` — produces the shared model, finds orphans | 73 |

Utilities are discovered through the `trd365.utilities` entry-point group, so
installing a package makes it appear in the API — there is no list to edit.

Secrets:

```bash
npm run secrets:check -- --vault certainti-kv
source scripts/secrets/load.sh
```

## Where the project is

| Phase | Contents | State |
|---|---|---|
| 0 | Web scaffold, Key Vault tooling, monorepo restructure | **Done** |
| 1 | `trd365-core`, `trd365-data-purge`, `trd365-analysis` **done**; remaining utility packages, JS→Python port | **In progress** |
| 2 | FastAPI orchestrator, job execution, audit log | **Done** |
| 3 | React SPA — invocation, health dashboard, audit, SSO | Not started |
| 4 | Maintenance VM, Terraform, self-updating deploys | **Deployed and serving** — see `docs/HANDOFF.md` §12 |

Two constraints worth knowing before you plan work:

- **No Claude Code session can reach the databases.** The private endpoints do
  not resolve and the proxy blocks the bastion. Verification here is unit tests
  and fakes; integration testing happens on the maintenance VM — which now
  exists, and **from which all three production databases connect** (see
  `docs/HANDOFF.md` §12).
- **Deploying needs a human once.** `terraform apply` requires `az login`, which
  is interactive and impossible from a Claude session — see `docs/HANDOFF.md` §11.
  After that first apply the VM updates itself from git every three hours, gated
  on the test suite.
- **Destructive utilities are the point of this system.** Safety defaults, an
  audit trail, and per-environment authorization are load-bearing requirements,
  not later polish.

## CI

`.github/workflows/ci.yml` — Node tooling tests, the web app
(lint/typecheck/test/build), and a Python job that installs each `packages/*/`
and runs ruff plus that package's own pytest config.

`.github/workflows/secrets-check.yml` — weekly Key Vault verification over OIDC.
