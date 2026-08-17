#!/usr/bin/env python3
"""Read-only discovery for interactions tables (for the metrics dashboard)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from engine import db  # noqa: E402
from correct import _fetch  # noqa: E402
from psycopg2 import sql  # noqa: E402

SAMPLE = "trd365_00042"


def cols(pool, dbk, schema, table):
    return _fetch(pool, dbk,
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position", [schema, table])


def rc(pool, dbk, schema, table):
    try:
        return _fetch(pool, dbk, sql.SQL("SELECT count(*) FROM {}.{}").format(
            sql.Identifier(schema), sql.Identifier(table)))[0][0]
    except Exception as exc:
        return f"ERR:{str(exc).strip()[:40]}"


def main():
    pool = db.ConnectionPool(db.load_config(HERE / "config" / "db_config.json"))
    try:
        # interaction tables present in sample org schema
        print("=" * 90)
        print(f"ORG '{SAMPLE}' — tables matching 'interaction'")
        print("=" * 90)
        tbls = [r[0] for r in _fetch(pool, "orgdb",
            "SELECT table_name FROM information_schema.tables WHERE table_schema=%s "
            "AND table_type='BASE TABLE' AND table_name ILIKE '%%interaction%%' ORDER BY 1", [SAMPLE])]
        for t in tbls:
            print(f"\n■ {SAMPLE}.{t}  rows={rc(pool,'orgdb',SAMPLE,t)}")
            for c, dt in cols(pool, "orgdb", SAMPLE, t):
                mark = ""
                lc = c.lower()
                if lc == "rid": mark = "  <-- PK"
                elif c.endswith("_rid"): mark = "  <-- *_rid"
                elif "date" in lc or "time" in lc: mark = "  <-- DATE/TIME"
                print(f"    {c:<34} {dt}{mark}")

        # does interactions live per-schema in all 26? count schemas having it
        print("\n" + "=" * 90)
        print("ORG — which interaction tables exist across all tenant schemas")
        print("=" * 90)
        rows = _fetch(pool, "orgdb",
            "SELECT table_name, count(DISTINCT table_schema) FROM information_schema.tables "
            "WHERE table_schema LIKE 'trd365\\_%' ESCAPE '\\' AND table_schema NOT LIKE '%backup%' "
            "AND table_name ILIKE '%%interaction%%' GROUP BY table_name ORDER BY 1")
        for t, n in rows:
            print(f"  {t:<40} in {n} schema(s)")

        # account table location (main)
        print("\n" + "=" * 90)
        print("MAIN — trd365.account columns (for account name join)")
        print("=" * 90)
        for c, dt in cols(pool, "maindb", "trd365", "account"):
            if c in ("rid",) or any(k in c.lower() for k in ("name", "account", "status", "code")):
                print(f"    {c:<34} {dt}")
    finally:
        pool.close_all()


if __name__ == "__main__":
    main()
