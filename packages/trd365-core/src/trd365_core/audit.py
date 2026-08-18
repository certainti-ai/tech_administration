"""
Append-only audit records.

Every invocation of every utility produces one record: who, what, where, when,
with which arguments, and what changed. The estate previously had no way to
answer "who purged this account?" — this is that answer.

Records are append-only by construction: there is no update or delete path.
The sink is pluggable so Phase 2 can write to a database without any utility
changing; the JSONL sink is the default and needs no infrastructure.
"""

from __future__ import annotations

import getpass
import json
import os
import socket
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .environments import Environment

SENSITIVE_ARG_HINTS = ("password", "secret", "token", "pat", "credential")
REDACTED = "***"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def redact_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Strip anything credential-shaped before it reaches the log.

    The audit log is the one artefact guaranteed to be read later and kept, so
    it is the worst possible place for a password to land.
    """
    cleaned: dict[str, Any] = {}
    for key, value in arguments.items():
        if any(hint in key.lower() for hint in SENSITIVE_ARG_HINTS):
            cleaned[key] = REDACTED
        else:
            cleaned[key] = value
    return cleaned


@dataclass
class RunRecord:
    """One invocation of one utility."""

    run_id: str
    utility: str
    environment: str
    actor: str
    host: str
    applied: bool
    started_at: str
    arguments: dict[str, Any] = field(default_factory=dict)
    finished_at: str | None = None
    outcome: str | None = None
    error: str | None = None
    #: Rows affected per fully-qualified table, e.g. ``{"trd365_00042.project": 12}``.
    rows_affected: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def mode(self) -> str:
        return "apply" if self.applied else "dry-run"

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, default=str)


class AuditSink(Protocol):
    def write(self, record: RunRecord) -> None: ...


class JsonlAuditSink:
    """Append records to a JSONL file, one line each."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: RunRecord) -> None:
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(record.to_json() + "\n")


class MemoryAuditSink:
    """Collects records in memory. For tests, and for previewing in the UI."""

    def __init__(self) -> None:
        self.records: list[RunRecord] = []

    def write(self, record: RunRecord) -> None:
        self.records.append(record)


def default_audit_path() -> Path:
    """``$TRD365_AUDIT_DIR`` if set, else ``~/.trd365/audit``."""
    base = os.environ.get("TRD365_AUDIT_DIR")
    return (Path(base) if base else Path.home() / ".trd365" / "audit") / "runs.jsonl"


class AuditedRun:
    """
    Context manager wrapping one utility invocation.

    The record is written on exit whether the run succeeded, failed or was
    interrupted — a purge that crashed halfway is precisely the one you need
    the record for.

        with AuditedRun("purge-account", env, applied=args.apply) as run:
            run.record_rows("trd365_00042.project", 12)
    """

    def __init__(
        self,
        utility: str,
        environment: Environment,
        *,
        applied: bool,
        arguments: dict[str, Any] | None = None,
        actor: str | None = None,
        sink: AuditSink | None = None,
    ) -> None:
        self.record = RunRecord(
            run_id=str(uuid.uuid4()),
            utility=utility,
            environment=environment.value,
            actor=actor or self._default_actor(),
            host=socket.gethostname(),
            applied=applied,
            started_at=_now(),
            arguments=redact_arguments(arguments or {}),
        )
        self._sink = sink if sink is not None else JsonlAuditSink(default_audit_path())
        self._outcome_override: str | None = None

    @staticmethod
    def _default_actor() -> str:
        try:
            return getpass.getuser()
        except Exception:  # noqa: BLE001 — no controlling terminal in a service
            return os.environ.get("USER") or "unknown"

    def record_rows(self, qualified_table: str, count: int) -> None:
        self.record.rows_affected[qualified_table] = (
            self.record.rows_affected.get(qualified_table, 0) + count
        )

    def note(self, message: str) -> None:
        self.record.notes.append(message)

    def mark_cancelled(self, message: str | None = None) -> None:
        """
        Record this run as cancelled without raising.

        A caller that already knows the run was cancelled — an orchestrator
        acting on a cancellation signal, say — should not have to throw to say
        so. Using an exception for that would mean either raising
        ``KeyboardInterrupt`` (a ``BaseException``, which escapes ordinary
        handling) or having the cancellation recorded as a failure.
        """
        self._outcome_override = "cancelled"
        if message:
            self.note(message)

    def mark_failed(self, message: str) -> None:
        """Record this run as failed without raising."""
        self._outcome_override = "failed"
        self.record.error = message

    @property
    def total_rows(self) -> int:
        return sum(self.record.rows_affected.values())

    def __enter__(self) -> AuditedRun:
        return self

    def __exit__(self, exc_type, exc, _tb) -> bool:
        self.record.finished_at = _now()
        if exc_type is None:
            # An exception always wins over an override: something went wrong
            # that the caller did not know about when it marked the outcome.
            self.record.outcome = self._outcome_override or "success"
        elif isinstance(exc, KeyboardInterrupt):
            self.record.outcome = "cancelled"
        else:
            self.record.outcome = "failed"
            self.record.error = f"{exc_type.__name__}: {exc}"
        self._sink.write(self.record)
        return False  # never swallow the exception


def read_records(path: str | Path) -> list[RunRecord]:
    """Read a JSONL audit file back. Malformed lines are skipped, not fatal."""
    file_path = Path(path)
    if not file_path.exists():
        return []

    records: list[RunRecord] = []
    with open(file_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(RunRecord(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue
    return records
