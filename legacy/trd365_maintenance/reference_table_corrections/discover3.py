#!/usr/bin/env python3
"""Read-only discovery PART 3 — FK constraints + column mirroring reality-check."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from engine import db  # noqa: E402
from correct import _fetch  # noqa: E402

REF_TABLES = ("task_template", "milestone_template",
              "checklist_template", "checklist_template_items")


def main():
    pool = db.ConnectionPool(db.load_config(HERE / "config" / "db_config.json"))
    try:
        # 1) Any real FK constraints referencing / on the template tables (main)?
        print("=" * 90)
        print("MAIN — foreign-key constraints touching the template tables")
        print("=" * 90)
        fks = _fetch(pool, "maindb",
            "SELECT tc.table_schema, tc.table_name, kcu.column_name, "
            "       ccu.table_schema, ccu.table_name, ccu.column_name, tc.constraint_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON tc.constraint_name=ccu.constraint_name "
            "WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='trd365' "
            "AND (tc.table_name = ANY(%s) OR ccu.table_name = ANY(%s))",
            [list(REF_TABLES), list(REF_TABLES)])
        if not fks:
            print("  (none — links are application-enforced, not DB FK constraints)")
        for r in fks:
            print(f"  {r[0]}.{r[1]}.{r[2]}  ->  {r[3]}.{r[4]}.{r[5]}   [{r[6]}]")

        # 2) Do org instance tables already carry reviewer_role / sequence_no?
        print("\n" + "=" * 90)
        print("ORG — existing reviewer_role / sequence_no columns (all tenant schemas)")
        print("=" * 90)
        rows = _fetch(pool, "orgdb",
            "SELECT column_name, table_name, count(DISTINCT table_schema) "
            "FROM information_schema.columns "
            "WHERE table_schema LIKE 'trd365\\_%' ESCAPE '\\' "
            "AND table_schema NOT LIKE '%backup%' "
            "AND column_name IN ('reviewer_role','reviewer_role_rid','sequence_no','sequence') "
            "GROUP BY column_name, table_name ORDER BY column_name, table_name")
        for col, tbl, nsch in rows:
            print(f"  {col:<20} on {tbl:<34} in {nsch} schema(s)")

        # 3) case_task <-> task_template linkage: does case_task have ANY task_template ref?
        print("\n" + "=" * 90)
        print("ORG — how case_task links to a template (its non-null *_template_rid columns)")
        print("=" * 90)
        cols = _fetch(pool, "orgdb",
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='trd365_00042' AND table_name='case_task' "
            "AND column_name LIKE '%template%rid' ORDER BY 1")
        print("  case_task template cols:", ", ".join(c[0] for c in cols) or "(none)")

        # 4) Are the main *_rid values UUID-ish? sample the PKs to understand consolidation keys
        print("\n" + "=" * 90)
        print("MAIN — sample rows of task_template (rid, task_name, milestone_template_rid, checklist_template_rid)")
        print("=" * 90)
        try:
            sample = _fetch(pool, "maindb",
                "SELECT rid, task_name, milestone_template_rid, checklist_template_rid, sequence_no "
                "FROM trd365.task_template ORDER BY milestone_sequence, sequence_no NULLS LAST LIMIT 12")
            for r in sample:
                print(f"  rid={r[0]}  name={str(r[1])[:34]:<34} mstone={str(r[2])[:12]} clist={str(r[3])[:12]} seq={r[4]}")
        except Exception as exc:
            print("  ERR", exc)
    finally:
        pool.close_all()


if __name__ == "__main__":
    main()
