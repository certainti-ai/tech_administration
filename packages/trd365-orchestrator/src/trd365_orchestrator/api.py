"""HTTP surface. Thin — every rule lives in :mod:`service`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from trd365_core.audit import default_audit_path, read_records
from trd365_core.environments import Environment
from trd365_core.errors import Trd365Error
from trd365_core.model_snapshot import diff_snapshots

from .jobs import JobState
from .security import AuthorizationError, Principal

router = APIRouter()


def get_orchestrator(request: Request):
    return request.app.state.orchestrator


def get_principal(request: Request) -> Principal:
    return request.app.state.authenticator(request)


def _env(value: str) -> Environment:
    try:
        return Environment.parse(value)
    except Trd365Error as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, AuthorizationError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, Trd365Error):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


# Endpoints that mutate scheduler state are declared `async def` deliberately:
# see the note on create_job.


class RunRequest(BaseModel):
    utility_id: str
    environment: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    apply: bool = False


class RejectRequest(BaseModel):
    reason: str = ""


# ------------------------------------------------------------------ utilities


@router.get("/utilities")
def list_utilities(orchestrator=Depends(get_orchestrator), principal=Depends(get_principal)):
    try:
        return {"utilities": orchestrator.list_utilities(principal)}
    except Exception as exc:
        raise _handle(exc) from exc


@router.post("/utilities/{utility_id}/preview")
def preview(
    utility_id: str,
    body: RunRequest,
    orchestrator=Depends(get_orchestrator),
    principal=Depends(get_principal),
):
    """The exact command a run would execute. Always safe — nothing is started."""
    try:
        command = orchestrator.preview_command(
            utility_id, _env(body.environment), body.arguments, body.apply
        )
        utility = orchestrator.registry.get(utility_id)
        from .security import requires_approval

        return {
            "command": command,
            "mode": "apply" if body.apply else "dry-run",
            "requires_approval": requires_approval(utility, _env(body.environment), body.apply),
            "impact": utility.impact.value,
            "databases": list(utility.databases),
        }
    except Exception as exc:
        raise _handle(exc) from exc


# ----------------------------------------------------------------------- jobs


@router.post("/jobs", status_code=201)
async def create_job(
    body: RunRequest, orchestrator=Depends(get_orchestrator), principal=Depends(get_principal)
):
    try:
        job = orchestrator.request_run(
            principal,
            utility_id=body.utility_id,
            environment=_env(body.environment),
            arguments=body.arguments,
            apply=body.apply,
        )
        return job.to_dict()
    except Exception as exc:
        raise _handle(exc) from exc


@router.get("/jobs")
def list_jobs(
    environment: str | None = None,
    state: str | None = None,
    utility_id: str | None = None,
    limit: int = Query(default=100, le=1000),
    orchestrator=Depends(get_orchestrator),
    principal=Depends(get_principal),
):
    try:
        jobs = orchestrator.list_jobs(
            principal,
            environment=_env(environment) if environment else None,
            state=JobState(state) if state else None,
            utility_id=utility_id,
            limit=limit,
        )
        return {"jobs": [j.to_dict() for j in jobs]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown state: {state}") from exc
    except Exception as exc:
        raise _handle(exc) from exc


@router.get("/jobs/{job_id}")
def get_job(job_id: str, orchestrator=Depends(get_orchestrator), principal=Depends(get_principal)):
    try:
        return orchestrator.get_job(principal, job_id).to_dict()
    except Trd365Error as exc:
        if "No job" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise _handle(exc) from exc


@router.post("/jobs/{job_id}/approve")
async def approve(
    job_id: str,
    orchestrator=Depends(get_orchestrator),
    principal=Depends(get_principal),
):
    try:
        return orchestrator.approve(principal, job_id).to_dict()
    except Exception as exc:
        raise _handle(exc) from exc


@router.post("/jobs/{job_id}/reject")
async def reject(
    job_id: str,
    body: RejectRequest,
    orchestrator=Depends(get_orchestrator),
    principal=Depends(get_principal),
):
    try:
        return orchestrator.reject(principal, job_id, body.reason).to_dict()
    except Exception as exc:
        raise _handle(exc) from exc


@router.post("/jobs/{job_id}/cancel")
async def cancel(
    job_id: str,
    orchestrator=Depends(get_orchestrator),
    principal=Depends(get_principal),
):
    try:
        return orchestrator.cancel(principal, job_id).to_dict()
    except Exception as exc:
        raise _handle(exc) from exc


@router.get("/approvals")
def approvals(orchestrator=Depends(get_orchestrator), principal=Depends(get_principal)):
    try:
        return {"jobs": [j.to_dict() for j in orchestrator.pending_approvals(principal)]}
    except Exception as exc:
        raise _handle(exc) from exc


# --------------------------------------------------------------------- health


@router.get("/me")
def me(principal=Depends(get_principal)):
    """
    Who the caller is and what they may do.

    The console reads this to describe itself honestly. Without it a read-only
    visitor is shown controls that will refuse them, which reads as a broken
    application rather than as a deliberate restriction.
    """
    from .security import Role, can_view

    return {
        "subject": principal.subject,
        "display_name": principal.display_name,
        # The console needs this to tell "not signed in" from "signed in with
        # nothing assigned". Both have no roles; only one is fixed by signing in.
        "authenticated": principal.authenticated,
        "roles": sorted(role.value for role in principal.roles),
        "can_view": can_view(principal),
        # Starting anything that writes needs operator or admin, and every
        # registered utility writes.
        "can_run": principal.has(Role.OPERATOR, Role.ADMIN),
        "can_approve": principal.has(Role.APPROVER, Role.ADMIN),
    }


@router.get("/health")
def health(orchestrator=Depends(get_orchestrator)):
    """Unauthenticated: a liveness probe must work before anyone signs in."""
    return {"status": "ok"}


@router.get("/health/environments")
def environments_health(orchestrator=Depends(get_orchestrator), principal=Depends(get_principal)):
    try:
        from .security import can_view

        if not can_view(principal):
            raise AuthorizationError("Viewer role required.")
        return {"environments": [h.to_dict() for h in orchestrator.health_all()]}
    except Exception as exc:
        raise _handle(exc) from exc


# ---------------------------------------------------------------------- model


@router.get("/model/{environment}")
def model(
    environment: str,
    orchestrator=Depends(get_orchestrator),
    principal=Depends(get_principal),
):
    try:
        from .security import can_view

        if not can_view(principal):
            raise AuthorizationError("Viewer role required.")
        if orchestrator.model_store is None:
            raise HTTPException(status_code=503, detail="No model store configured.")

        snapshot = orchestrator.model_store.latest(_env(environment))
        if snapshot is None:
            raise HTTPException(
                status_code=404,
                detail=f"No data-model snapshot for {environment}. Run the analysis first.",
            )
        return {
            "environment": snapshot.environment,
            "generated_at": snapshot.generated_at,
            "generated_by": snapshot.generated_by,
            "fingerprint": snapshot.fingerprint,
            "summary": snapshot.summary(),
            # The breakdown behind the deviation total. Without it the console can
            # show how many there are and not what kind, which is the only part
            # that tells an operator whether to care.
            "deviations": snapshot.deviation_counts(),
            "schemas": snapshot.tenant_schemas,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise _handle(exc) from exc


@router.get("/model/{environment}/drift")
def model_drift(
    environment: str, orchestrator=Depends(get_orchestrator), principal=Depends(get_principal)
):
    """What changed between the two most recent snapshots."""
    try:
        from .security import can_view

        if not can_view(principal):
            raise AuthorizationError("Viewer role required.")
        store = orchestrator.model_store
        if store is None:
            raise HTTPException(status_code=503, detail="No model store configured.")

        env = _env(environment)
        versions = store.versions(env)
        if len(versions) < 2:
            return {"changed": False, "summary": "Only one snapshot; nothing to compare."}

        previous = store.load(env, versions[-2])
        latest = store.load(env, versions[-1])
        difference = diff_snapshots(previous, latest)
        return {
            "changed": difference.changed,
            "summary": difference.summary(),
            "added_schemas": difference.added_schemas,
            "removed_schemas": difference.removed_schemas,
            "schema_diffs": [
                {
                    "schema": d.schema,
                    "added_tables": d.added_tables,
                    "removed_tables": d.removed_tables,
                    "added_references": d.added_references,
                    "removed_references": d.removed_references,
                    "added_deviations": d.added_deviations,
                    "resolved_deviations": d.resolved_deviations,
                }
                for d in difference.schema_diffs
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise _handle(exc) from exc


# ---------------------------------------------------------------------- audit


@router.get("/audit")
def audit(
    limit: int = Query(default=200, le=2000),
    environment: str | None = None,
    utility: str | None = None,
    orchestrator=Depends(get_orchestrator),
    principal=Depends(get_principal),
):
    """
    The audit trail. Read-only by construction — there is deliberately no
    endpoint that edits or deletes a record (PRD FR-3.2).
    """
    try:
        from .security import can_view

        if not can_view(principal):
            raise AuthorizationError("Viewer role required.")

        path = getattr(orchestrator, "audit_path", None) or default_audit_path()
        records = read_records(path)
        if environment:
            records = [r for r in records if r.environment == environment]
        if utility:
            records = [r for r in records if r.utility == utility]

        records.sort(key=lambda r: r.started_at, reverse=True)
        return {
            "records": [
                {
                    "run_id": r.run_id,
                    "utility": r.utility,
                    "environment": r.environment,
                    "actor": r.actor,
                    "mode": r.mode,
                    "outcome": r.outcome,
                    "started_at": r.started_at,
                    "finished_at": r.finished_at,
                    "rows_affected": r.rows_affected,
                    "error": r.error,
                    "notes": r.notes,
                }
                for r in records[:limit]
            ]
        }
    except Exception as exc:
        raise _handle(exc) from exc
