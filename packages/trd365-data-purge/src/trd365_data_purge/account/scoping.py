"""
Account scoping — resolve an account, capture its id-sets, and build the WHERE
clause that selects exactly the rows belonging to it.

Ported from ``legacy/trd365_maintenance/data_purge/account/scoping.py``, keeping
the vendor's SECTION-1 resolution and SECTION-2/3/7 scoping rules intact. Three
things changed in the port:

* schema metadata comes from a run-scoped :class:`~trd365_data_purge.engine.SchemaCache`
  keyed by database, instead of module-level dicts keyed by ``(schema, table)``
  that were never cleared and could serve one database's metadata for another;
* the special-case predicates take a :class:`ScopeContext` rather than four
  positional arguments, so they can reach the cache;
* :meth:`AccountScoper.discover` also consults the shared data-model snapshot,
  so re-running the data-model analysis propagates newly-added tables into the
  purge without anyone editing the manifest.

The scoping rule, in one sentence: a table belongs to the account if it carries
``account_rid``, or if it has a foreign key into a table that does, or if it
carries one of a small set of unambiguous ``*_rid`` columns whose parent does.
Anything that satisfies none of those is reported as **unscoped** and left
completely untouched — guessing there would delete another account's rows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from trd365_core.datamodel import PK_COLUMN, entity

from ..engine import SchemaCache, quote
from . import manifest as M

ACCOUNT = entity("account")

#: A predicate that can never match. Used when a table's parent is absent, which
#: means nothing in it can belong to this account.
NEVER: tuple[str, list] = ("1=0", [])


# ---------------------------------------------------------------------------
# resolution (SECTION 1)
# ---------------------------------------------------------------------------


@dataclass
class ResolvedAccount:
    """Where an account's data physically lives."""

    rid: str
    exists: bool
    r_number: str | None = None
    storage_type: str | None = None
    parent_rid: str | None = None
    org_schema: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rid": self.rid,
            "exists": self.exists,
            "r_number": self.r_number,
            "storage_type": self.storage_type,
            "parent_rid": self.parent_rid,
            "org_schema": self.org_schema,
        }


def resolve_account(pool, rid: str) -> ResolvedAccount:
    """
    Find the account and the org schema its data lives in.

    An account with ``storage_type == "store_in_parent"`` has no schema of its
    own: its rows sit in its parent's schema, distinguished by ``account_rid``.
    Getting this wrong would either miss every row or point the purge at a
    schema belonging to somebody else, so it is resolved before anything else.
    """
    conn = pool.get(ACCOUNT.db_key)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT r_number, storage_type, parent_account_rid "
            f"FROM {quote(M.MAIN_SCHEMA)}.{quote(ACCOUNT.table)} WHERE {PK_COLUMN}=%s",
            (rid,),
        )
        row = cur.fetchone()
    conn.rollback()

    if not row:
        return ResolvedAccount(rid=rid, exists=False)

    r_number, storage_type, parent_rid = row
    effective = r_number

    if storage_type == "store_in_parent" and parent_rid:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT r_number FROM {quote(M.MAIN_SCHEMA)}.{quote(ACCOUNT.table)} "
                f"WHERE {PK_COLUMN}=%s",
                (parent_rid,),
            )
            parent = cur.fetchone()
        conn.rollback()
        if parent:
            effective = parent[0]

    return ResolvedAccount(
        rid=rid,
        exists=True,
        r_number=r_number,
        storage_type=storage_type,
        parent_rid=parent_rid,
        org_schema=M.org_schema_for(effective),
    )


# ---------------------------------------------------------------------------
# id-set capture, before anything is deleted
# ---------------------------------------------------------------------------


