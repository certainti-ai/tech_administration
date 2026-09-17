#!/usr/bin/env python3
"""Copy the main database's reference tables into the org database.

The two databases live on different Postgres servers, so no SQL-level copy is
possible: rows are read from main and streamed into org over COPY.

This creates a SECOND COPY of reference data. It will drift from main the
moment either side changes, which is the same failure mode as every other
duplicated-state finding in docs/recon-checks.md. The mitigations here are the
refresh log (so staleness is visible rather than assumed) and the fact that the
whole run is a rebuild, not a merge — re-running always converges on main.

Safety, in order of importance:

* **Nothing is written without ``--apply``.** The default is a full rehearsal:
  every statement runs inside one transaction that is then rolled back, so a
  dry run proves the DDL and the copy actually work rather than guessing.
* **One transaction for the whole run.** A failure on table 20 leaves the
  schema exactly as it was — there is no half-copied state to clean up.
* **The source connection is forced read-only** at the session level, so a
  mistake here cannot write to main whatever the login is granted.
* Row counts are verified against the source before the transaction commits.

    python tools/copy_reference_tables.py                 # rehearse, change nothing
    python tools/copy_reference_tables.py --apply         # do it
    python tools/copy_reference_tables.py --env stage     # pre-production
"""
from __future__ import annotations

import argparse
import io
import sys
from datetime import datetime, timezone

from trd365_core.db import ConnectionPool
from trd365_core.environments import Environment

#: Where the copies land in the ORG database. Everything downstream — the
#: consolidated views, the dashboards — names this one schema and nothing else.
DEFAULT_TARGET_SCHEMA = "trd365_all"

#: The schema these tables live in on MAIN. Unrelated to the target above and
#: not ours to rename.
SOURCE_SCHEMA = "trd365"

#: Reference tables, chosen because tenant-schema ``_rid`` columns resolve to
#: them.
#:
#: ``account`` and ``user`` are included at the owner's instruction. Two things
#: follow that the refresh log is there to keep visible: the org copy of
#: ``account`` is a second statement of which tenants exist and whether they are
#: active, so a query joining it is answering from a snapshot rather than from
#: main; and ``user`` carries login identities, so this schema is no longer
#: purely non-sensitive lookup data and should be granted accordingly.
#:
#: ``interaction_templates`` is here and ``templates`` is too: probing found
#: ``template_rid`` values in the former, so which one the column means is not
#: settled. Both are tiny; copying both costs nothing and removes the guess.
TABLES = [
    "account",
    "case_filing_type",
    "checklist_template",
    "city",
    "country",
    "currency",
    "document_category",
    "document_type",
    "event_types",
    "industry",
    "interaction_assessment_source",
    "interaction_level",
    "interaction_source",
    "interaction_status",
    "interaction_templates",
    "interaction_type",
    "milestone_template",
    "project_classification",
    "project_type",
    "regions",
    "resource_type",
    "signoff_type",
    "skill_level",
    "skill_subtype",
    "skill_type",
    "state",
    "status",
    "tags",
    "task_category",
    "task_template",
    "task_type",
    "templates",
    "user",
]

REFRESH_LOG = "_reference_refresh"


def source_shape(cur, table: str) -> tuple[list[tuple[str, str, bool]], list[str]]:
    """Columns as ``(name, rendered type, not null)`` and the primary key.

    ``format_type`` is used rather than reassembling a type from
    information_schema: it renders exactly what the column is, varchar lengths
    and numeric precision included, with no reconstruction to get wrong.
    """
    cur.execute(
        """
        SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        (SOURCE_SCHEMA, table),
    )
    columns = [(r[0], r[1], r[2]) for r in cur.fetchall()]
    cur.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
        WHERE i.indrelid = format('%%I.%%I', %s, %s)::regclass AND i.indisprimary
        """,
        (SOURCE_SCHEMA, table),
    )
    return columns, [r[0] for r in cur.fetchall()]


TARGET_SCHEMA = DEFAULT_TARGET_SCHEMA


