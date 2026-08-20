"""
The manifest is data, not code, and it came from the vendor's SECTION files.

These tests exist to catch an edit to it, not to restate it: the ordering is the
only thing standing between a purge and a wall of foreign-key violations, and it
was derived by someone reading the vendor's SQL. If a table moves, that should
be a deliberate act with a reason, and this test is where the reason gets
written down.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from trd365_core.datamodel import DEFAULT_MAIN_SCHEMA, TENANT_SCHEMA_LIKE

from trd365_data_purge.account import manifest as M

LEGACY = (
    Path(__file__).resolve().parents[3]
    / "legacy"
    / "trd365_maintenance"
    / "data_purge"
    / "account"
    / "manifest.py"
)


def legacy_list(name: str) -> list[str]:
    """Read a list literal out of the legacy manifest without importing it."""
    tree = ast.parse(LEGACY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id == name:  # type: ignore[attr-defined]
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {LEGACY}")


@pytest.mark.skipif(not LEGACY.exists(), reason="legacy tree not vendored in this checkout")
@pytest.mark.parametrize(
    ("ported", "name"),
    [(M.ORG_TABLES, "ORG_TABLES"), (M.MAIN_TABLES, "MAIN_TABLES"), (M.AI_TABLES, "AI_TABLES")],
)
def test_tables_are_the_legacy_order_exactly(ported, name):
    assert ported == legacy_list(name)


def test_no_table_is_listed_twice():
    for name, tables in (
        ("org", M.ORG_TABLES),
        ("main", M.MAIN_TABLES),
        ("ai", M.AI_TABLES),
    ):
        duplicates = {t for t in tables if tables.count(t) > 1}
        assert not duplicates, f"{name} lists {duplicates} more than once"


def test_parents_come_after_their_children():
    # A spot-check of the invariant the whole ordering exists for: an account's
    # own row goes last, and each entity's table follows the tables that point at it.
    assert M.MAIN_TABLES[-1] == "account"
    assert M.ORG_TABLES.index("cases") > M.ORG_TABLES.index("case_history")
    assert M.ORG_TABLES.index("project") > M.ORG_TABLES.index("project_fiscal")
    assert M.ORG_TABLES.index("resources") > M.ORG_TABLES.index("resource_fiscal")


def test_steps_run_org_then_main_then_ai():
    assert [step for (step, _db, _kind, _t) in M.STEPS] == [
        "org_delete",
        "main_delete",
        "ai_delete",
    ]
    assert [db for (_s, db, _k, _t) in M.STEPS] == ["orgdb", "maindb", "trd365ai"]


def test_main_schema_comes_from_the_shared_data_model():
    assert M.MAIN_SCHEMA == DEFAULT_MAIN_SCHEMA


def test_org_schema_prefix_matches_the_tenant_pattern():
    # The analysis finds tenant schemas with TENANT_SCHEMA_LIKE; the purge builds
    # one by name. If those two ever disagree the purge targets a schema the
    # analysis has never modelled.
    assert M.TENANT_SCHEMA_PREFIX.replace("_", r"\_") + "%" == TENANT_SCHEMA_LIKE


@pytest.mark.parametrize(
    ("r_number", "expected"),
    [
        ("ACC-00042", "trd365_00042"),
        ("00042", "trd365_00042"),
        (None, "trd365_"),
    ],
)
def test_org_schema_for(r_number, expected):
    assert M.org_schema_for(r_number) == expected
