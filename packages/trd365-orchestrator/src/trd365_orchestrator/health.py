"""
Per-environment health, for the dashboard (PRD FR-4.5).

Three questions, answered independently so one failure does not hide the others:
is the environment configured, do its databases answer, and is its data model
fresh enough for the utilities to trust.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

from trd365_core.environments import DB_KEYS, Environment, configuration_status, describe
from trd365_core.model_snapshot import DEFAULT_MAX_AGE, ModelStore


@dataclass
class DatabaseHealth:
    db_key: str
    configured: bool
    reachable: bool | None = None  # None when not probed
    latency_ms: float | None = None
    database: str | None = None
    error: str | None = None


@dataclass
class ModelHealth:
    present: bool
    generated_at: str | None = None
    age_hours: float | None = None
    stale: bool | None = None
    schemas: int = 0
    tables: int = 0
    deviations: int = 0
    fingerprint: str | None = None


@dataclass
class EnvironmentHealth:
    environment: str
    configured: bool
    databases: list[DatabaseHealth] = field(default_factory=list)
    model: ModelHealth | None = None
    active_jobs: int = 0
    writer_busy: bool = False

    @property
    def status(self) -> str:
        """A single word for the dashboard tile, paired with a label and icon."""
        if not self.configured:
            return "unconfigured"
        if any(d.reachable is False for d in self.databases):
            return "critical"
        if self.model is None or not self.model.present or self.model.stale:
            return "warning"
        return "good"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status
        return data


def model_health(store: ModelStore, environment: Environment, max_age: timedelta) -> ModelHealth:
    snapshot = store.latest(environment)
    if snapshot is None:
        return ModelHealth(present=False)

    summary = snapshot.summary()
    return ModelHealth(
        present=True,
        generated_at=snapshot.generated_at,
        age_hours=round(snapshot.age.total_seconds() / 3600, 1),
        stale=snapshot.is_stale(max_age),
        schemas=summary["schemas"],
        tables=summary["tables"],
        deviations=summary["deviations"],
        fingerprint=snapshot.fingerprint,
    )


def environment_health(
    environment: Environment,
    *,
    model_store: ModelStore | None = None,
    pool_factory: Callable[[Environment], Any] | None = None,
    probe_databases: bool = False,
    max_model_age: timedelta = DEFAULT_MAX_AGE,
    active_jobs: int = 0,
    writer_busy: bool = False,
    environ: dict[str, str] | None = None,
) -> EnvironmentHealth:
    """
    Assemble one environment's health.

    Database probing is opt-in because it costs an SSH tunnel and a round trip
    per database; a dashboard poll should not open three tunnels every few
    seconds. Configuration and model status are cheap and always reported.
    """
    status = configuration_status(environ)[environment]
    health = EnvironmentHealth(
        environment=environment.value,
        configured=all(status.values()),
        active_jobs=active_jobs,
        writer_busy=writer_busy,
    )

    for db_key in DB_KEYS:
        configured = status[db_key]
        entry = DatabaseHealth(db_key=db_key, configured=configured)

        if configured and probe_databases and pool_factory is not None:
            started = time.monotonic()
            try:
                pool = pool_factory(environment)
                info = pool.verify(db_key)
                entry.reachable = True
                entry.latency_ms = round((time.monotonic() - started) * 1000, 1)
                entry.database = info.get("database")
            except Exception as exc:  # noqa: BLE001 — surfaced, not raised
                entry.reachable = False
                entry.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        elif not configured:
            entry.reachable = False
            entry.error = "credentials not configured"
        else:
            settings = describe(environment, db_key, environ)
            entry.database = settings.dbname

        health.databases.append(entry)

    if model_store is not None:
        health.model = model_health(model_store, environment, max_model_age)

    return health
