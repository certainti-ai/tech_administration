#!/usr/bin/env python3
"""Build ``trd365_all`` — every tenant schema's data consolidated, references resolved.

One materialised view per table, each a ``UNION ALL`` over every tenant schema
with a ``tenant_schema`` provenance column, then left-joined to the reference
tables in ``trd365`` so names sit beside the rids they resolve. A dashboard
reads one relation with no joins.

Materialised rather than physical because the whole estate is under a million
rows: a full rebuild is cheap, so there is no incremental-refresh machinery to
get wrong, and ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` lets dashboards keep
reading the previous snapshot while the next one builds.

Everything here is generated from the live catalogue rather than hand-written,
because the estate is not uniform and does not stay still:

* **Tenant schemas come and go.** There were 30 this morning and 32 this
  afternoon. The schema list is discovered on every run, so a new tenant is
  picked up by regenerating rather than by remembering to edit a list.
* **Column sets differ between tenants.** The view takes the UNION of columns
  and selects ``NULL::type`` where a tenant lacks one, because an intersection
  would silently drop real data.
* **The same column can have different types in different tenants** — 60 of
  them do. Each is widened to a type that holds every variant (see ``widen``).
* **Primary keys are not all called rid.** The chat tables use
  ``session_rid``/``question_rid``/``answer_rid``/``message_rid``. The key is
  read from the catalogue, and ``(tenant_schema, <pk>)`` is the unique index
  that CONCURRENTLY refresh requires.

    python tools/build_consolidated_views.py --env stage            # write the SQL, run nothing
    python tools/build_consolidated_views.py --env stage --apply    # build them
    python tools/build_consolidated_views.py --env stage --refresh  # refresh them
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timezone

from trd365_core.db import ConnectionPool
from trd365_core.environments import Environment

TARGET_SCHEMA = "trd365_all"
REF_SCHEMA = "trd365"
TENANT_RE = r"^trd365_[0-9]+$"

TABLES = [
    "account_details",
    "project", "project_fiscal", "project_fiscal_region",
    "project_resource", "project_resource_fiscal", "project_resource_fiscal_region",
    "cases", "case_team", "case_task", "case_projects", "case_project_fiscal_region",
    "case_project_resource", "case_project_resource_fiscal", "dossier_form",
    "interactions", "interaction_items", "interaction_send_history",
    "interaction_response_history", "interaction_status_history",
    "chat_sessions", "chat_questions", "chat_answers", "chat_messages",
]

#: Columns worth an index on the consolidated side: every dashboard filters or
#: joins on these, and without them a scan of the union is the only plan.
INDEX_ON = ["account_rid", "project_rid", "project_fiscal_rid", "case_rid",
            "fiscal_year", "session_rid"]

#: ``X_rid`` names its parent; the reference table is X, or its plural.
def resolve_ref(col: str, ref_tables: set[str]) -> str | None:
    if col in ("created_by", "modified_by"):
        return "user" if "user" in ref_tables else None
    if not col.endswith("_rid"):
        return None
    stem = col[:-4]
    for cand in (stem, stem + "s", stem + "es", re.sub(r"y$", "ies", stem)):
        if cand in ref_tables:
            return cand
    return None


CHAR = re.compile(r"^(character varying|character|text)")
NUM = re.compile(r"^(numeric|integer|bigint|smallint|double precision|real)")
TS = re.compile(r"^timestamp")


def widen(types: set[str], naive_tz: str) -> tuple[str, str | None]:
    """A type every variant fits in, and a note when the choice is lossy.

    Length and precision are dropped rather than taking the widest, because a
    consolidated column has no business rejecting a value that one tenant
    allowed. The timestamp case is the only one that can move data: a naive
    timestamp has to be told which zone it was recorded in.
    """
    if len(types) == 1:
        return next(iter(types)), None
    if all(CHAR.match(t) for t in types):
        return "text", None
    if all(NUM.match(t) for t in types):
        return "numeric", None
    if all(TS.match(t) for t in types):
        return ("timestamp with time zone",
                f"naive timestamps read as {naive_tz}")
    return "text", f"mixed families {sorted(types)} — forced to text"


def cast_expr(col: str, have: str | None, target: str, naive_tz: str) -> str:
    """One branch's expression for one consolidated column."""
    q = f'"{col}"'
    if have is None:
        return f"NULL::{target} AS {q}"
    if have == target:
        return q
    if TS.match(target) and have == "timestamp without time zone":
        return f"({q} AT TIME ZONE '{naive_tz}') AS {q}"
    return f"{q}::{target} AS {q}"


