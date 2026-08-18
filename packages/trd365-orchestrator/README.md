# trd365-orchestrator

Runs the maintenance utilities: job execution, approvals, audit and health.
This is the service the maintenance VM hosts.

```bash
pip install -e "packages/trd365-orchestrator[dev]"
TRD365_DEV_AUTH=1 uvicorn trd365_orchestrator.app:app --port 8080
# http://localhost:8080/docs
```

## Design points that carry weight

**Production writes need a second person.** A prod `--apply` is *requested*, not
started: it lands in `pending_approval` and waits. Self-approval is refused
regardless of role — a second approver who can be the same person is not a
second approver. Dry runs never need approval; the point of a preview is that
it is safe to take without ceremony.

**One writer per environment.** Two purges against the same database at once is
how one deadlocks against the other, or half-deletes a tree the other is
walking, so writes hold a per-environment lock (FR-2.5). Read-only jobs take no
lock — blocking a report behind a four-hour purge would only push people back to
running things by hand.

**The registry is the whitelist.** A command line is built only from parameters
the utility declares. Without that, the API would let a caller append arbitrary
flags to something that deletes production data. Unknown arguments, missing
required ones, non-integers, and embedded newlines are all rejected before a job
is created.

**Unconfigured authentication refuses to write.** With no authenticator, callers
are anonymous and hold no roles, so nothing that writes will start. A deployment
that forgot to configure auth fails closed rather than exposing an
unauthenticated route to a production purge.

**Cancellation gives the utility a chance to roll back.** SIGTERM to the whole
process group — so `psql` and any SSH tunnel the tool started get it too — then
a grace period, and SIGKILL only if it will not go. A kill that skipped SIGTERM
could leave a purge half-applied. When it does escalate, the operator is told
the database may hold an incomplete transaction.

**The audit trail is append-only by construction.** There is no route that edits
or deletes a record, and a test asserts that against the published OpenAPI
schema (FR-3.2). Runs are recorded on success, failure *and* cancellation, with
cancellation distinguished from failure — that difference matters when reading
back what happened to a purge someone stopped deliberately.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness. Unauthenticated — a probe must work before anyone signs in |
| `GET` | `/api/utilities` | The catalogue the UI renders from |
| `POST` | `/api/utilities/{id}/preview` | The exact command a run would execute. Starts nothing |
| `POST` | `/api/jobs` | Request a run |
| `GET` | `/api/jobs` | List, filterable by environment, state, utility |
| `GET` | `/api/jobs/{id}` | One job, with its output tail |
| `POST` | `/api/jobs/{id}/approve` \| `/reject` \| `/cancel` | Decide or stop |
| `GET` | `/api/approvals` | The pending queue |
| `GET` | `/api/health/environments` | Per-environment connectivity and model freshness |
| `GET` | `/api/model/{env}` \| `/drift` | Current data model, and what changed |
| `GET` | `/api/audit` | The trail. Read-only |

## Configuration

| Variable | Effect |
|---|---|
| `TRD365_DEV_AUTH=1` | Enable header-based development authentication |
| `TRD365_PROBE_DATABASES=1` | Let health checks open real connections |
| `TRD365_MODEL_DIR` | Where data-model snapshots live |
| `TRD365_AUDIT_DIR` | Where audit records are appended |
| `AZURE_KEY_VAULT_NAME` | Vault holding the database credentials |

Database probing is off by default: it costs an SSH tunnel and a round trip per
database, and a dashboard poll should not open three tunnels every few seconds.

## Authentication

`header_authenticator` reads `x-dev-user` and `x-dev-roles` and exists so the
API can be driven before Entra ID is wired in (Phase 3). It is enabled only by
`TRD365_DEV_AUTH=1` and is never the default.

Roles: `viewer` reads; `operator` runs; `approver` releases production runs;
`admin` does both.

**Do not enable dev auth on the maintenance VM.** It lets a caller name their
own roles in a header.

## Testing note

`SubprocessRunner` is tested against real processes, not fakes — including
SIGTERM handling, SIGKILL escalation, and that cancellation reaches grandchild
processes. It is the component that actually launches a purge; testing it with
a double would test nothing that matters.
