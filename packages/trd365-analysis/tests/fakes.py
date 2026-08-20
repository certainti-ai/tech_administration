"""
An in-memory stand-in for the reads this package issues.

No Claude Code session can reach the databases, so analysis has to be
exercisable without one. This implements only the queries the package actually
sends and raises ``NotImplementedError`` for anything else, so a test cannot
come to depend on behaviour the fake invented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

PK = "rid"


@dataclass
class Table:
    columns: list[str]
    rows: list[dict[str, Any]] = field(default_factory=list)


def table(columns, rows=()) -> Table:
    return Table(list(columns), [dict(r) for r in rows])


_COLUMNS = re.compile(
    r"^SELECT table_name, column_name FROM information_schema\.columns "
    r"WHERE table_schema = %s ORDER BY table_name, ordinal_position$"
)
_TENANT = re.compile(r"^SELECT nspname FROM pg_namespace WHERE nspname LIKE %s ")
_HAS_COLUMN = re.compile(
    r"^SELECT 1 FROM information_schema\.columns WHERE table_schema=%s "
    r"AND table_name=%s AND column_name=%s$"
)
_PK_LIST = re.compile(r'^SELECT rid FROM "([^"]+)"\."([^"]+)"$')
_COUNT_ALL = re.compile(r'^SELECT count\(\*\) FROM "([^"]+)"\."([^"]+)"$')
_ORPHAN_COUNT = re.compile(
    r'^SELECT count\(\*\) FROM "([^"]+)"\."([^"]+)" c WHERE c\."([^"]+)" IS NOT NULL '
    r'AND NOT EXISTS \(SELECT 1 FROM "([^"]+)"\."([^"]+)" p WHERE p\.rid = c\."([^"]+)"\)$'
)
_ORPHAN_SAMPLE = re.compile(
    r'^SELECT DISTINCT c\."([^"]+)" FROM "([^"]+)"\."([^"]+)" c WHERE c\."([^"]+)" IS NOT NULL '
    r'AND NOT EXISTS \(SELECT 1 FROM "([^"]+)"\."([^"]+)" p WHERE p\.rid = c\."([^"]+)"\) '
    r"LIMIT %s$"
)
_GROUP_BY = re.compile(
    r'^SELECT "([^"]+)", count\(\*\) FROM "([^"]+)"\."([^"]+)" '
    r'WHERE "([^"]+)" IS NOT NULL GROUP BY "([^"]+)"$'
)


class FakeDatabase:
    """
    Tables keyed by ``(db_key, schema, table)``, and a ``fetch`` that reads them.

    ``fail_on`` maps a substring of a query to an exception to raise, so a test
    can make one specific read fail without any of the others changing.
    """

    def __init__(self, tables: dict[tuple[str, str, str], Table] | None = None) -> None:
        self.tables: dict[tuple[str, str, str], Table] = dict(tables or {})
        self.queries: list[tuple[str, str]] = []
        self.fail_on: dict[str, Exception] = {}

    # ------------------------------------------------------------- helpers

    def get(self, db_key: str, schema: str, name: str) -> Table | None:
        return self.tables.get((db_key, schema, name))

    def schemas(self, db_key: str) -> set[str]:
        return {s for (d, s, _t) in self.tables if d == db_key}

    def rows(self, db_key: str, schema: str, name: str) -> list[dict]:
        found = self.get(db_key, schema, name)
        return found.rows if found else []

    def pk_values(self, db_key: str, schema: str, name: str) -> set:
        return {r.get(PK) for r in self.rows(db_key, schema, name)}

    # --------------------------------------------------------------- fetch

    def fetch(self, db_key: str, query: str, params: list | None = None) -> list[tuple]:
        self.queries.append((db_key, query))
        for needle, error in self.fail_on.items():
            if needle in query:
                raise error

        flat = " ".join(query.split())
        params = list(params or [])

        if _COLUMNS.match(flat):
            (schema,) = params
            out = []
            for (d, s, name), t in sorted(self.tables.items()):
                if d == db_key and s == schema:
                    out += [(name, column) for column in t.columns]
            return out

        if _TENANT.match(flat):
            return [
                (name,)
                for name in sorted(self.schemas(db_key))
                if name.startswith("trd365_") and "backup" not in name
            ]

        if _HAS_COLUMN.match(flat):
            schema, name, column = params
            found = self.get(db_key, schema, name)
            return [(1,)] if found and column in found.columns else []

        match = _PK_LIST.match(flat)
        if match:
            schema, name = match.groups()
            return [(r[PK],) for r in self.rows(db_key, schema, name) if PK in r]

        match = _COUNT_ALL.match(flat)
        if match:
            schema, name = match.groups()
            return [(len(self.rows(db_key, schema, name)),)]

        match = _ORPHAN_COUNT.match(flat)
        if match:
            schema, child, column, _ps, parent, _c2 = match.groups()
            return [(len(self._orphan_values(db_key, schema, child, column, parent)),)]

        match = _ORPHAN_SAMPLE.match(flat)
        if match:
            column, schema, child, _c1, _ps, parent, _c2 = match.groups()
            values = self._orphan_values(db_key, schema, child, column, parent)
            distinct = sorted({v for v in values})
            return [(v,) for v in distinct[: params[0]]]

        match = _GROUP_BY.match(flat)
        if match:
            column, schema, name, _c1, _c2 = match.groups()
            counts: dict[Any, int] = {}
            for row in self.rows(db_key, schema, name):
                value = row.get(column)
                if value is not None:
                    counts[value] = counts.get(value, 0) + 1
            return sorted(counts.items())

        raise NotImplementedError(f"The fake database does not understand: {flat}")

    def _orphan_values(self, db_key, schema, child, column, parent) -> list:
        valid = self.pk_values(db_key, schema, parent)
        return [
            row[column]
            for row in self.rows(db_key, schema, child)
            if row.get(column) is not None and row[column] not in valid
        ]


class FakePool:
    """A :class:`trd365_core.db.ConnectionPool` stand-in over a FakeDatabase."""

    def __init__(self, database: FakeDatabase) -> None:
        self.database = database

    def fetcher(self):
        return self.database.fetch

    def close(self) -> None:
        pass

    def __enter__(self) -> FakePool:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


def silent(_message: str) -> None:
    """A log function that discards."""
