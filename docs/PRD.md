# Product Requirements — Certainti Tech Administration Platform

Status: **draft, approved in outline.** Architecture decisions in §3 were taken
on 2026-08-17 and are settled; everything else is open to revision.

---

## 1. Problem

Certainti's platform maintenance is performed by a collection of ad-hoc scripts
(`legacy/trd365_maintenance/`) run by hand from a laptop. That arrangement has
four concrete failures:

1. **No safety uniformity.** Some tools delete unless you pass a flag; others
   require a flag to delete. The two most destructive tools — account deletion
   and fiscal-year deletion — are in the dangerous group.
2. **No audit trail.** Nothing records who ran what, against which database,
   with what arguments, or what it changed. After the fact there is no way to
   answer "who purged this account?"
3. **No access control.** Anyone holding `db_config.json` can purge production.
   Credentials are pasted into per-module JSON files.
4. **Single environment.** The scripts assume one set of databases. Dev, QA and
   Stage are handled by editing config by hand, which is exactly when mistakes
   get made.

## 2. Goals

| # | Goal | Measure of success |
|---|---|---|
| G1 | One consistent, tested Python codebase for all maintenance utilities | Every utility is an installable package with tests; zero duplicated modules |
| G2 | Every destructive action is safe by default | No utility writes without an explicit `--apply`; verified by a test that inspects every registered utility |
| G3 | Every action is attributable | Append-only audit record for every invocation: who, what, where, when, arguments, outcome, rows affected |
| G4 | Operators use a UI, not a laptop | Utilities invocable from a web app with per-environment authorization |
| G5 | Four environments are first-class | Dev / QA / Stage / Prod selectable everywhere; Prod requires extra ceremony |
| G6 | Platform health is visible | Dashboard showing connectivity, schema drift, orphan counts, recent job outcomes |

### Non-goals (this phase)

- Replacing the application's own admin features. These are *maintenance*
  utilities — out-of-band fixes, not product functionality.
- Scheduled/automatic execution. Every run is operator-initiated. Scheduling may
  come later, but automatic destructive jobs are explicitly out of scope.
- Migrating the databases themselves.

## 3. Architecture decisions (settled)

| Decision | Choice | Rationale |
|---|---|---|
| Repo layout | **Monorepo, separate installable packages** | Shared core versioned once; changes atomic across utilities; one CI pipeline |
| App stack | **FastAPI + React SPA, single service** | Backend must run Python to invoke the utilities; one process is one deploy on one VM |
| Auth | **Entra ID SSO + per-environment RBAC + second approver for Prod** | Already an Azure shop; Prod destruction should not be a single-person action |
| Delivery order | **Phase 1 (Python consolidation) first** | Everything else builds on it, and it is independently useful |

## 4. Functional requirements

### 4.1 Utilities (Phase 1)

- **FR-1.1** Every utility is a package under `packages/`, installable and
  independently runnable as a CLI.
- **FR-1.2** Every utility that writes accepts `--apply`. Absent it, the utility
  performs a dry run and reports what *would* change. `--dry-run` is removed.
- **FR-1.3** Every utility accepts `--env {dev,qa,stage,prod}`. There is no
  default; the environment must be named explicitly.
- **FR-1.4** Connection details and credentials come from the environment /
  Azure Key Vault (see `docs/secrets.md`), never from a committed file.
- **FR-1.5** Every utility emits a structured run record (see FR-3).
- **FR-1.6** `manual-rd-percent-update` is ported from JavaScript to Python with
  behaviour preserved, including its rollback and backup-cleanup companions.
- **FR-1.7** Duplicated code is removed: one connection layer, one
  project-fiscal purge implementation.

### 4.2 Orchestration (Phase 2)

- **FR-2.1** A registry describes every utility: id, description, parameters
  with types, whether it is destructive, which databases it touches.
- **FR-2.2** Utilities are invocable individually through the orchestrator; the
  orchestrator does not impose an order or a pipeline.
- **FR-2.3** Long-running jobs execute asynchronously with streamed progress;
  the caller is never blocked on a multi-hour purge.
- **FR-2.4** A running job can be cancelled, and cancellation leaves the
  database in a consistent state (no half-applied section).
- **FR-2.5** Jobs are queued per environment so two destructive jobs cannot run
  against the same database concurrently.

