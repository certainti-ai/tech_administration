"""
Running jobs, one writer per environment at a time.

Two destructive jobs against the same database at once is how a purge deadlocks
against another purge, or worse, half-deletes a tree another job is walking. So
writes hold a per-environment lock (PRD FR-2.5). Read-only jobs take no lock:
they cannot interfere, and blocking a report behind a four-hour purge would only
push people back to running things by hand.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from trd365_core.audit import AuditedRun, AuditSink
from trd365_core.environments import Environment
from trd365_core.errors import Trd365Error
from trd365_core.registry import Registry

from .commands import build_argv
from .jobs import Job, JobState, JobStore
from .runner import Runner


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Scheduler:
    """Owns the running jobs and the per-environment write locks."""

    def __init__(
        self,
        registry: Registry,
        store: JobStore,
        runner: Runner,
        *,
        audit_sink: AuditSink | None = None,
        python: str | None = None,
    ) -> None:
        self._registry = registry
        self._store = store
        self._runner = runner
        self._audit_sink = audit_sink
        self._python = python
        self._locks: dict[str, asyncio.Lock] = {}
        self._cancels: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def _lock_for(self, environment: Environment) -> asyncio.Lock:
        return self._locks.setdefault(environment.value, asyncio.Lock())

    def is_busy(self, environment: Environment) -> bool:
        return self._lock_for(environment).locked()

    # ------------------------------------------------------------------ submit

    def submit(self, job: Job) -> Job:
        """Start a queued job. Jobs awaiting approval are not startable."""
        if job.state is not JobState.QUEUED:
            raise Trd365Error(f"Job {job.id} is {job.state.value}, not queued.")

        cancel = asyncio.Event()
        self._cancels[job.id] = cancel
        self._tasks[job.id] = asyncio.create_task(self._execute(job, cancel))
        return job

    def cancel(self, job_id: str) -> Job:
        """
        Ask a job to stop.

        A queued job is cancelled outright. A running one is signalled, and the
        runner gives it a chance to roll back before killing it.
        """
        job = self._store.get(job_id)
        if job.state.is_terminal:
            raise Trd365Error(f"Job {job_id} already finished as {job.state.value}.")

        event = self._cancels.get(job_id)
        if event is not None:
            event.set()

        if job.state is JobState.QUEUED:
            job.transition(JobState.CANCELLED)
            job.finished_at = _now()
            task = self._tasks.pop(job_id, None)
            if task is not None:
                task.cancel()

        return job

    async def wait(self, job_id: str) -> Job:
        """Await completion. Used by tests and by synchronous callers."""
        task = self._tasks.get(job_id)
        if task is not None:
            await asyncio.shield(task)
        return self._store.get(job_id)

    async def drain(self) -> None:
        """Wait for every in-flight job. Called on shutdown."""
        tasks = [t for t in self._tasks.values() if not t.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ----------------------------------------------------------------- execute

    async def _execute(self, job: Job, cancel: asyncio.Event) -> None:
        utility = self._registry.get(job.utility_id)
        environment = job.env
        needs_lock = job.apply or utility.impact.needs_apply

        try:
            if needs_lock:
                lock = self._lock_for(environment)
                if lock.locked():
                    self._store.append_output(
                        job,
                        f"[orchestrator] waiting: another writing job holds {environment.value}",
                    )
                await lock.acquire()
            else:
                lock = None

            try:
                if cancel.is_set():
                    # Cancelled while queued behind the lock.
                    if not job.state.is_terminal:
                        job.transition(JobState.CANCELLED)
                        job.finished_at = _now()
                    return

                await self._run_locked(job, utility, environment, cancel)
            finally:
                if lock is not None:
                    lock.release()

        except asyncio.CancelledError:
            if not job.state.is_terminal:
                job.transition(JobState.CANCELLED)
                job.finished_at = _now()
            raise
        except Exception as exc:  # noqa: BLE001 — recorded on the job, not swallowed
            if not job.state.is_terminal:
                if job.state is JobState.QUEUED:
                    job.transition(JobState.RUNNING)
                job.transition(JobState.FAILED)
            job.error = f"{type(exc).__name__}: {exc}"
            job.finished_at = _now()
        finally:
            self._cancels.pop(job.id, None)
            self._tasks.pop(job.id, None)

    async def _run_locked(self, job, utility, environment, cancel) -> None:
        argv = build_argv(
            utility,
            environment,
            job.arguments,
            apply=job.apply,
            python=self._python,
        )

        job.transition(JobState.RUNNING)
        job.started_at = _now()
        self._store.append_output(job, f"[orchestrator] {' '.join(argv)}")

        # The audit record is written on every outcome, including a job that was
        # cancelled or failed — those are the runs you most need recorded. The
        # outcome is stated explicitly rather than signalled by raising.
        with AuditedRun(
            job.utility_id,
            environment,
            applied=job.apply,
            arguments=job.arguments,
            actor=job.requested_by,
            sink=self._audit_sink,
        ) as run:
            run.note(f"job {job.id}")
            if job.approved_by:
                run.note(f"approved by {job.approved_by}")

            exit_code = await self._runner.run(
                argv,
                lambda line: self._store.append_output(job, line),
                cancel,
            )

            job.exit_code = exit_code
            job.finished_at = _now()

            if cancel.is_set():
                job.transition(JobState.CANCELLED)
                run.mark_cancelled("cancelled while running")
            elif exit_code == 0:
                job.transition(JobState.SUCCEEDED)
            else:
                job.transition(JobState.FAILED)
                job.error = f"utility exited with code {exit_code}"
                run.mark_failed(job.error)
