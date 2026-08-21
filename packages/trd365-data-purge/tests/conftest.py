"""
Fixtures, and one guard that matters more than any of them.

The utilities decide where to write their audit trail, their checkpoints and the
data-model snapshot from environment variables, falling back to ``~/.trd365``.
That is right for a deployed host and wrong for a test run: a test that drives the
real CLI without injecting a sink writes a real audit record.

That is not hypothetical. It happened. The end-to-end tests in this package ran on
the maintenance VM as part of the deploy's test gate, where
``TRD365_AUDIT_DIR=/var/lib/trd365/audit``, and six invented purge runs appeared in
the production audit trail — the console showed ``purge-case`` and
``purge-interaction`` against dev, claiming success, at the moment of the deploy.

Injecting a sink per test fixes the test that remembers. Redirecting the
environment fixes the ones that do not, which is the point: an audit trail is
worth having only if everything in it is real.
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
    # A stray HOME write would land in the real ~/.trd365 if a lookup is ever
    # added that does not consult these three.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    yield tmp_path
