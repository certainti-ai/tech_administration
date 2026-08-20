#!/usr/bin/env python3
"""
Distil a pg_dump of the platform's main schema into a small reference fixture.

Why this exists
---------------
``trd365_core.datamodel`` encodes conventions the whole estate is built on:
``rid`` primary keys, ``{entity}_rid`` foreign keys, ``trd365`` as the shared
schema. Those were inferred from reading the maintenance scripts, and nothing
has ever checked them against a database.

**Take the DDL from the live database.** A checked-in ``pg_dump`` in another
repository is a snapshot of what someone intended at some point; the schema the
utilities actually run against is the only authority, and the two drift. That is
the ``--env`` mode below, and it is the one to use. It needs database access, so
it runs on the maintenance VM, not in a Claude session.

The file mode exists only as a stopgap for reading a dump you already have.
Anything it produces should be treated as unverified until the live extraction
has confirmed it.

Usage
-----
    # Authoritative: read the live database.
    python tools/extract_reference_schema.py --env prod --schema trd365 \\
        reference/trd365_main_schema.json

    # Stopgap: read a pg_dump you already have on disk.
    python tools/extract_reference_schema.py --from-dump <dir-or-file> \\
        reference/trd365_main_schema.json

The output holds table and column names only — no data, no types, no
constraints — so the conventions can be asserted in CI without carrying a schema
dump around.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

CREATE_TABLE = re.compile(r"CREATE TABLE (\w+)\.(\w+) \((.*?)\n\);", re.S)

#: Lines inside a CREATE TABLE body that declare a constraint, not a column.
CONSTRAINT_PREFIXES = ("CONSTRAINT", "PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "EXCLUDE")

COLUMN = re.compile(r"^(\w+)\s+\S")


def parse(sql: str) -> dict[str, dict[str, list[str]]]:
    """``{schema: {table: [column, ...]}}`` from a pg_dump."""
    found: dict[str, dict[str, list[str]]] = {}

    for schema, table, body in CREATE_TABLE.findall(sql):
        columns: list[str] = []
        for raw in body.split("\n"):
            line = raw.strip().rstrip(",")
            if not line or line.upper().startswith(CONSTRAINT_PREFIXES):
                continue
            match = COLUMN.match(line)
            if match:
                columns.append(match.group(1))
        found.setdefault(schema, {})[table] = columns

    return found


def from_database(environment: str, schema: str) -> dict[str, dict[str, list[str]]]:
    """
    Read the live catalog. The authoritative source.

    Uses the same introspection query the data-model analysis uses, so what this
    records and what the utilities see cannot disagree.
    """
    from trd365_core.datamodel import CATALOG_QUERY
    from trd365_core.db import ConnectionPool
    from trd365_core.environments import Environment

    env = Environment.parse(environment)
    with ConnectionPool(env) as pool:
        rows = pool.fetch("maindb", CATALOG_QUERY, [schema])

    tables: dict[str, list[str]] = {}
    for table_name, column_name in rows:
        tables.setdefault(table_name, []).append(column_name)
    return {schema: tables}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Distil a schema into a reference fixture.",
        epilog="Prefer --env: a checked-in dump drifts from the database the utilities run against.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--env", help="Read the live database for this environment. Authoritative.")
    source.add_argument("--from-dump", type=Path, help="Read a pg_dump file or directory. Stopgap.")
    parser.add_argument("--schema", default="trd365", help="Schema to read (default trd365).")
    parser.add_argument("target", type=Path, help="Where to write the JSON fixture.")
    args = parser.parse_args(argv[1:])

    if args.env:
        merged = from_database(args.env, args.schema)
        provenance = f"live database, {args.env}"
    else:
        files = (
            sorted(args.from_dump.glob("*.sql"))
            if args.from_dump.is_dir()
            else [args.from_dump]
        )
        if not files:
            print(f"No .sql files under {args.from_dump}")
            return 1
        merged = {}
        for path in files:
            for schema, tables in parse(path.read_text(errors="replace")).items():
                merged.setdefault(schema, {}).update(tables)
        provenance = f"pg_dump at {args.from_dump} — UNVERIFIED, may have drifted"

    payload = {
        "_comment": (
            "Table and column names only — no data, no types, no constraints. Used to check "
            "trd365_core.datamodel's conventions against a real schema."
        ),
        "_source": provenance,
        "_extracted_at": datetime.now(UTC).strftime("%Y-%m-%d"),
        "_authoritative": bool(args.env),
        "schemas": {
            schema: dict(sorted(tables.items())) for schema, tables in sorted(merged.items())
        },
    }

    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    for schema, tables in sorted(merged.items()):
        columns = sum(len(c) for c in tables.values())
        print(f"{schema}: {len(tables)} tables, {columns} columns -> {args.target}")
    if not args.env:
        print("NOTE: read from a dump, not the database. Re-run with --env on the VM to confirm.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