def capture_id_sets(pool, cache: SchemaCache, account: ResolvedAccount) -> dict[str, list]:
    """
    Read the rids the later steps need, while the rows still exist.

    The trd365ai step has no path back to the org schema, and by the time it
    runs the org rows are gone. Its scope therefore has to be captured now, up
    front, and carried in the checkpoint — a resumed run must reuse the saved
    sets rather than re-reading empty tables.
    """
    conn = pool.get("orgdb")
    schema = account.org_schema
    rid = account.rid
    sets: dict[str, list] = {}

    def rids(table: str, where: str, params) -> list:
        if not cache.table_exists(conn, "orgdb", schema, table):
            return []
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {PK_COLUMN} FROM {quote(schema)}.{quote(table)} WHERE {where}", params
            )
            return [row[0] for row in cur.fetchall()]

    sets["cases"] = rids("cases", "account_rid=%s", (rid,))
    sets["project"] = rids("project", "account_rid=%s", (rid,))
    sets["project_fiscal"] = rids("project_fiscal", "account_rid=%s", (rid,))
    sets["resources"] = rids("resources", "account_rid=%s", (rid,))

    has_interactions = cache.table_exists(conn, "orgdb", schema, "interactions")
    if has_interactions and "account_rid" in cache.columns(conn, "orgdb", schema, "interactions"):
        sets["interactions"] = rids("interactions", "account_rid=%s", (rid,))
    else:
        sets["interactions"] = rids(
            "interactions", "project_fiscal_rid = ANY(%s)", (sets["project_fiscal"],)
        )

    sets["project_task"] = rids(
        "project_task", "project_fiscal_rid = ANY(%s)", (sets["project_fiscal"],)
    )
    sets["checklists"] = rids("checklists", "case_rid = ANY(%s)", (sets["cases"],))

    conn.rollback()
    return sets


# ---------------------------------------------------------------------------
# special predicates — tables the vendor scopes through a parent, not account_rid
# ---------------------------------------------------------------------------


@dataclass
class ScopeContext:
    """What a predicate needs to inspect the schema it is scoping against."""

    conn: Any
    cache: SchemaCache
    db_key: str
    schema: str
    rid: str
    sets: dict[str, list]

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


def _via_attach_to(parent: str) -> SpecialPredicate:
    """Timeline tables point at their subject with a bare ``attach_to`` column."""

    def predicate(ctx: ScopeContext) -> Predicate:
        if not ctx.exists(parent):
            return NEVER
        return (
            f"attach_to IN (SELECT {PK_COLUMN} FROM {ctx.qualified(parent)} "
            f"WHERE account_rid = %s)",
            [ctx.rid],
        )

    return predicate


def _via_chat_session(ctx: ScopeContext) -> Predicate:
    if not ctx.exists("chat_sessions"):
        return NEVER
    return (
        f"session_rid IN (SELECT session_rid FROM {ctx.qualified('chat_sessions')} "
        f"WHERE account_rid = %s)",
        [ctx.rid],
    )


def _user_group_entity_access(ctx: ScopeContext) -> Predicate:
    # An access grant names an entity generically, so it is reached through both
    # summary tables that can be the entity in question.
    return (
        f"entity_rid IN (SELECT {PK_COLUMN} FROM {ctx.qualified('project_fiscal_summary')} "
        f"WHERE account_rid=%s) "
        f"OR entity_rid IN (SELECT project_rid FROM {ctx.qualified('project_summary')} "
        f"WHERE account_rid=%s)",
        [ctx.rid, ctx.rid],
    )


def _key_contact_details(ctx: ScopeContext) -> Predicate:
    # entity_rid is polymorphic here: a project, or the account itself.
    if ctx.exists("project"):
        return (
            f"entity_rid IN (SELECT {PK_COLUMN} FROM {ctx.qualified('project')} "
            f"WHERE account_rid = %s) OR entity_rid = %s",
            [ctx.rid, ctx.rid],
        )
    return "entity_rid = %s", [ctx.rid]


