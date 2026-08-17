#!/usr/bin/env python3
"""Data-model analysis — base script.

Establishes connections to all three platform databases (Main, Org, TRD365AI)
reusing the account_deletion connection layer (engine/db.py: per-DB SSH tunnels,
connect retry/backoff, config from config/db_config.json), verifies each one,
then hands a ready ConnectionPool to `run_analysis()`.

The analysis logic itself is not written yet — drop it into `run_analysis()`
(marked with a TODO below). Everything above it is the reusable plumbing.

Usage:
    python analyze.py                       # connect to all 3, verify, run analysis
    python analyze.py --db orgdb            # limit to specific DB key(s)
    python analyze.py --config config/db_config.json

Passwords come from config/db_config.json, or env vars
PG_MAINDB_PASSWORD / PG_ORGDB_PASSWORD / PG_TRD365AI_PASSWORD and
SSH_TUNNEL_PASSWORD, or you'll be prompted.
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine import db  # noqa: E402

# Logical DB keys as defined in config/db_config.json.
DB_KEYS = ["maindb", "orgdb", "trd365ai"]
DEFAULT_CONFIG = HERE / "config" / "db_config.json"


def connect_all(pool, db_keys, log=print):
    """Open + verify a connection to each requested DB. Returns the list of keys
    that connected. Verification is a lightweight identity/version query."""
    connected = []
    for key in db_keys:
        try:
            conn = pool.get(key)
            cur = conn.cursor()
            cur.execute("SELECT current_database(), current_user, version()")
            dbname, user, version = cur.fetchone()
            cur.close()
            conn.rollback()  # end the read txn cleanly; leave no open transaction
            log(f"[ok] {key:<9} db={dbname} user={user} :: {version.split(',')[0]}")
            connected.append(key)
        except Exception as exc:
            log(f"[FAIL] {key:<9} {type(exc).__name__}: {str(exc).strip()[:160]}")
    return connected


def run_analysis(pool, db_keys, log=print):
    """Data-model analysis logic goes here.

    `pool.get(<db_key>)` returns a live psycopg2 connection for that database
    (one of DB_KEYS). Connections are reused across calls. Use a fresh cursor per
    query and `conn.rollback()` (or commit if you ever write) to end read txns.

    Example skeleton:
        conn = pool.get("orgdb")
        cur = conn.cursor()
        cur.execute("SELECT schema_name FROM information_schema.schemata")
        schemas = [r[0] for r in cur.fetchall()]
        cur.close(); conn.rollback()
        ...
    """
    # ────────────────────────────────────────────────────────────────────────
    # TODO: analysis logic to be provided next.
    # ────────────────────────────────────────────────────────────────────────
    log("\n(no analysis logic yet — add it in run_analysis() in analyze.py)")


def main():
    ap = argparse.ArgumentParser(description="Data-model analysis (base script).")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--db", nargs="*", choices=DB_KEYS, default=DB_KEYS,
                    help="Limit to specific DB key(s). Default: all three.")
    args = ap.parse_args()

    if not args.config.exists():
        sys.exit(f"Config not found: {args.config}")

    print("=" * 78)
    print("Data-Model Analysis")
    print(f"config : {args.config}")
    print(f"targets: {', '.join(args.db)}")
    print("=" * 78)

    pool = db.ConnectionPool(db.load_config(args.config))
    try:
        connected = connect_all(pool, args.db)
        if len(connected) != len(args.db):
            missing = [k for k in args.db if k not in connected]
            sys.exit(f"\nCould not connect to: {', '.join(missing)}. Aborting.")
        print("\nAll target databases connected.\n" + "-" * 78)
        run_analysis(pool, connected)
    finally:
        pool.close_all()
        print("\n[cleanup] connections + tunnels closed.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
