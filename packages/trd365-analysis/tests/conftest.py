"""
Fixtures, and the same guard the purge package needs.

``AuditedRun`` with no sink writes to ``$TRD365_AUDIT_DIR``, and the model store
saves to ``$TRD365_MODEL_DIR``. On the maintenance VM both point at real
directories, and this package's tests run there as part of the deploy's test
gate — so a test that drives the real CLI would write a real audit record and
could publish a snapshot the other utilities then trust.

See ``packages/trd365-data-purge/tests/conftest.py`` for what happened when this
was missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


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