def _kafka_events(ctx: ScopeContext) -> Predicate:
    if not ctx.exists("document"):
        return NEVER
    sql = (
        f"document_rid IN (SELECT {PK_COLUMN} FROM {ctx.qualified('document')} "
        f"WHERE account_rid = %s)"
    )
    params = [ctx.rid]
    if ctx.exists("import"):
        sql += (
            f" OR document_upload_rid IN (SELECT i.{PK_COLUMN} FROM {ctx.qualified('import')} i "
            f"JOIN {ctx.qualified('document')} d ON i.document_rid = d.{PK_COLUMN} "
            f"WHERE d.account_rid = %s)"
        )
        params.append(ctx.rid)
    return sql, params


SPECIAL_PREDICATES: dict[str, SpecialPredicate] = {
    "attachment_timeline": _via_attach_to("attachments"),
    "notes_timeline": _via_attach_to("notes"),
    "account_timeline_old": lambda ctx: ("attach_to = %s", [ctx.rid]),
    "user_group_entity_access": _user_group_entity_access,
    "account": lambda ctx: (f"{PK_COLUMN} = %s", [ctx.rid]),
    "key_contact_details": _key_contact_details,
    "kafka_events": _kafka_events,
    "chat_answers": _via_chat_session,
    "chat_attachments": _via_chat_session,
    "chat_audit_log": _via_chat_session,
    "chat_branches": _via_chat_session,
    "chat_messages": _via_chat_session,
    "chat_questions": _via_chat_session,
}

#: Unambiguous ``*_rid`` columns and the table(s) they can point at.
#:
#: ``project_rid`` is deliberately absent: depending on the table it means either
#: a project or a project fiscal, and picking the wrong one would scope a delete
#: by an unrelated row's identifier.
FALLBACK_PARENTS: dict[str, list[str]] = {
    "case_rid": ["cases", "case_summary"],
    "interaction_rid": ["interactions", "interactions_summary"],
    "project_fiscal_rid": ["project_fiscal", "project_fiscal_summary"],
    "resource_rid": ["resources"],
    "checklist_rid": ["checklists"],
    "session_rid": ["chat_sessions"],
    "task_rid": ["project_task", "task_summary"],
    "project_task_rid": ["project_task"],
}


# ---------------------------------------------------------------------------
# discovery of account-scoped tables the manifest does not list
# ---------------------------------------------------------------------------


def account_scopable_tables(conn, schema: str) -> set[str]:
    """Org tables carrying ``account_rid``, or with a foreign key into one that does."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH acct AS (
              SELECT table_name FROM information_schema.columns
              WHERE table_schema=%s AND column_name='account_rid'
            )
            SELECT DISTINCT t.relname FROM pg_class t
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname=%s AND t.relkind='r'
              AND ( t.relname IN (SELECT table_name FROM acct)
                    OR EXISTS (SELECT 1 FROM pg_constraint c
                               JOIN pg_class rt ON rt.oid = c.confrelid
                               WHERE c.conrelid = t.oid AND c.contype='f'
                                 AND rt.relname IN (SELECT table_name FROM acct)))
            """,
            (schema, schema),
        )
        return {row[0] for row in cur.fetchall()}


def fk_children_with_account_rid(
    conn, cache: SchemaCache, db_key: str, schema: str, parent: str
) -> set[str]:
    """Main-schema tables with a foreign key into ``parent`` that also carry ``account_rid``."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT t.relname FROM pg_constraint c
            JOIN pg_class t  ON t.oid = c.conrelid
            JOIN pg_class rt ON rt.oid = c.confrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname=%s AND c.contype='f' AND rt.relname=%s
            """,
            (schema, parent),
        )
        children = {row[0] for row in cur.fetchall()}
    return {c for c in children if "account_rid" in cache.columns(conn, db_key, schema, c)}


# ---------------------------------------------------------------------------
# the scoper the engine drives
# ---------------------------------------------------------------------------


