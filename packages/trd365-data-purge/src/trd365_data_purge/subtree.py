"""
The shape shared by every purge of something *inside* an account.

An account purge is its own thing: it owns whole schemas, its scope is discovered
as well as declared, and it reaches trd365ai through id-sets captured before
anything is deleted. A case, an interaction, a project — anything below the
account — is much simpler and always the same simple thing:

1. resolve the account, because that decides which org schema to look in;
2. confirm the target exists **in that schema**, so a rid belonging to another
   tenant cannot resolve here;
3. scope each table by the column that names the owner, with a handful of
   named exceptions for the tables that reach it some other way.

That is what this module holds. An entity package supplies the parts that differ
— the anchor table, the owning column, its exceptions, and whether foreign keys
may be followed — and gets resolution, the checkpoint-resume path and the scoper
for free.

Whether foreign keys may be followed is a real decision, not a default. A case
follows them: ``checklist_items`` reaches the case only through ``checklists``,
and every FK-reachable table there is genuinely owned. An interaction does not:
``chat_sessions`` carries an ``interaction_rid`` without owning anything, so
following links would delete conversations that are meant to outlive the
interaction. Each entity says which it is, in one flag, next to the reason.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from trd365_core.datamodel import PK_COLUMN

from .account.scoping import ResolvedAccount, resolve_account_reference
from .engine import SchemaCache, quote

#: Which database each schema kind lives in. Sub-account entities never touch
#: trd365ai: it holds no link back to an org schema finer than a project fiscal.
DB_FOR_KIND: dict[str, str] = {"org": "orgdb", "main": "maindb"}

#: A predicate that can never match. Distinct from ``None``, which means "this
#: could not be worked out and a human should look": a table whose parent is
#: absent is *known* to hold nothing belonging to the target.
NEVER: tuple[str, list] = ("1=0", [])


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


@dataclass
class ResolvedChild:
    """A target inside an account, and the schema its rows live in."""

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


def resolve_child(
    pool, cache: SchemaCache, *, account_ref: str, anchor: str, rid: str
) -> ResolvedChild:
    """
    Find ``rid`` in ``anchor``, inside the schema belonging to ``account_ref``.

    The account is resolved first because which org schema to look in depends on
    its storage type. The target is then confirmed to be *in that schema*: a rid
    that exists in a different tenant's schema must not resolve here, or the run
    would execute its whole manifest against the wrong tenant, delete nothing,
    and report success.
    """
    account = resolve_account_reference(pool, account_ref)
    if not account.exists:
        return ResolvedChild(rid=rid, exists=False, account=account)

    schema = account.org_schema
    db_key = DB_FOR_KIND["org"]
    conn = pool.get(db_key)

    if not cache.table_exists(conn, db_key, schema, anchor):
        return ResolvedChild(rid=rid, exists=False, account=account, org_schema=schema)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {PK_COLUMN} FROM {quote(schema)}.{quote(anchor)} WHERE {PK_COLUMN}=%s",
            (rid,),
        )
        found = cur.fetchone()
    conn.rollback()

    return ResolvedChild(rid=rid, exists=bool(found), account=account, org_schema=schema)


def resumed_from(saved, rid: str) -> ResolvedChild | None:
    """
    Rebuild a target from a checkpoint, or ``None`` if the checkpoint cannot.

    Every sub-account purge deletes its anchor row in the **first** step, so a run
    interrupted after that point can never resolve itself again. The org schema is
    the only thing resolution contributes, so a checkpoint carrying it is enough —
    and without it the remaining rows would be stranded with no way to reach them.
    """
    if saved is None or not saved.resolved.get("org_schema"):
        return None
    schema = saved.resolved["org_schema"]
    return ResolvedChild(
        rid=rid,
        exists=True,
        account=ResolvedAccount(
            rid=saved.resolved.get("account_rid", ""),
            exists=True,
            r_number=saved.resolved.get("r_number"),
            org_schema=schema,
        ),
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

# On quoting: identifiers that came from the database are quoted, identifiers
# written here are not. A table name or an FK column read out of the catalog could
# be anything and has to be quoted to be safe; ``case_rid`` and ``checklist_rid``
# are literals in this file. Quoting those too would only make the SQL in a report
# harder to read, and would be inconsistent with the account scoper, which emits a
# bare ``account_rid = %s``.


def via_parent(parent: str, local_column: str, owner_column: str) -> SpecialPredicate:
    """
    A table that reaches the target only through a parent that names it.

    ``checklist_items`` is the standing example: it has no ``case_rid``, but its
    ``checklist_rid`` points at a ``checklists`` row that has one.
    """

    def predicate(ctx: ScopeContext) -> Predicate:
        if not ctx.exists(parent):
            return NEVER
        return (
            f"{local_column} IN (SELECT {PK_COLUMN} FROM {ctx.qualified(parent)} "
            f"WHERE {owner_column} = %s)",
            [ctx.rid],
        )

    return predicate


def by_primary_key(ctx: ScopeContext) -> Predicate:
    """The anchor row itself."""
    return f"{PK_COLUMN} = %s", [ctx.rid]


def by_column(column: str) -> SpecialPredicate:
    """A named column holding the target's rid directly."""
    return lambda ctx: (f"{column} = %s", [ctx.rid])