def build(pool, naive_tz: str) -> tuple[list[str], list[str]]:
    """Return (statements, notes)."""
    schemas = sorted(r[0] for r in pool.fetch("orgdb",
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name ~ %s",
        (TENANT_RE,)))
    ref_tables = {r[0] for r in pool.fetch("orgdb",
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        (REF_SCHEMA,))}

    # One catalogue read for everything, rather than a query per table.
    catalogue: dict[tuple[str, str], dict[str, str]] = {}
    for s, t, c, ty in pool.fetch("orgdb", """
            SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname ~ %s AND c.relkind = 'r'
              AND a.attnum > 0 AND NOT a.attisdropped""", (TENANT_RE,)):
        catalogue.setdefault((s, t), {})[c] = ty

    ref_display: dict[str, list[tuple[str, str]]] = {}
    for rt in ref_tables:
        cols = [r[0] for r in pool.fetch("orgdb",
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position""",
            (REF_SCHEMA, rt))]
        if rt == "user":
            ref_display[rt] = [("concat_ws(' ', {a}.first_name, {a}.last_name)", "name")]
            continue
        # The display column is the one carrying a name or a code; a reference
        # table without either is not worth joining.
        picks = [c for c in cols if ("name" in c or "code" in c)
                 and c not in ("created_by", "modified_by")]
        ref_display[rt] = [("{a}.\"%s\"" % c, c) for c in picks[:2]]

    stmts = [f'CREATE SCHEMA IF NOT EXISTS "{TARGET_SCHEMA}"', f"""
CREATE TABLE IF NOT EXISTS "{TARGET_SCHEMA}"."_consolidated_refresh" (
  view_name    varchar(128) PRIMARY KEY,
  row_count    bigint      NOT NULL,
  tenants      integer     NOT NULL,
  seconds      numeric(8,3) NOT NULL,
  refreshed_at timestamptz NOT NULL
)""".strip()]
    notes: list[str] = [f"tenant schemas discovered: {len(schemas)}"]

    for table in TABLES:
        here = [s for s in schemas if (s, table) in catalogue]
        if not here:
            notes.append(f"{table}: PRESENT IN NO SCHEMA — skipped")
            continue

        variants: dict[str, set[str]] = {}
        for s in here:
            for c, ty in catalogue[(s, table)].items():
                variants.setdefault(c, set()).add(ty)
        target_type = {}
        for c, tys in variants.items():
            target_type[c], note = widen(tys, naive_tz)
            if note:
                notes.append(f"{table}.{c}: {note}")

        cols = sorted(variants)
        pk = [r[0] for r in pool.fetch("orgdb", """
                SELECT a.attname FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
                WHERE i.indrelid = format('%%I.%%I', %s, %s)::regclass AND i.indisprimary""",
            (here[0], table))]
        if not pk and "rid" in variants:
            # Some tables carry a rid without declaring it a key. Falling back to
            # it needs no separate uniqueness check: if it is not unique, the
            # CREATE UNIQUE INDEX below fails and the whole build rolls back,
            # which is the right way round to find out.
            pk = ["rid"]
            notes.append(f"{table}: no declared primary key — keyed on rid, "
                         "proven by the unique index or the build fails")
        elif not pk:
            notes.append(f"{table}: no primary key and no rid — built WITHOUT a "
                         "unique index, so it cannot refresh CONCURRENTLY")

        branches = []
        for s in here:
            have = catalogue[(s, table)]
            exprs = [f"'{s}'::varchar(64) AS tenant_schema"]
            exprs += [cast_expr(c, have.get(c), target_type[c], naive_tz) for c in cols]
            branches.append("  SELECT " + ",\n         ".join(exprs) + f'\n  FROM "{s}"."{table}"')

        joins, outs, used = [], [], set(cols) | {"tenant_schema"}
        for c in cols:
            rt = resolve_ref(c, ref_tables)
            if not rt or not ref_display.get(rt):
                continue
            alias = "r%d" % len(joins)
            joins.append(f'  LEFT JOIN "{REF_SCHEMA}"."{rt}" {alias} ON {alias}.rid = u."{c}"')
            for expr, suffix in ref_display[rt]:
                base = c[:-4] + "_" + suffix if c.endswith("_rid") else c + "_" + suffix
                name = base if base not in used else base + "_ref"
                used.add(name)
                outs.append(f'  {expr.format(a=alias)} AS "{name}"')

        body = "\nUNION ALL\n".join(branches)
        select = "  u.*" + ((",\n" + ",\n".join(outs)) if outs else "")
        stmts.append(f'DROP MATERIALIZED VIEW IF EXISTS "{TARGET_SCHEMA}"."{table}" CASCADE')
        stmts.append(
            f'CREATE MATERIALIZED VIEW "{TARGET_SCHEMA}"."{table}" AS\n'
            f"WITH u AS (\n{body}\n)\nSELECT\n{select}\nFROM u\n"
            + ("\n".join(joins) + "\n" if joins else "")
            + "WITH DATA")
        if pk:
            key = ", ".join(['"tenant_schema"'] + [f'"{c}"' for c in pk])
            stmts.append(f'CREATE UNIQUE INDEX "{table}_pk" ON "{TARGET_SCHEMA}"."{table}" ({key})')
        for c in INDEX_ON:
            if c in variants:
                stmts.append(f'CREATE INDEX "{table}_{c}" ON "{TARGET_SCHEMA}"."{table}" ("{c}")')
        notes.append(f"{table}: {len(here)} tenants, {len(cols)} union columns, "
                     f"{len(joins)} reference joins, key={pk or 'NONE'}")
    return stmts, notes


def refresh(pool) -> None:
    conn = pool.get("orgdb")
    cur = conn.cursor()
    cur.execute("""SELECT matviewname FROM pg_matviews WHERE schemaname = %s
                   ORDER BY matviewname""", (TARGET_SCHEMA,))
    for (view,) in cur.fetchall():
        cur.execute("""SELECT count(*) FROM pg_index i
                       JOIN pg_class c ON c.oid = i.indexrelid
                       WHERE i.indrelid = format('%%I.%%I', %s, %s)::regclass
                         AND i.indisunique""", (TARGET_SCHEMA, view))
        concurrent = "CONCURRENTLY " if cur.fetchone()[0] else ""
        t0 = time.time()
        cur.execute(f'REFRESH MATERIALIZED VIEW {concurrent}"{TARGET_SCHEMA}"."{view}"')
        secs = time.time() - t0
        cur.execute(f'SELECT count(*), count(DISTINCT tenant_schema) FROM "{TARGET_SCHEMA}"."{view}"')
        n, tenants = cur.fetchone()
        cur.execute(f"""INSERT INTO "{TARGET_SCHEMA}"."_consolidated_refresh"
                          (view_name, row_count, tenants, seconds, refreshed_at)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (view_name) DO UPDATE SET
                          row_count = EXCLUDED.row_count, tenants = EXCLUDED.tenants,
                          seconds = EXCLUDED.seconds, refreshed_at = EXCLUDED.refreshed_at""",
                    (view, n, tenants, round(secs, 3), datetime.now(timezone.utc)))
        conn.commit()
        print(f"  {view:<34} {n:>9,} rows  {tenants:>2} tenants  {secs:6.2f}s"
              f"  {'concurrent' if concurrent else 'EXCLUSIVE LOCK'}")
    cur.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env", default="stage")
    ap.add_argument("--apply", action="store_true", help="execute; otherwise print the SQL")
    ap.add_argument("--refresh", action="store_true", help="refresh existing views")
    ap.add_argument("--naive-timezone", default="UTC",
                    help="zone assumed for tenants storing a naive timestamp (default UTC)")
    ap.add_argument("--out", help="write the generated SQL here")
    args = ap.parse_args()

    with ConnectionPool(Environment(args.env)) as pool:
        if args.refresh:
            refresh(pool)
            return 0

        stmts, notes = build(pool, args.naive_timezone)
        sql = ";\n\n".join(stmts) + ";\n"
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(sql)
        print("-- %d statements, %d characters" % (len(stmts), len(sql)))
        for n in notes:
            print("-- " + n)
        if not args.apply:
            print("-- nothing executed; pass --apply to build")
            return 0

        conn = pool.get("orgdb")
        cur = conn.cursor()
        try:
            for s in stmts:
                cur.execute(s)
            conn.commit()
            print("BUILT %d statements in %s" % (len(stmts), TARGET_SCHEMA))
        except Exception:
            conn.rollback()
            print("ROLLED BACK — nothing was created.", file=sys.stderr)
            raise
        finally:
            cur.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
