"""
Fixtures, and the guard this package was missing.

Most tests here drive an in-memory audit sink, which is why the omission went
unnoticed: the fixtures look isolated. But some exercise the real
:class:`AuditedRun`, and with no sink that writes to ``$TRD365_AUDIT_DIR`` — a
real directory on the maintenance VM, where this suite runs as the deploy's test
gate.

The result was eight fabricated records in the live audit trail, one per deploy:
``purge-account`` against ``dev``, ``applied: true``, actor ``ops@certainti.ai``,
account ``r-1``. All failed and none touched a database, so no data was at risk —
but an audit trail is worth exactly what its worst entry is worth, and "applied"
runs that never happened is a bad worst entry.

The same guard exists in the other three packages, added when the purge package
did this first. It was not copied here because these tests looked like they did
not need it. ``test_state_isolation.py`` now asserts every package has it, rather
than relying on the next person noticing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from trd365_core.audit import MemoryAuditSink
from trd365_core.registry import Registry

sys.path.insert(0, str(Path(__file__).parent))

from helpers import PURGE, REPORT, ScriptedRunner, principal  # noqa: E402

from trd365_orchestrator.jobs import JobStore  # noqa: E402
from trd365_orchestrator.scheduler import Scheduler  # noqa: E402
from trd365_orchestrator.security import Role  # noqa: E402
from trd365_orchestrator.service import Orchestrator, OrchestratorConfig  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Point every default write path inside this test's tmp_path."""
    for variable, name in (
        ("TRD365_AUDIT_DIR", "audit"),
        ("TRD365_STATE_DIR", "state"),
        ("TRD365_MODEL_DIR", "model"),
    ):
        monkeypatch.setenv(variable, str(tmp_path / name))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    yield tmp_path


@pytest.fixture
def registry():
    return Registry([PURGE, REPORT])


@pytest.fixture
def store():
    return JobStore()


@pytest.fixture
def audit():
    return MemoryAuditSink()


@pytest.fixture
def operator():
    return principal("alice", Role.OPERATOR)


@pytest.fixture
def approver():
    return principal("bob", Role.APPROVER)


@pytest.fixture
def viewer():
    return principal("carol", Role.VIEWER)


@pytest.fixture
def make_orchestrator(registry, store, audit):
    def _make(runner=None, *, authenticated=True, model_store=None):
        runner = runner or ScriptedRunner()
        scheduler = Scheduler(registry, store, runner, audit_sink=audit)
        return Orchestrator(
            registry,
            store,
            scheduler,
            model_store=model_store,
            audit_sink=audit,
            config=OrchestratorConfig(authentication_configured=authenticated),
            environ={},
        )

    return _make
