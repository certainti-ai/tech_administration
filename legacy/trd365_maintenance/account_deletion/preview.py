#!/usr/bin/env python3
"""
Read-only preview: export the exact rows that WOULD be deleted for an account,
one CSV per table (schema-qualified), plus an index summary. No writes, no
deletes — uses the same account-scope predicates as the deletion engine.

Usage:
    python preview.py                              # first 'To be Processed' row in the CSV
    python preview.py --account P001-....          # a specific rid
    python preview.py --account P001-... --max-rows 5000   # cap rows per table (default 10000)
"""

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine import db, engine  # noqa: E402
from engine import deletion_manifest as M  # noqa: E402

DEFAULT_CONFIG = HERE / "config" / "db_config.json"
DEFAULT_INPUT = HERE / "input" / "accounts.csv"


def _safe(s):
    return "".join(c if c.isalnum() else "_" for c in s)


def pick_account(input_csv, explicit):
    if explicit:
        return explicit
    with open(input_csv, newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("status", "").strip().lower() == "to be processed":
                return row["account_rid"].strip()
    sys.exit("No --account given and no 'To be Processed' row in the input CSV.")


def main():
    ap = argparse.ArgumentParser(description="Read-only preview of rows to be deleted.")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--account", default=None)
    ap.add_argument("--max-rows", type=int, default=10000, help="cap rows exported per table")
    args = ap.parse_args()

    rid = pick_account(args.input, args.account)
    pool = db.ConnectionPool(db.load_config(args.config))
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    outdir = HERE / "reports" / f"preview_{_safe(rid)}_{ts}"
    outdir.mkdir(parents=True, exist_ok=True)

    try:
        acct = engine.resolve_account(pool, rid)
        if not acct.get("exists"):
            sys.exit(f"Account {rid} not found in trd365.account (already deleted or wrong id).")
        print(f"Account {rid}  r_number={acct['r_number']}  org_schema={acct['org_schema']}  "
              f"storage_type={acct['storage_type']}")
        sets = engine.capture_id_sets(pool, acct)
        print("id-sets: " + ", ".join(f"{k}={len(v)}" for k, v in sets.items()))
        schema_for = {"org": acct["org_schema"], "main": M.MAIN_SCHEMA, "ai": M.AI_SCHEMA}

        index = []  # (step, schema, table, rows, exported, file)
        for step_key, db_key, kind, tables in M.STEPS:
            conn = pool.get(db_key)
            schema = schema_for[kind]
            print(f"\n=== {step_key} ({db_key} / {schema}) ===")
            for table in tables:
                conn.rollback()
                if not engine.table_exists(conn, schema, table):
                    continue
                pred = engine.build_predicate(conn, schema, table, acct, sets, kind)
                if pred is None:
                    index.append((step_key, schema, table, "UNSCOPED", 0, ""))
                    print(f"  {schema}.{table}: UNSCOPED")
                    continue
                where, params = pred
                n = engine.count_where(conn, schema, table, where, params)
                if n == 0:
                    continue
                fname = f"{step_key}__{schema}__{table}.csv"
                with conn.cursor() as cur:
                    cur.execute(f'SELECT * FROM {engine._q(schema)}.{engine._q(table)} '
                                f'WHERE {where} LIMIT {args.max_rows}', params)
                    cols = [d[0] for d in cur.description]
                    rows = cur.fetchall()
                conn.rollback()
                with open(outdir / fname, "w", newline="") as fh:
                    w = csv.writer(fh)
                    w.writerow(cols)
                    w.writerows(rows)
                index.append((step_key, schema, table, n, len(rows), fname))
                trunc = "  (TRUNCATED)" if n > len(rows) else ""
                print(f"  {schema}.{table}: {n} row(s) -> {fname}{trunc}")

        # index file
        with open(outdir / "_INDEX.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["step", "schema", "table", "rows_in_scope", "rows_exported", "file"])
            w.writerows(index)
        total = sum(r[3] for r in index if isinstance(r[3], int))
        print(f"\nTotal rows in scope: {total}")
        print(f"Preview exported to: {outdir}")
        print("Open _INDEX.csv for the table list, or each per-table CSV to review rows.")
    finally:
        pool.close_all()


if __name__ == "__main__":
    main()
