"""
Case scoping — which rows belong to one case.

Ported from ``legacy/trd365_maintenance/data_purge/case/scoping_case.py``, with
its rules intact. The mechanics live in :mod:`trd365_data_purge.subtree`, which
every purge of something inside an account shares; what is specific to a case is
here, and it is short:

* the anchor is ``cases``;
* the owning column is ``case_rid``;
* ``checklist_items`` has no ``case_rid`` and reaches the case through
  ``checklists``;
* foreign keys **are** followed, because every FK-reachable table in this subtree
  is genuinely owned by the case.

The rule, in one sentence: a table belongs to the case if it carries ``case_rid``,
or if it has a foreign key into a table that does. Anything satisfying neither is
reported **unscoped** and left completely untouched.
"""

from __future__ import annotations

from ..engine import SchemaCache
from ..subtree import (
    DB_FOR_KIND,
    NEVER,
    Predicate,
    ResolvedChild,
    ScopeContext,
    SpecialPredicate,
    SubtreeScoper,
    by_primary_key,
    resolve_child,
    resumed_from,
    via_parent,
)
from . import manifest as M

__all__ = [
    "DB_FOR_KIND",
    "FIXED_SCHEMAS",
    "NEVER",
    "OWNER_COLUMN",
    "SPECIAL_PREDICATES",
    "CaseScoper",
    "Predicate",
    "ResolvedChild",
    "ScopeContext",
    "SpecialPredicate",
    "resolve_case",
    "resumed_from",
]

#: The table holding the case itself.
ANCHOR = "cases"

#: The column that names the owning case on a table the case owns.
OWNER_COLUMN = "case_rid"

#: The schemas that do not depend on which account is being purged.
FIXED_SCHEMAS: dict[str, str] = {"main": M.MAIN_SCHEMA}

SPECIAL_PREDICATES: dict[str, SpecialPredicate] = {
    ANCHOR: by_primary_key,
    # No case_rid of its own: an item belongs to a checklist, and the checklist
    # belongs to the case.
    "checklist_items": via_parent("checklists", "checklist_rid", OWNER_COLUMN),
}


def resolve_case(pool, cache: SchemaCache, account_ref: str, case_rid: str) -> ResolvedChild:
    """Find the case inside the account it was said to belong to."""
    return resolve_child(pool, cache, account_ref=account_ref, anchor=ANCHOR, rid=case_rid)


class CaseScoper(SubtreeScoper):
    """The scoper the engine drives for a case purge."""

    def __init__(self, case: ResolvedChild, cache: SchemaCache) -> None:
        super().__init__(
            child=case,
            cache=cache,
            owner_column=OWNER_COLUMN,
            specials=SPECIAL_PREDICATES,
            # Followed: `checklist_items` aside, this subtree's FK-reachable
            # tables are all genuinely case-owned. Contrast the interaction
            # manifest, where following links would delete rows meant to survive.
            follow_foreign_keys=True,
        )