def ddl_for(table: str, columns, pk) -> str:
    body = []
    for name, typ, not_null in columns:
        body.append(f'  "{name}" {typ}' + (" NOT NULL" if not_null else ""))
    if pk:
        body.append("  PRIMARY KEY (%s)" % ", ".join(f'"{c}"' for c in pk))
    return 'CREATE TABLE "%s"."%s" (\n%s\n)' % (TARGET_SCHEMA, table, ",\n".join(body))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env", default="prod", help="environment (default: prod)")
    ap.add_argument("--apply", action="store_true",
                    help="commit. Without it the run is rehearsed and rolled back.")
    ap.add_argument("--without-identity", action="store_true",
                    help="skip account and user, leaving only non-sensitive lookups")
    ap.add_argument("--tables", help="comma-separated override of the table list")
    ap.add_argument("--target-schema", default=DEFAULT_TARGET_SCHEMA,
                    help="schema in the org database to write into")
    args = ap.parse_args()

    tables = args.tables.split(",") if args.tables else list(TABLES)
    if args.without_identity:
        tables = [t for t in tables if t not in ("account", "user")]
    tables.sort()

    global TARGET_SCHEMA
    TARGET_SCHEMA = args.target_schema

    env = Environment(args.env)
    started = datetime.now(timezone.utc)

    with ConnectionPool(env) as pool:
        src = pool.get("maindb")
        # Belt and braces: this script only ever reads from main, and the
        # database is told to enforce that rather than trusted to be asked
        # nicely. Any write here fails with SQLSTATE 25006.
        src.rollback()
        with src.cursor() as guard:
            guard.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        src.commit()

        dst = pool.get("orgdb")
        src_cur, dst_cur = src.cursor(), dst.cursor()
        copied: list[tuple[str, int, int]] = []

        try:
            dst_cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{TARGET_SCHEMA}"')
            dst_cur.execute(
                f'''CREATE TABLE IF NOT EXISTS "{TARGET_SCHEMA}"."{REFRESH_LOG}" (
                      table_name   varchar(128) PRIMARY KEY,
                      row_count    bigint       NOT NULL,
                      refreshed_at timestamptz  NOT NULL,
                      source_env   varchar(32)  NOT NULL
                    )'''
            )

            for table in tables:
                columns, pk = source_shape(src_cur, table)
                if not columns:
                    print(f"  !! {table}: not found in {SOURCE_SCHEMA} on main — skipped")
                    continue

                src_cur.execute(f'SELECT count(*) FROM "{SOURCE_SCHEMA}"."{table}"')
                expected = src_cur.fetchone()[0]

                # Rebuild rather than merge: the target is a snapshot of main,
                # so dropping it is what makes a re-run converge instead of
                # accumulating rows main no longer has.
                dst_cur.execute(f'DROP TABLE IF EXISTS "{TARGET_SCHEMA}"."{table}"')
                dst_cur.execute(ddl_for(table, columns, pk))

                buf = io.StringIO()
                src_cur.copy_expert(
                    f'COPY "{SOURCE_SCHEMA}"."{table}" TO STDOUT WITH (FORMAT csv)', buf)
                buf.seek(0)
                dst_cur.copy_expert(
                    f'COPY "{TARGET_SCHEMA}"."{table}" FROM STDIN WITH (FORMAT csv)', buf)

                dst_cur.execute(f'SELECT count(*) FROM "{TARGET_SCHEMA}"."{table}"')
                landed = dst_cur.fetchone()[0]
                if landed != expected:
                    raise RuntimeError(
                        f"{table}: {expected} rows on main but {landed} landed — "
                        "rolling the whole run back"
                    )

                dst_cur.execute(
                    f'''INSERT INTO "{TARGET_SCHEMA}"."{REFRESH_LOG}"
                          (table_name, row_count, refreshed_at, source_env)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (table_name) DO UPDATE
                          SET row_count = EXCLUDED.row_count,
                              refreshed_at = EXCLUDED.refreshed_at,
                              source_env = EXCLUDED.source_env''',
                    (table, landed, started, env.value),
                )
                copied.append((table, landed, len(columns)))
                print(f"  {table:<32} {landed:>9,} rows  {len(columns):>3} cols")

            if args.apply:
                dst.commit()
                print(f"\nCOMMITTED — {len(copied)} tables, "
                      f"{sum(n for _, n, _ in copied):,} rows into {TARGET_SCHEMA}")
            else:
                dst.rollback()
                print(f"\nREHEARSED AND ROLLED BACK — {len(copied)} tables, "
                      f"{sum(n for _, n, _ in copied):,} rows would be copied.\n"
                      "Everything above actually ran; nothing was kept. "
                      "Re-run with --apply to keep it.")
        except Exception:
            dst.rollback()
            print("\nROLLED BACK — nothing was written.", file=sys.stderr)
            raise
        finally:
            src_cur.close()
            dst_cur.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