class AccountScoper:
    """
    Turns ``(schema, table, kind)`` into the WHERE clause selecting this
    account's rows, or ``None`` when the table cannot be tied to the account.

    Returning ``None`` is the important behaviour: the engine leaves such a
    table completely untouched and the report lists it for a human. A purge that
    guessed here would delete somebody else's data.
    """

    def __init__(
        self,
        account: ResolvedAccount,
        sets: dict[str, list],
        cache: SchemaCache,
        db_for: dict[str, str],
        model=None,
    ) -> None:
        self.account = account
        self.sets = sets
        self.cache = cache
        self.db_for = db_for
        self.model = model
        self.rid = account.rid

    def _context(self, conn, schema: str, kind: str) -> ScopeContext:
        return ScopeContext(
            conn=conn,
            cache=self.cache,
            db_key=self.db_for[kind],
            schema=schema,
            rid=self.rid,
            sets=self.sets,
        )

    # ------------------------------------------------------------ discovery

    def discover(self, conn, schema: str, kind: str, manifest_tables) -> list[str]:
        """
        Account-scoped tables in this schema that the manifest does not list.

        For the org step this unions live introspection with the shared
        data-model snapshot, so a table added since this manifest was written is
        purged as soon as the data-model analysis has seen it.
        """
        known = set(manifest_tables) | set(SPECIAL_PREDICATES)

        if kind == "org":
            found = account_scopable_tables(conn, schema)
            if self.model is not None:
                found |= set(M.reconcile(self.model, schema)["missing_from_manifest"])
        elif kind == "main":
            found = fk_children_with_account_rid(
                conn, self.cache, self.db_for[kind], schema, ACCOUNT.table
            )
        else:
            # trd365ai has no account link at all; its manifest is exhaustive.
            return []

        return sorted(found - known)

    # ------------------------------------------------------------ predicate

    def predicate(self, conn, schema: str, table: str, kind: str) -> Predicate | None:
        ctx = self._context(conn, schema, kind)

        special = SPECIAL_PREDICATES.get(table)
        if special is not None:
            return special(ctx)

        if kind == "ai":
            # No path back to org: scope by the fiscal set captured up front.
            cols = ctx.columns(table)
            for column in M.AI_FISCAL_COLUMNS:
                if column in cols:
                    return f"{quote(column)} = ANY(%s)", [self.sets.get("project_fiscal", [])]
            return None

        return self._org_or_main_predicate(ctx, table)

    def _org_or_main_predicate(self, ctx: ScopeContext, table: str) -> Predicate | None:
        cols = ctx.columns(table)
        conditions: list[str] = []
        params: list = []

        if "account_rid" in cols:
            conditions.append("account_rid = %s")
            params.append(ctx.rid)

        for local_col, ref_table, ref_col in ctx.fks(table):
            if not local_col or not ref_col or ref_table == table:
                continue
            if "account_rid" in ctx.columns(ref_table):
                conditions.append(
                    f"{quote(local_col)} IN (SELECT {quote(ref_col)} FROM "
                    f"{ctx.qualified(ref_table)} WHERE account_rid = %s)"
                )
                params.append(ctx.rid)

        for column, candidates in FALLBACK_PARENTS.items():
            if column not in cols:
                continue
            for parent in candidates:
                if not ctx.exists(parent):
                    continue
                parent_cols = ctx.columns(parent)
                if "account_rid" in parent_cols and PK_COLUMN in parent_cols:
                    conditions.append(
                        f"{quote(column)} IN (SELECT {PK_COLUMN} FROM {ctx.qualified(parent)} "
                        f"WHERE account_rid = %s)"
                    )
                    params.append(ctx.rid)
                    break

        if not conditions:
            return None
        return " OR ".join(conditions), params


#: Schemas that do not depend on which account is being purged. ``org`` is
#: filled in per account, from :func:`resolve_account`.
FIXED_SCHEMAS: dict[str, str] = {"main": M.MAIN_SCHEMA, "ai": M.AI_SCHEMA}

#: ``schema_kind -> db_key``, derived from the manifest so the two cannot drift.
DB_FOR_KIND: dict[str, str] = {kind: db for (_step, db, kind, _tables) in M.STEPS}
