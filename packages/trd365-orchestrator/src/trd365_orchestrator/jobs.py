"""
Job records: what was asked for, what happened, and what it changed.

A job is created the moment someone asks for a run and outlives the process that
executed it. Terminal states are final — a completed job is never edited, only
read — which is what makes the audit trail trustworthy.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from trd365_core.audit import redact_arguments
from trd365_core.environments import Environment
from trd365_core.errors import Trd365Error


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JobState(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

    @property
    def is_terminal(self) -> bool:
        return self in {
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.REJECTED,
        }

    @property
    def is_active(self) -> bool:
        return self in {JobState.QUEUED, JobState.RUNNING}


class InvalidJobTransition(Trd365Error):
    """A job was moved to a state it cannot reach from where it is."""


#: The only legal moves. Anything else is a bug, and is rejected loudly rather
#: than quietly corrupting the record of what happened.
_ALLOWED: dict[JobState, set[JobState]] = {
    JobState.PENDING_APPROVAL: {JobState.QUEUED, JobState.REJECTED, JobState.CANCELLED},
    JobState.QUEUED: {JobState.RUNNING, JobState.CANCELLED},
    JobState.RUNNING: {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED},
    JobState.SUCCEEDED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
    JobState.REJECTED: set(),
}


@dataclass
class Job:
    id: str
    utility_id: str
    environment: str
    apply: bool
    arguments: dict[str, Any]
    requested_by: str
    requested_at: str
    state: JobState = JobState.QUEUED
    approved_by: str | None = None
    approved_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error: str | None = None
    rows_affected: dict[str, int] = field(default_factory=dict)
    output: list[str] = field(default_factory=list)

    @property
    def mode(self) -> str:
        return "apply" if self.apply else "dry-run"

    @property
    def env(self) -> Environment:
        return Environment.parse(self.environment)

    def transition(self, to: JobState) -> None:
        if to not in _ALLOWED[self.state]:
            raise InvalidJobTransition(
                f"Job {self.id} cannot move from {self.state.value} to {to.value}."
            )
        self.state = to

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        data["mode"] = self.mode
        return data


def new_job(
    *,
    utility_id: str,
    environment: Environment,
    apply: bool,
    arguments: dict[str, Any],
    requested_by: str,
    needs_approval: bool,
) -> Job:
    return Job(
        id=str(uuid.uuid4()),
        utility_id=utility_id,
        environment=environment.value,
        apply=apply,
        # Redacted at creation, not at display: a credential that never enters
        # the record cannot leak out of it later.
        arguments=redact_arguments(arguments),
        requested_by=requested_by,
        requested_at=_now(),
        state=JobState.PENDING_APPROVAL if needs_approval else JobState.QUEUED,
    )


class JobStore:
    """
    In-memory job index, newest first.

    The durable record of what ran is the audit log (``trd365_core.audit``);
    this is the live view the API and UI read. Phase 4 can back it with a
    database without changing callers.
    """

    def __init__(self, max_output_lines: int = 2000) -> None:
        self._jobs: dict[str, Job] = {}
        self._max_output_lines = max_output_lines

    def add(self, job: Job) -> Job:
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job:
        try:
            return self._jobs[job_id]
        except KeyError:
            raise Trd365Error(f"No job {job_id}.") from None

    def list(
        self,
        *,
        environment: Environment | None = None,
        state: JobState | None = None,
        utility_id: str | None = None,
        limit: int = 100,
    ) -> list[Job]:
        jobs = sorted(self._jobs.values(), key=lambda j: j.requested_at, reverse=True)
        if environment is not None:
            jobs = [j for j in jobs if j.environment == environment.value]
        if state is not None:
            jobs = [j for j in jobs if j.state is state]
        if utility_id is not None:
            jobs = [j for j in jobs if j.utility_id == utility_id]
        return jobs[:limit]

    def active(self, environment: Environment | None = None) -> list[Job]:
        return [j for j in self.list(environment=environment, limit=10_000) if j.state.is_active]

    def append_output(self, job: Job, line: str) -> None:
        """
        Keep the tail of long output.

        A multi-hour purge can emit far more than anyone will read, and holding
        all of it would grow without bound; the end is the part that explains
        how a job finished.
        """
        job.output.append(line)
        if len(job.output) > self._max_output_lines:
            dropped = len(job.output) - self._max_output_lines
            del job.output[:dropped]
            job.output[0] = f"[… {dropped} earlier line(s) dropped …]"
