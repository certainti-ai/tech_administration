#!/usr/bin/env python3
"""Read-only, FOCUSED discovery for the template restructuring.

Reference (template) tables in scope — all in maindb.trd365:
    task_template            (adding reviewer_role)
    milestone_template
    checklist_template
    checklist_template_items (adding sequence_no)

Reports: their structure + row counts, how they relate to each other, and which
columns across the org tenant schemas reference each one. Pure introspection.
"""
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from engine import db  # noqa: E402
from correct import _fetch, MAIN_SCHEMA  # noqa: E402
from psycopg2 import sql  # noqa: E402

REF_TABLES = ["task_template", "milestone_template",
              "checklist_template", "checklist_template_items"]

# candidate *_rid column prefixes that would point at each reference table
REF_REFCOLS = {
    "task_template":            ["task_template_rid"],
    "milestone_template":       ["milestone_template_rid"],
    "checklist_template":       ["checklist_template_rid"],
    "checklist_template_items": ["checklist_template_item_rid", "checklist_template_items_rid"],
}


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
        print("=" * 92)
        print(f"MAIN DB — {MAIN_SCHEMA}.<template tables> — structure + row counts")
        print("=" * 92)
        for t in REF_TABLES:
            cs = cols(pool, "maindb", MAIN_SCHEMA, t)
            if not cs:
                print(f"\n■ {MAIN_SCHEMA}.{t}   *** NOT FOUND ***")
                continue
            n = rowcount(pool, "maindb", MAIN_SCHEMA, t)
            print(f"\n■ {MAIN_SCHEMA}.{t}   rows={n}")
            for c, dt in cs:
                mark = "  <-- PK" if c == "rid" else ("  <-- FK *_rid" if c.endswith("_rid") else "")
                print(f"    {c:<34} {dt}{mark}")

        # org tenant schemas
        org_schemas = [r[0] for r in _fetch(pool, "orgdb",
            "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'trd365\\_%' ESCAPE '\\' "
            "AND nspname NOT LIKE '%backup%' ORDER BY 1")]
        print("\n" + "=" * 92)
        print(f"ORG DB — {len(org_schemas)} tenant schema(s)")
        print("=" * 92)
        print(", ".join(org_schemas))

        # Which columns across ALL org schemas reference each template table?
        # Use one catalog query across all tenant schemas, then match ref cols.
        print("\n" + "=" * 92)
        print("ORG DB — columns that reference the template tables (across all tenant schemas)")
        print("=" * 92)
        allcols = _fetch(pool, "orgdb",
            "SELECT table_schema, table_name, column_name FROM information_schema.columns "
            "WHERE table_schema LIKE 'trd365\\_%' ESCAPE '\\' "
            "AND table_schema NOT LIKE '%backup%' "
            "AND column_name LIKE '%template%rid' ORDER BY table_name, column_name")
        # group: refcol -> {table_name -> set(schemas)}
        by_ref = defaultdict(lambda: defaultdict(set))
        for sch, tbl, col in allcols:
            by_ref[col][tbl].add(sch)
        for ref_table, refcols in REF_REFCOLS.items():
            print(f"\n▶ {ref_table}  (via {', '.join(refcols)})")
            found = False
            for col in sorted(by_ref):
                if col in refcols:
                    for tbl, schs in sorted(by_ref[col].items()):
                        print(f"    {col:<34} -> org table '{tbl}'  in {len(schs)} schema(s)")
                        found = True
            if not found:
                print("    (no matching *_rid columns found — check naming)")

        # Show any other *template*rid columns we did NOT map (naming deviations)
        mapped = {c for cs in REF_REFCOLS.values() for c in cs}
        unmapped = sorted(c for c in by_ref if c not in mapped)
        if unmapped:
            print("\n" + "-" * 92)
            print("Other *template*rid columns present (unmapped — review naming):")
            for col in unmapped:
                tbls = sorted(by_ref[col])
                print(f"    {col:<40} in tables: {', '.join(tbls[:8])}"
                      + (" ..." if len(tbls) > 8 else ""))
    finally:
        pool.close_all()


if __name__ == "__main__":
    main()
