"""
A small in-memory stand-in for Postgres.

No Claude Code session can reach the real databases (see the repo README), so
the engine has to be exercisable without one. This fake implements only what the
purge actually issues, and raises ``NotImplementedError`` for anything else —
so a test cannot quietly come to depend on semantics the fake invented.

Transactions are real enough to matter: writes are staged and applied on
``commit``, discarded on ``rollback``. That is what makes it possible to assert
the engine's central invariant — a backup row exists if and only if the source
row was deleted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import psycopg2

FK_VIOLATION = "23503"


class FakeFkViolation(psycopg2.Error):
    """A foreign-key violation, as psycopg2 would report it."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self._message = message

    @property
    def pgcode(self) -> str:
        return FK_VIOLATION

    def __str__(self) -> str:
        return self._message


@dataclass
class FakeTable:
    columns: list[str]
    rows: list[dict[str, Any]] = field(default_factory=list)
    #: Single-column foreign keys as ``(local_col, ref_table, ref_col)``.
    fks: list[tuple[str, str, str]] = field(default_factory=list)
    #: While this table still holds rows, deleting from *this* table raises a
    #: foreign-key violation. Models a child that has to go first.
    blocked_by: str | None = None


def table(columns, rows=(), fks=(), blocked_by=None) -> FakeTable:
    materialised = []
    for index, row in enumerate(rows):
        record = dict(row)
        record.setdefault("_ctid", f"(0,{index + 1})")
        materialised.append(record)
    return FakeTable(list(columns), materialised, list(fks), blocked_by)


# --------------------------------------------------------------------------
# predicate evaluation — deliberately tiny
# --------------------------------------------------------------------------


def matches(row: dict[str, Any], where: str, params) -> bool:
    """Evaluate the handful of predicate shapes the engine tests use."""
    where = where.strip()
    if where in ("1=0", "FALSE"):
        return False
    if where in ("1=1", "TRUE"):
        return True
    if where == "account_rid = %s":
        return row.get("account_rid") == list(params)[0]
    if where == "account_rid=%s":
        return row.get("account_rid") == list(params)[0]
    if where == "rid = %s":
        return row.get("rid") == list(params)[0]
    raise NotImplementedError(
        f"The fake database does not evaluate {where!r}. Assert on the generated "
        f"SQL instead, or add the shape here deliberately."
    )


