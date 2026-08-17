#!/usr/bin/env python3
"""Read-only discovery PART 2 — org-side instance tables + all reference columns.

Focus: how case_task / activities / checklists / checklist-items in the org tenant
schemas link back to the four main templates, and to each other (task<->milestone
<->checklist<->items). Pure introspection.
"""
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from engine import db  # noqa: E402
from correct import _fetch  # noqa: E402
from psycopg2 import sql  # noqa: E402

SAMPLE = "trd365_00042"
# instance tables of interest in the org schema
ORG_TABLES = ["case_task", "activities", "checklists", "checklist_items",
              "case_checklist_items", "checklist_item", "case_milestone", "milestone",
              "milestones", "task", "tasks"]


def cols(pool, dbk, schema, table):
    return _fetch(pool, dbk,
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
        [schema, table])


def rowcount(pool, dbk, schema, table):
    try:
        return _fetch(pool, dbk, sql.SQL("SELECT count(*) FROM {}.{}").format(
            sql.Identifier(schema), sql.Identifier(table)))[0][0]
    except Exception as exc:
        return f"ERR:{str(exc).strip()[:40]}"


def main():
    pool = db.ConnectionPool(db.load_config(HERE / "config" / "db_config.json"))
    try:
        # First: list ALL tables in sample schema that mention our domain words,
        # so we discover the real names (checklist items table, milestone table).
        print("=" * 92)
        print(f"ORG '{SAMPLE}': all tables matching task/checklist/milestone/activit")
        print("=" * 92)
        real = [r[0] for r in _fetch(pool, "orgdb",
            "SELECT table_name FROM information_schema.tables WHERE table_schema=%s "
            "AND table_type='BASE TABLE' AND ("
            "table_name ILIKE '%%task%%' OR table_name ILIKE '%%checklist%%' OR "
            "table_name ILIKE '%%milestone%%' OR table_name ILIKE '%%activit%%') "
            "ORDER BY table_name", [SAMPLE])]
        for t in real:
            print(f"  {t:<40} rows={rowcount(pool,'orgdb',SAMPLE,t)}")

        # Detail the key instance tables (union of discovered + known candidates)
        detail = sorted(set(real) | set(ORG_TABLES))
        for t in detail:
            cs = cols(pool, "orgdb", SAMPLE, t)
            if not cs:
                continue
            print("\n" + "-" * 92)
            print(f"■ {SAMPLE}.{t}   rows={rowcount(pool,'orgdb',SAMPLE,t)}")
            for c, dt in cs:
                interesting = (c == "rid" or c.endswith("_rid") or
                               any(k in c.lower() for k in
                                   ("template", "sequence", "reviewer", "name",
                                    "milestone", "task", "checklist")))
                if interesting:
                    mark = "  <-- PK" if c == "rid" else ("  <-- *_rid" if c.endswith("_rid") else "")
                    print(f"    {c:<34} {dt}{mark}")

        # Cross-schema: every column referencing task/milestone/checklist instances
        print("\n" + "=" * 92)
        print("ORG (all schemas): distinct *_rid columns for task/milestone/checklist/item")
        print("=" * 92)
        rows = _fetch(pool, "orgdb",
            "SELECT column_name, table_name, count(DISTINCT table_schema) "
            "FROM information_schema.columns "
            "WHERE table_schema LIKE 'trd365\\_%' ESCAPE '\\' "
            "AND table_schema NOT LIKE '%backup%' "
            "AND column_name LIKE '%\\_rid' ESCAPE '\\' "
            "AND (column_name ILIKE '%task%' OR column_name ILIKE '%checklist%' "
            "OR column_name ILIKE '%milestone%') "
            "GROUP BY column_name, table_name ORDER BY column_name, table_name")
        by_col = defaultdict(list)
        for col, tbl, nsch in rows:
            by_col[col].append((tbl, nsch))
        for col in sorted(by_col):
            print(f"\n  {col}")
            for tbl, nsch in by_col[col]:
                print(f"      -> {tbl:<34} in {nsch} schema(s)")
    finally:
        pool.close_all()


if __name__ == "__main__":
    main()
