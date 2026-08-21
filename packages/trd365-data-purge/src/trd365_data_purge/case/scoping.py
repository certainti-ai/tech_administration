"""
Case scoping — build the WHERE clause that selects exactly one case's rows.

Ported from ``legacy/trd365_maintenance/data_purge/case/scoping_case.py``,
keeping its rules intact. Two things changed in the port:

* schema metadata comes from the run-scoped :class:`~trd365_data_purge.engine.SchemaCache`
  keyed by database, rather than module-level dicts keyed by ``(schema, table)``
  that could serve one database's metadata for another;
* the special cases are a table of named predicates instead of a chain of ``if``
  statements inside ``predicate``, which is how ``account/scoping.py`` is built —
  the two entities now read the same way.

The rule, in one sentence: a table belongs to the case if it carries
``case_rid``, or if it has a foreign key into a table that does. Anything that
satisfies neither is reported **unscoped** and left completely untouched.

There is deliberately no discovery here. The account purge widens its manifest
from live introspection because an account owns whole schemas' worth of tables
and new ones appear; a case owns a known subtree, and a table that merely
mentions ``case_rid`` is not necessarily owned by the case — ``chat_sessions`` is
the standing example on the interaction side. Guessing would delete rows that
should survive the case, so the manifest is the whole scope.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from trd365_core.datamodel import PK_COLUMN

from ..account.scoping import ResolvedAccount, resolve_account_reference
from ..engine import SchemaCache, quote
from . import manifest as M

#: Which database each schema kind lives in.
DB_FOR_KIND: dict[str, str] = {"org": "orgdb", "main": "maindb"}

#: The schemas that do not depend on which account is being purged.
FIXED_SCHEMAS: dict[str, str] = {"main": M.MAIN_SCHEMA}

#: A predicate that can never match, used when a table's parent is absent.
NEVER: tuple[str, list] = ("1=0", [])


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


@dataclass
class ResolvedCase:
    """A case, and the account schema its rows live in."""

    rid: str
    exists: bool
    account: ResolvedAccount
    org_schema: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rid": self.rid,
            "exists": self.exists,
            "org_schema": self.org_schema,
            "account_rid": self.account.rid,
            "r_number": self.account.r_number,
        }


def resolve_case(pool, cache: SchemaCache, account_ref: str, case_rid: str) -> ResolvedCase:
    """
    Find the case inside the account it was said to belong to.

    The account has to be resolved first because a case's rows live in that
    account's org schema, and which schema that is depends on the account's
    storage type. The case is then confirmed to exist *in that schema*: a rid
    that exists in a different tenant's schema must not resolve here, or the
    purge would run its whole manifest against the wrong tenant and delete
    nothing while reporting success.
    """
    account = resolve_account_reference(pool, account_ref)
    if not account.exists:
        return ResolvedCase(rid=case_rid, exists=False, account=account)

    schema = account.org_schema
    conn = pool.get(DB_FOR_KIND["org"])

    if not cache.table_exists(conn, DB_FOR_KIND["org"], schema, "cases"):
        return ResolvedCase(rid=case_rid, exists=False, account=account, org_schema=schema)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {PK_COLUMN} FROM {quote(schema)}.{quote('cases')} "
            f"WHERE {PK_COLUMN}=%s",
            (case_rid,),
        )
        found = cur.fetchone()
    conn.rollback()

    return ResolvedCase(
        rid=case_rid,
        exists=bool(found),
        account=account,
        org_schema=schema,
    )


# ---------------------------------------------------------------------------
# predicates
# ---------------------------------------------------------------------------


@dataclass
class ScopeContext:
    """What a predicate needs to inspect the schema it is scoping against."""

    conn: Any
    cache: SchemaCache
    db_key: str
    schema: str
    rid: str

    def exists(self, table: str) -> bool:
        return self.cache.table_exists(self.conn, self.db_key, self.schema, table)

    def columns(self, table: str) -> set[str]:
        return self.cache.columns(self.conn, self.db_key, self.schema, table)

    def fks(self, table: str) -> list[tuple]:
        return self.cache.single_column_fks(self.conn, self.db_key, self.schema, table)

    def qualified(self, table: str) -> str:
        return f"{quote(self.schema)}.{quote(table)}"


Predicate = tuple[str, list]
SpecialPredicate = Callable[[ScopeContext], Predicate]


def _checklist_items(ctx: ScopeContext) -> Predicate:
    # No case_rid of its own; an item belongs to a checklist, and the checklist
    # belongs to the case.
    if not ctx.exists("checklists"):
        return NEVER
    return (
        f"checklist_rid IN (SELECT {PK_COLUMN} FROM {ctx.qualified('checklists')} "
        f"WHERE case_rid = %s)",
        [ctx.rid],
    )


SPECIAL_PREDICATES: dict[str, SpecialPredicate] = {
    "cases": lambda ctx: (f"{PK_COLUMN} = %s", [ctx.rid]),
    "checklist_items": _checklist_items,
}


# ---------------------------------------------------------------------------
# the scoper the engine drives
# ---------------------------------------------------------------------------


class CaseScoper:
    """
    Turns ``(schema, table, kind)`` into the WHERE clause selecting this case's
    rows, or ``None`` when the table cannot be tied to the case.

    Returning ``None`` is the important behaviour: the engine leaves such a table
    completely untouched and the report lists it for a human.
    """

    def __init__(self, case: ResolvedCase, cache: SchemaCache) -> None:
        self.case = case
        self.cache = cache
        self.rid = case.rid

    def _context(self, conn, schema: str, kind: str) -> ScopeContext:
        return ScopeContext(
            conn=conn,
            cache=self.cache,
            db_key=DB_FOR_KIND[kind],
            schema=schema,
            rid=self.rid,
        )

    def discover(self, conn, schema: str, kind: str, manifest_tables) -> list[str]:
        """Nothing: the manifest is the whole scope. See the module docstring."""
        return []

    def predicate(self, conn, schema: str, table: str, kind: str) -> Predicate | None:
        ctx = self._context(conn, schema, kind)

        special = SPECIAL_PREDICATES.get(table)
        if special is not None:
            return special(ctx)

        if "case_rid" in ctx.columns(table):
            return "case_rid = %s", [self.rid]

        # Otherwise: a foreign key into something that does carry case_rid. The
        # subselect rather than a join keeps the clause usable as a WHERE on the
        # table being deleted, which is what the engine backs up and counts.
        conditions: list[str] = []
        params: list = []
        for local_col, ref_table, ref_col in ctx.fks(table):
            if not local_col or ref_table == table:
                continue
            if "case_rid" in ctx.columns(ref_table):
                conditions.append(
                    f"{quote(local_col)} IN (SELECT {quote(ref_col)} FROM "
                    f"{ctx.qualified(ref_table)} WHERE case_rid = %s)"
                )
                params.append(self.rid)

        if conditions:
            return " OR ".join(conditions), params
        return None