### 4.3 Audit (Phase 2)

- **FR-3.1** Every invocation writes an append-only record: actor, utility,
  environment, arguments, start/end time, outcome, rows affected per table,
  and the dry-run/apply flag.
- **FR-3.2** Audit records are immutable — no update or delete path exists in
  the API.
- **FR-3.3** Audit records are queryable and exportable from the UI.
- **FR-3.4** Failed and cancelled runs are recorded as fully as successful ones.

### 4.4 Web application (Phase 3)

- **FR-4.1** Entra ID SSO. No local accounts.
- **FR-4.2** Roles: `viewer` (read dashboards and audit), `operator` (run
  non-destructive utilities, and destructive ones in Dev/QA/Stage), `approver`
  (approve Prod runs), `admin` (manage roles).
- **FR-4.3** A destructive Prod run is *requested*, not executed: it enters a
  pending state and requires approval by a different user before it runs.
- **FR-4.4** Utility invocation UI is generated from the registry (FR-2.1), so a
  new utility appears in the UI without frontend changes.
- **FR-4.5** Dashboard shows, per environment: database connectivity and
  latency, schema drift/orphan counts, recent job outcomes, pending approvals.
- **FR-4.6** Every destructive action shows a dry-run preview and requires
  explicit confirmation naming the environment.
- **FR-4.7** The existing asset/licence/people portal is carried across into the
  SPA.

### 4.5 Deployment (Phase 4)

- **FR-5.1** A dedicated maintenance VM, provisioned as code (Terraform), with
  network access to all four environments' databases via the bastion.
- **FR-5.2** The application runs as a managed service, restarts on failure, and
  survives reboot.
- **FR-5.3** The VM authenticates to Key Vault by managed identity — no stored
  credentials on disk.
- **FR-5.4** Deployment is repeatable from CI, not by hand.

## 5. Non-functional requirements

- **NFR-1 Safety.** A destructive utility must be impossible to trigger by
  accident: explicit environment, explicit `--apply`, and for Prod a second
  human.
- **NFR-2 Auditability.** Reconstructing "who changed what, when" must require
  reading exactly one log.
- **NFR-3 Least privilege.** The VM's identity reads only the secrets it needs.
  Operators hold no database credentials themselves.
- **NFR-4 Recoverability.** Every destructive utility snapshots what it deletes
  before deleting, and a documented rollback exists.
- **NFR-5 Observability.** A failed job explains itself well enough to act on
  without SSH-ing into the VM.
- **NFR-6 No secrets in the repo.** Enforced by CI.

## 6. Environments

| Env | Purpose | Destructive utilities | Approval |
|---|---|---|---|
| Dev | Development | Allowed | None |
| QA | Test | Allowed | None |
| Stage | Pre-production | Allowed | None |
| Prod | Live customer data | Allowed **only via approval workflow** | Second approver required |

Each environment supplies its own `maindb`, `orgdb`, and `trd365ai`
connections. Only Prod's are currently known (see
`legacy/trd365_maintenance/*/config/db_config.json`); **the other three are
undiscovered and are an open question — see `docs/HANDOFF.md` §Open questions.**

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| A UI button runs a Prod purge by mistake | **Critical** | Dry-run default, explicit env, typed confirmation, second approver, per-env queue |
| Porting the JS module changes financial calculations | High | Port with characterisation tests derived from the JS; compare outputs before switching over |
| Refactoring purge SQL breaks deletion order | High | Treat SQL as data, not code to rewrite; move files unchanged, cover ordering with tests |
| Bastion/VM becomes a single point of access failure | Medium | Provision as code so it is rebuildable; document the manual fallback |
| Audit log grows unbounded | Low | Retention policy, export to cold storage |

## 8. Phasing

| Phase | Contents | State |
|---|---|---|
| 0 | Web app scaffold, Key Vault secrets tooling, monorepo restructure | **Done** |
| 1 | `trd365-core`, utility packages, de-duplication, JS→Python port, tests, CI | **Next** |
| 2 | FastAPI orchestrator, job execution, audit log, registry | Not started |
| 3 | React SPA — invocation UI, health dashboard, audit views, SSO | Not started |
| 4 | Maintenance VM, Terraform, deployment pipeline, multi-env wiring | Not started |
