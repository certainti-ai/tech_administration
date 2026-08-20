"""
Resumable run state.

A purge of a large account runs for a long time and touches three databases. If
it dies partway, restarting from the beginning would re-scan everything already
deleted, and — worse — the id-sets it captured before deleting are gone, because
the rows they were read from no longer exist. So the checkpoint stores both what
has completed and the id-sets, and a resumed run continues from where it stopped
even if the entity's own anchor row is already deleted.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def default_state_dir() -> Path:
    """``$TRD365_STATE_DIR`` if set, else ``~/.trd365/state``."""
    base = os.environ.get("TRD365_STATE_DIR")
    return Path(base) if base else Path.home() / ".trd365" / "state"


@dataclass
class Checkpoint:
    """One purge run's resumable state."""

    entity: str
    entity_rid: str
    environment: str
    run_id: str
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    resolved: dict[str, Any] = field(default_factory=dict)
    id_sets: dict[str, list] = field(default_factory=dict)
    completed: dict[str, list[str]] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    steps_meta: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    audit_clean: bool | None = None
    finished_at: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "entity_rid": self.entity_rid,
            "environment": self.environment,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "resolved": self.resolved,
            "id_sets": self.id_sets,
            "completed": self.completed,
            "metrics": self.metrics,
            "steps_meta": self.steps_meta,
            "findings": self.findings,
            "audit_clean": self.audit_clean,
            "finished_at": self.finished_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def tables_completed(self) -> int:
        return sum(len(v) for v in self.completed.values())


class CheckpointStore:
    """Checkpoints as JSON files, one per entity row, written atomically."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_state_dir()

    def path_for(self, environment: str, entity: str, entity_rid: str) -> Path:
        # The rid is used in a filename, so anything path-shaped is neutralised.
        safe_rid = "".join(c if c.isalnum() or c in "-_" else "_" for c in entity_rid)[:120]
        return self.root / environment / entity / f"{safe_rid}.json"

    def load(self, environment: str, entity: str, entity_rid: str) -> Checkpoint | None:
        path = self.path_for(environment, entity, entity_rid)
        if not path.exists():
            return None
        try:
            return Checkpoint.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            # A corrupt checkpoint must not block a rerun; starting over is
            # correct and safe, because the purge is idempotent per table.
            return None

    def save(self, checkpoint: Checkpoint) -> Path:
        path = self.path_for(checkpoint.environment, checkpoint.entity, checkpoint.entity_rid)
        path.parent.mkdir(parents=True, exist_ok=True)

        handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                json.dump(checkpoint.to_dict(), fh, indent=2, default=str)
            os.replace(temp_name, path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        return path

    def clear(self, environment: str, entity: str, entity_rid: str) -> None:
        self.path_for(environment, entity, entity_rid).unlink(missing_ok=True)