_COUNT_WHERE = re.compile(r'^SELECT count\(\*\) FROM "([^"]+)"\."([^"]+)" WHERE (.+)$', re.S)
_COUNT_ALL = re.compile(r'^SELECT count\(\*\) FROM "([^"]+)"\."([^"]+)"$')
_CTIDS = re.compile(r'^SELECT ctid FROM "([^"]+)"\."([^"]+)" WHERE (.+) LIMIT (\d+)$', re.S)
_RIDS = re.compile(r'^SELECT rid FROM "([^"]+)"\."([^"]+)" WHERE (.+)$', re.S)
_INSERT_BAK = re.compile(
    r'^INSERT INTO "([^"]+)"\."([^"]+)" SELECT t\.\*, %s, %s, %s, %s FROM "([^"]+)"\."([^"]+)" t '
    r"WHERE t\.ctid = ANY\(%s::tid\[\]\)$",
    re.S,
)
_DELETE_CTIDS = re.compile(
    r'^DELETE FROM "([^"]+)"\."([^"]+)" WHERE ctid = ANY\(%s::tid\[\]\)$'
)


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn
        self._result: list[tuple] = []
        self.rowcount = -1

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def close(self) -> None:
        pass

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self) -> list[tuple]:
        return list(self._result)

    # ------------------------------------------------------------- execute

    def execute(self, sql: str, params=None) -> None:
        self.conn.statements.append(sql)
        sql = " ".join(sql.split())
        params = [] if params is None else list(params)
        self._result = []
        self.rowcount = -1

        if sql.startswith(("CREATE SCHEMA", "CREATE TABLE", "ALTER TABLE", "SET ")):
            self.conn.ddl.append(sql)
            return

        if "information_schema.tables" in sql:
            schema, name = params
            self._result = [(1,)] if self.conn.has(schema, name) else []
            return

        if "information_schema.columns" in sql and "SELECT column_name" in sql:
            schema, name = params
            found = self.conn.table(schema, name)
            self._result = [(c,) for c in (found.columns if found else [])]
            return

        if "pg_constraint" in sql and "array_length" in sql:
            schema, name = params
            found = self.conn.table(schema, name)
            self._result = list(found.fks) if found else []
            return

        if "information_schema.columns" in sql and "acct AS" in sql:
            self._result = [(t,) for t in sorted(self.conn.account_scopable(params[0]))]
            return

        if "pg_constraint" in sql and "rt.relname=%s" in sql:
            schema, parent = params
            self._result = [(t,) for t in sorted(self.conn.children_of(schema, parent))]
            return

        for pattern, handler in (
            (_COUNT_WHERE, self._count_where),
            (_COUNT_ALL, self._count_all),
            (_CTIDS, self._ctids),
            (_INSERT_BAK, self._insert_backup),
            (_DELETE_CTIDS, self._delete_ctids),
            (_RIDS, self._rids),
        ):
            match = pattern.match(sql)
            if match:
                handler(match, params)
                return

        raise NotImplementedError(f"The fake database does not understand: {sql}")

    # ------------------------------------------------------------ handlers

    def _live(self, schema: str, name: str) -> list[dict]:
        return self.conn.live_rows(schema, name)

    def _count_where(self, match, params) -> None:
        schema, name, where = match.group(1), match.group(2), match.group(3)
        self._result = [(sum(1 for r in self._live(schema, name) if matches(r, where, params)),)]

    def _count_all(self, match, _params) -> None:
        self._result = [(len(self._live(match.group(1), match.group(2))),)]

    def _ctids(self, match, params) -> None:
        schema, name, where, limit = match.groups()
        selected = [r for r in self._live(schema, name) if matches(r, where, params)]
        self._result = [(r["_ctid"],) for r in selected[: int(limit)]]

    def _rids(self, match, params) -> None:
        schema, name, where = match.groups()
        self._result = [
            (r["rid"],) for r in self._live(schema, name) if matches(r, where, params)
        ]

    def _insert_backup(self, match, params) -> None:
        bak_schema, bak_table, schema, name = match.group(1, 2, 3, 4)
        ctids = set(params[4])
        rows = [r for r in self._live(schema, name) if r["_ctid"] in ctids]
        self.conn.stage_insert(bak_schema, bak_table, rows, params[:4])
        self.rowcount = len(rows)

    def _delete_ctids(self, match, params) -> None:
        schema, name = match.group(1), match.group(2)
        found = self.conn.table(schema, name)
        if found is not None and found.blocked_by and self.conn.live_rows(schema, found.blocked_by):
            raise FakeFkViolation(
                f'update or delete on table "{name}" violates foreign key constraint '
                f'on table "{found.blocked_by}"'
            )
        ctids = set(params[0])
        matched = [r for r in self._live(schema, name) if r["_ctid"] in ctids]
        self.conn.stage_delete(schema, name, matched)
        self.rowcount = len(matched)


