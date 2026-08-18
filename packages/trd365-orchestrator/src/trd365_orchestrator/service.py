"""
The orchestrator's use cases, independent of HTTP.

Everything the API does goes through here, so the rules — authorisation,
approval, valid transitions — are enforced once and are testable without a web
client.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from trd365_core.audit import AuditSink
from trd365_core.environments import Environment
from trd365_core.errors import Trd365Error
from trd365_core.model_snapshot import DEFAULT_MAX_AGE, ModelStore
from trd365_core.registry import Registry

from .commands import build_argv
from .health import EnvironmentHealth, environment_health
from .jobs import Job, JobState, JobStore, new_job
from .scheduler import Scheduler
from .security import (
    AuthorizationError,
    Principal,
    authorize_run,
    can_approve,
    can_view,
    requires_approval,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class OrchestratorConfig:
    authentication_configured: bool = False
    probe_databases: bool = False
    max_model_age: timedelta = DEFAULT_MAX_AGE


class Orchestrator:
    def __init__(
        self,
        registry: Registry,
        store: JobStore,
        scheduler: Scheduler,
        *,
        model_store: ModelStore | None = None,
        pool_factory=None,
        audit_sink: AuditSink | None = None,
        config: OrchestratorConfig | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        self.registry = registry
        self.store = store
        self.scheduler = scheduler
        self.model_store = model_store
        self.pool_factory = pool_factory
        self.audit_sink = audit_sink
        self.config = config or OrchestratorConfig()
        self._environ = environ

    # ------------------------------------------------------------- utilities

    def list_utilities(self, principal: Principal) -> list[dict[str, Any]]:
        if not can_view(principal):
            raise AuthorizationError("Viewer role required.")
        return self.registry.to_dict()

    def preview_command(
        self, utility_id: str, environment: Environment, arguments: dict[str, Any], apply: bool
    ) -> str:
        """The exact command a run would execute, shown before confirming."""
        utility = self.registry.get(utility_id)
        return " ".join(build_argv(utility, environment, arguments, apply=apply))

    # ------------------------------------------------------------------ jobs

    def request_run(
        self,
        principal: Principal,
        *,
        utility_id: str,
        environment: Environment,
        arguments: dict[str, Any],
        apply: bool,
    ) -> Job:
        """
        Ask for a run.

        A production write is *requested*, not started: it lands in
        ``pending_approval`` and waits for a different person (FR-4.3).
        Everything else queues immediately.
        """
        utility = self.registry.get(utility_id)

        authorize_run(
            principal,
            utility,
            environment,
            apply,
            authentication_configured=self.config.authentication_configured,
        )

        # Fail on bad arguments now, while there is a person to tell, rather
        # than after an approval has been collected.
        build_argv(utility, environment, arguments, apply=apply)

        needs_approval = requires_approval(utility, environment, apply)
        job = new_job(
            utility_id=utility_id,
            environment=environment,
            apply=apply,
            arguments=arguments,
            requested_by=principal.subject,
            needs_approval=needs_approval,
        )
        self.store.add(job)

        if not needs_approval:
            self.scheduler.submit(job)
        return job

    def approve(self, principal: Principal, job_id: str) -> Job:
        job = self.store.get(job_id)
        if job.state is not JobState.PENDING_APPROVAL:
            raise Trd365Error(f"Job {job_id} is {job.state.value}, not awaiting approval.")

        if not can_approve(principal, job.requested_by):
            if principal.subject == job.requested_by:
                raise AuthorizationError(
                    "You cannot approve your own production run. A second approver that can "
                    "be the same person is not a second approver."
                )
            raise AuthorizationError("Approver role required.")

        job.approved_by = principal.subject
        job.approved_at = _now()
        job.transition(JobState.QUEUED)
        self.scheduler.submit(job)
        return job

    def reject(self, principal: Principal, job_id: str, reason: str = "") -> Job:
        job = self.store.get(job_id)
        if job.state is not JobState.PENDING_APPROVAL:
            raise Trd365Error(f"Job {job_id} is {job.state.value}, not awaiting approval.")
        if not can_approve(principal, job.requested_by):
            raise AuthorizationError("Approver role required.")

        job.transition(JobState.REJECTED)
        job.approved_by = principal.subject
        job.approved_at = _now()
        job.finished_at = _now()
        job.error = reason or "rejected"
        return job

    def cancel(self, principal: Principal, job_id: str) -> Job:
        job = self.store.get(job_id)
        # The requester can always stop their own job; otherwise operator rights
        # are needed. Stopping a destructive run should never be the hard part.
        from .security import Role

        if principal.subject != job.requested_by and not principal.has(Role.OPERATOR, Role.ADMIN):
            raise AuthorizationError("Operator role required to cancel someone else's job.")
        return self.scheduler.cancel(job_id)

    def get_job(self, principal: Principal, job_id: str) -> Job:
        if not can_view(principal):
            raise AuthorizationError("Viewer role required.")
        return self.store.get(job_id)

    def list_jobs(self, principal: Principal, **filters) -> list[Job]:
        if not can_view(principal):
            raise AuthorizationError("Viewer role required.")
        return self.store.list(**filters)

    def pending_approvals(self, principal: Principal) -> list[Job]:
        return self.list_jobs(principal, state=JobState.PENDING_APPROVAL, limit=1000)

    # ---------------------------------------------------------------- health

    def health(self, environment: Environment) -> EnvironmentHealth:
        return environment_health(
            environment,
            model_store=self.model_store,
            pool_factory=self.pool_factory,
            probe_databases=self.config.probe_databases,
            max_model_age=self.config.max_model_age,
            active_jobs=len(self.store.active(environment)),
            writer_busy=self.scheduler.is_busy(environment),
            environ=self._environ,
        )

    def health_all(self) -> list[EnvironmentHealth]:
        return [self.health(env) for env in Environment]
