"""
Interaction scoping — which rows belong to one interaction.

Ported from ``legacy/trd365_maintenance/data_purge/interaction/
scoping_interaction.py``, with its rules intact. The mechanics live in
:mod:`trd365_data_purge.subtree`; what is specific to an interaction is here:

* the anchor is ``interactions``;
* the owning column is ``interaction_rid``;
* ``interaction_timeline`` points at the interaction with a generic
  ``entity_rid`` instead;
* ``interaction_response_history`` is reachable two ways at once — directly, and
  through the item the response was to;
* foreign keys are **not** followed. See below.

**Why foreign keys are not followed here.** ``chat_sessions`` carries an
``interaction_rid`` with no foreign key behind it: it is a soft reference from a
conversation that is meant to outlive the interaction it was started from. Any
rule general enough to pull in FK-reachable tables would pull that in too, and
deleting it would destroy chat history the interaction does not own. So the
manifest is the entire scope and the owning column is the entire rule. The
legacy tool made the same choice, and said so in a comment in capital letters.
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
    by_column,
    by_primary_key,
    resolve_child,
    resumed_from,
)
from . import manifest as M

__all__ = [
    "DB_FOR_KIND",
    "FIXED_SCHEMAS",
    "NEVER",
    "OWNER_COLUMN",
    "SPECIAL_PREDICATES",
    "InteractionScoper",
    "Predicate",
    "ResolvedChild",
    "ScopeContext",
    "SpecialPredicate",
    "resolve_interaction",
    "resumed_from",
]

#: The table holding the interaction itself.
ANCHOR = "interactions"

#: The column that names the owning interaction on a table it owns.
OWNER_COLUMN = "interaction_rid"

#: The schemas that do not depend on which account is being purged.
FIXED_SCHEMAS: dict[str, str] = {"main": M.MAIN_SCHEMA}


def _response_history(ctx: ScopeContext) -> Predicate:
    """
    Responses reach the interaction directly *and* through the item answered.

    Both paths are needed, not either: a row can carry an
    ``interaction_item_rid`` and no ``interaction_rid``, or the reverse. Taking
    one path alone leaves rows behind, which the audit then reports as residual.
    """
    sql = f"{OWNER_COLUMN} = %s"
    params = [ctx.rid]
    if ctx.exists("interaction_items"):
        sql += (
            f" OR interaction_item_rid IN (SELECT rid FROM "
            f"{ctx.qualified('interaction_items')} WHERE {OWNER_COLUMN} = %s)"
        )
        params.append(ctx.rid)
    return sql, params


SPECIAL_PREDICATES: dict[str, SpecialPredicate] = {
    ANCHOR: by_primary_key,
    # Timeline rows name their subject generically rather than by interaction.
    "interaction_timeline": by_column("entity_rid"),
    "interaction_response_history": _response_history,
}


def resolve_interaction(
    pool, cache: SchemaCache, account_ref: str, interaction_rid: str
) -> ResolvedChild:
    """Find the interaction inside the account it was said to belong to."""
    return resolve_child(
        pool, cache, account_ref=account_ref, anchor=ANCHOR, rid=interaction_rid
    )


class InteractionScoper(SubtreeScoper):
    """The scoper the engine drives for an interaction purge."""

    def __init__(self, interaction: ResolvedChild, cache: SchemaCache) -> None:
        super().__init__(
            child=interaction,
            cache=cache,
            owner_column=OWNER_COLUMN,
            specials=SPECIAL_PREDICATES,
            # Not followed. chat_sessions carries an interaction_rid it does not
            # own; see the module docstring.
            follow_foreign_keys=False,
        )
