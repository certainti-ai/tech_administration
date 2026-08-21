"""
Fixtures, and the guard every utility package needs.

``AuditedRun`` with no sink writes to ``$TRD365_AUDIT_DIR``, which on the
maintenance VM is a real directory, and this package's tests run there as part of
the deploy's test gate. See ``packages/trd365-data-purge/tests/conftest.py`` for
what happened the one time this was missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    for variable, name in (
        ("TRD365_AUDIT_DIR", "audit"),
        ("TRD365_STATE_DIR", "state"),
        ("TRD365_MODEL_DIR", "model"),
    ):
        monkeypatch.setenv(variable, str(tmp_path / name))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    yield tmp_path
