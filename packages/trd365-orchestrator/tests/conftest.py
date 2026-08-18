"""Fixtures. Shared doubles live in helpers.py."""

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