# ---------------------------------------------------------------------------
# the scoper the engine drives
# ---------------------------------------------------------------------------


@dataclass
class SubtreeScoper:
    """
    Turns ``(schema, table, kind)`` into the WHERE clause selecting the target's
    rows, or ``None`` when the table cannot be tied to it.

    Returning ``None`` is the important behaviour: the engine leaves such a table
    completely untouched and the report lists it for a human. A purge that guessed
    there would delete somebody else's rows.
    """

    child: ResolvedChild
    cache: SchemaCache
    #: The column that names the owner on a table it owns — ``case_rid``, and so on.
    owner_column: str
    #: Tables that reach the owner some other way, by name.
    specials: dict[str, SpecialPredicate] = field(default_factory=dict)
    #: Whether a table may be scoped through a foreign key into something that
    #: does carry ``owner_column``. See the module docstring: this is a decision.
    follow_foreign_keys: bool = False

    @property
    def rid(self) -> str:
        return self.child.rid

    def _context(self, conn, schema: str, kind: str) -> ScopeContext:
        return ScopeContext(
            conn=conn,
            cache=self.cache,
            db_key=DB_FOR_KIND[kind],
            schema=schema,
            rid=self.rid,
        )

    def discover(self, conn, schema: str, kind: str, manifest_tables) -> list[str]:
        """
        Nothing. The manifest is the whole scope.

        The account purge widens its manifest from live introspection because an
        account owns whole schemas' worth of tables and new ones appear. A
        sub-account entity owns a known subtree, and a table that merely mentions
        its rid is not necessarily owned by it — see ``NOT_OWNED`` in the
        interaction manifest for the case that proves it.
        """
        return []

    def predicate(self, conn, schema: str, table: str, kind: str) -> Predicate | None:
        ctx = self._context(conn, schema, kind)

        special = self.specials.get(table)
        if special is not None:
            return special(ctx)

        if self.owner_column in ctx.columns(table):
            return f"{self.owner_column} = %s", [self.rid]

        if not self.follow_foreign_keys:
            return None

        # A foreign key into something that does carry the owning column. A
        # subselect rather than a join, so the clause stays usable as a WHERE on
        # the table being deleted — which is what the engine backs up and counts.
        conditions: list[str] = []
        params: list = []
        for local_col, ref_table, ref_col in ctx.fks(table):
            if not local_col or ref_table == table:
                continue
            if self.owner_column in ctx.columns(ref_table):
                conditions.append(
                    f"{quote(local_col)} IN (SELECT {quote(ref_col)} FROM "
                    f"{ctx.qualified(ref_table)} WHERE {self.owner_column} = %s)"
                )
                params.append(self.rid)

        if conditions:
            return " OR ".join(conditions), params
        return None