class FakeConnection:
    """One database. Writes are staged until ``commit``."""

    def __init__(self, tables: dict[tuple[str, str], FakeTable] | None = None) -> None:
        self.tables: dict[tuple[str, str], FakeTable] = dict(tables or {})
        self.closed = 0
        self.commits = 0
        self.rollbacks = 0
        self.statements: list[str] = []
        self.ddl: list[str] = []
        self._pending_deletes: list[tuple[str, str, dict]] = []
        self._pending_inserts: list[tuple[str, str, dict]] = []

    # ------------------------------------------------------------- schema

    def table(self, schema: str, name: str) -> FakeTable | None:
        return self.tables.get((schema, name))

    def has(self, schema: str, name: str) -> bool:
        return (schema, name) in self.tables

    def live_rows(self, schema: str, name: str) -> list[dict]:
        found = self.table(schema, name)
        if found is None:
            return []
        staged = {id(r) for (s, t, r) in self._pending_deletes if (s, t) == (schema, name)}
        rows = [r for r in found.rows if id(r) not in staged]
        rows += [r for (s, t, r) in self._pending_inserts if (s, t) == (schema, name)]
        return rows

    def account_scopable(self, schema: str) -> set[str]:
        with_account = {
            name for (s, name), t in self.tables.items()
            if s == schema and "account_rid" in t.columns
        }
        found = set(with_account)
        for (s, name), t in self.tables.items():
            if s != schema:
                continue
            if any(ref in with_account for (_local, ref, _rc) in t.fks):
                found.add(name)
        return found

    def children_of(self, schema: str, parent: str) -> set[str]:
        return {
            name for (s, name), t in self.tables.items()
            if s == schema and any(ref == parent for (_local, ref, _rc) in t.fks)
        }

    # -------------------------------------------------------- transactions

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def stage_delete(self, schema: str, name: str, rows: list[dict]) -> None:
        self._pending_deletes += [(schema, name, r) for r in rows]

    def stage_insert(self, schema: str, name: str, rows: list[dict], tag) -> None:
        if (schema, name) not in self.tables:
            self.tables[(schema, name)] = FakeTable(columns=[], rows=[])
        for row in rows:
            copied = dict(row)
            copied.update(
                {
                    "_purge_run_at": tag[0],
                    "_purge_run_id": tag[1],
                    "_purge_entity": tag[2],
                    "_purge_entity_rid": tag[3],
                }
            )
            self._pending_inserts.append((schema, name, copied))

    def commit(self) -> None:
        self.commits += 1
        for schema, name, row in self._pending_deletes:
            found = self.tables.get((schema, name))
            if found is not None:
                found.rows = [r for r in found.rows if id(r) != id(row)]
        for schema, name, row in self._pending_inserts:
            self.tables.setdefault((schema, name), FakeTable(columns=[], rows=[])).rows.append(row)
        self._pending_deletes.clear()
        self._pending_inserts.clear()

    def rollback(self) -> None:
        self.rollbacks += 1
        self._pending_deletes.clear()
        self._pending_inserts.clear()

    def close(self) -> None:
        self.closed = 1


class FakePool:
    """A :class:`trd365_core.db.ConnectionPool` stand-in keyed by db_key."""

    def __init__(self, connections: dict[str, FakeConnection]) -> None:
        self.connections = connections

    def get(self, db_key: str) -> FakeConnection:
        return self.connections[db_key]

    def close(self) -> None:
        for conn in self.connections.values():
            conn.close()

    def __enter__(self) -> FakePool:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.close()
        return False


def silent(_message: str) -> None:
    """A log function that discards. Tests that care capture into a list instead."""


class AccountDirectory(FakeConnection):
    """
    A main database that also answers ``resolve_account``'s bespoke query.

    Account resolution reads three named columns in one statement rather than
    the row shapes everything else deals in, so that query is special-cased.
    Every other statement falls through to the ordinary fake, which is what
    makes this usable for the whole main step and not just resolution.
    """

    def __init__(
        self,
        accounts: dict[str, tuple],
        tables: dict[tuple[str, str], FakeTable] | None = None,
    ) -> None:
        super().__init__(tables or {})
        self.accounts = accounts

    def cursor(self):
        outer = self
        fallback = super().cursor()

        class Cursor:
            result = None
            resolved = False

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_exc):
                return False

            def close(self_inner):
                fallback.close()

            def execute(self_inner, sql, params=None):
                # resolve_account issues two shapes: the full row for the target,
                # and just the reference number when following a parent link.
                if "r_number" in sql:
                    self_inner.resolved = True
                    record = outer.accounts.get(list(params or [])[0])
                    self_inner.result = (
                        record
                        if record is None or "storage_type" in sql
                        else (record[0],)
                    )
                    return
                self_inner.resolved = False
                fallback.execute(sql, params)

            @property
            def rowcount(self_inner):
                return fallback.rowcount

            def fetchone(self_inner):
                return self_inner.result if self_inner.resolved else fallback.fetchone()

            def fetchall(self_inner):
                return [] if self_inner.resolved else fallback.fetchall()

        return Cursor()
