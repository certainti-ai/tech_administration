"""
That no test suite can write to the real audit trail.

This has now gone wrong twice. The utilities write through
:class:`~trd365_core.audit.AuditedRun`, which with no sink appends to
``$TRD365_AUDIT_DIR``; the model store saves to ``$TRD365_MODEL_DIR``. On the
maintenance VM those are real directories, and every package's tests run there as
the deploy's test gate — so a test that drives a real CLI writes a real audit
record on a real host, once per deploy, for as long as nobody looks.

The first time it was the purge package. The fix was a conftest fixture, copied
to two of the three remaining packages; the orchestrator was skipped because its
tests mostly use an in-memory sink and so looked like they did not need it. They
did: eight fabricated ``purge-account`` runs against ``dev``, marked applied,
accumulated in the live trail.

So the guard is no longer a convention. Any package that grows a tests directory
without it fails here, on a machine that has no audit trail to damage.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGES = Path(__file__).resolve().parents[3] / "packages"

#: Every variable that redirects a default write path. Adding one to the codebase
#: without adding it here leaves a hole of exactly the shape this file exists to
#: close.
REDIRECTS = ("TRD365_AUDIT_DIR", "TRD365_STATE_DIR", "TRD365_MODEL_DIR")


def conftests() -> list[Path]:
    found = sorted(PACKAGES.glob("*/tests/conftest.py"))
    assert found, f"no test packages found under {PACKAGES}"
    return found


def autouse_fixture_names(source: str) -> set[str]:
    """Names of fixtures declared ``autouse=True``, read from the syntax tree."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            for keyword in decorator.keywords:
                if (
                    keyword.arg == "autouse"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    names.add(node.name)
    return names


@pytest.mark.parametrize("conftest", conftests(), ids=lambda p: p.parts[-3])
class TestEveryPackageIsolatesItsWrites:
    def test_it_has_an_autouse_fixture(self, conftest):
        assert autouse_fixture_names(conftest.read_text()), (
            f"{conftest} has no autouse fixture, so nothing redirects its writes"
        )

    @pytest.mark.parametrize("variable", REDIRECTS)
    def test_it_redirects_every_write_path(self, conftest, variable):
        source = conftest.read_text()
        assert variable in source, f"{conftest} does not redirect {variable}"

    def test_the_redirection_is_autouse_rather_than_opt_in(self, conftest):
        # A fixture a test has to remember to request is not a guard.
        source = conftest.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in autouse_fixture_names(source):
                body = ast.get_source_segment(source, node) or ""
                if all(variable in body for variable in REDIRECTS):
                    return
        pytest.fail(f"{conftest} redirects the write paths, but not from an autouse fixture")

    def test_home_is_redirected_too(self, conftest):
        # The checkpoint store falls back to ~/.trd365 when TRD365_STATE_DIR is
        # unset, which is how a stray checkpoint reached a real home directory.
        assert '"HOME"' in conftest.read_text(), f"{conftest} does not redirect HOME"
