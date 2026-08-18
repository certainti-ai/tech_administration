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
packages/       Python maintenance packages (trd365-core built)
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

Secrets:

```bash
npm run secrets:check -- --vault certainti-kv
source scripts/secrets/load.sh
```

## Where the project is

| Phase | Contents | State |
|---|---|---|
| 0 | Web scaffold, Key Vault tooling, monorepo restructure | **Done** |
| 1 | `trd365-core` **done**; utility packages, de-duplication, JS→Python port | **In progress** |
| 2 | FastAPI orchestrator, job execution, audit log | **Done** |
| 3 | React SPA — invocation, health dashboard, audit, SSO | Not started |
| 4 | Maintenance VM, Terraform, deployment | **Terraform written, never applied** |

Two constraints worth knowing before you plan work:

- **No Claude Code session can reach the databases.** The private endpoints do
  not resolve and the proxy blocks the bastion. Verification here is unit tests
  and fakes; integration testing happens on the maintenance VM.
- **Destructive utilities are the point of this system.** Safety defaults, an
  audit trail, and per-environment authorization are load-bearing requirements,
  not later polish.

## CI

`.github/workflows/ci.yml` — Node tooling tests, the web app
(lint/typecheck/test/build), and a Python job that activates once
`packages/*/pyproject.toml` exists.

`.github/workflows/secrets-check.yml` — weekly Key Vault verification over OIDC.
