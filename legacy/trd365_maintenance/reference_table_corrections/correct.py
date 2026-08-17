#!/usr/bin/env python3
"""Reference-table data corrections — base script (Main + Org DB).

Purpose
-------
Impact analysis and controlled correction of REFERENCE / LOOKUP table data in the
two platform databases:

    maindb -> thinkrd365_pvt_main   (shared/global schema: `trd365`)
    orgdb  -> thinkrd365_pvt_org    (per-tenant schemas: `trd365_<nnnnn>`)

This file is the reusable plumbing only — it establishes + verifies connections
to Main and Org (reusing the account_deletion / data_model_analysis engine layer:
per-DB SSH tunnels, connect retry/backoff, config from config/db_config.json),
then hands a ready ConnectionPool to `run_corrections()`.

The correction logic itself is NOT written yet — it goes in `run_corrections()`
(marked with a TODO). Requirements will be provided later.

Data-model conventions (from data_model_analysis/model_analysis.py)
-------------------------------------------------------------------
* Most tables have primary key `rid`; foreign refs are `{entity}_rid`
  (e.g. project.rid <- some_table.project_rid).
* PRIMARY entities and their parents:
      account  -> maindb  trd365.account            (cross-DB: referenced from org)
      project  -> orgdb   <tenant>.project
      resource -> orgdb   <tenant>.resources        (plural)
      case     -> orgdb   <tenant>.cases            (plural; referenced as case_rid)
* Reference/lookup tables typically live in the shared `trd365` schema (main) and
  are referenced by a stable prefix across many tenant tables (see the
  "global-lookup" classification in model_analysis.py).

Safety model (corrections = writes)
-----------------------------------
* Runs in DRY-RUN by default: it opens read txns, reports what WOULD change, and
  never commits. Pass --apply to actually write.
* Every write path must run inside a single transaction per DB and only commit
  when --apply is set (use the `execute_write()` helper). Nothing auto-commits.

Usage
-----
    python correct.py                       # connect to main+org, verify (dry-run)
    python correct.py --db orgdb            # limit to specific DB key(s)
    python correct.py --apply               # actually commit corrections
    python correct.py --config config/db_config.json

Passwords come from config/db_config.json, or env vars
PG_MAINDB_PASSWORD / PG_ORGDB_PASSWORD and SSH_TUNNEL_PASSWORD, or you'll be prompted.
"""

import argparse
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

QUERY_TIMEOUT = 90  # seconds; guards against tunnel-death hangs (dead socket, no read timeout)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine import db  # noqa: E402
try:
    from psycopg2 import sql as _sql  # noqa: F401  (re-exported for correction logic)
except ImportError:
    sys.exit("psycopg2 required. pip install -r requirements.txt")

# Logical DB keys as defined in config/db_config.json.
DB_KEYS = ["maindb", "orgdb"]
DEFAULT_CONFIG = HERE / "config" / "db_config.json"
MAIN_SCHEMA = "trd365"  # shared/global schema in maindb (holds most reference tables)


def _fetch(pool, dbk, query, params=None, timeout=QUERY_TIMEOUT):
    """Run a READ query with a watchdog timeout. If a dropped tunnel leaves the
    socket dead (psycopg2 has no read timeout), drop the connection to abort the
    hung read and raise, so the caller can skip/continue instead of hanging.
    Always rolls back — never mutates."""
    conn = pool.get(dbk)
    box = {}

    def work():
        try:
            cur = conn.cursor()
            cur.execute(query, params) if params is not None else cur.execute(query)
            box["rows"] = cur.fetchall()
            cur.close()
            conn.rollback()
        except BaseException as exc:  # noqa: BLE001 - reported to caller
            box["err"] = exc

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        pool.drop(dbk)  # close the socket to unblock the hung query; next get() reconnects
        raise TimeoutError(f"query timed out after {timeout}s on {dbk} (tunnel likely dropped)")
    if "err" in box:
        raise box["err"]
    return box["rows"]


def execute_write(pool, dbk, query, params=None, apply=False, log=print):
    """Run a WRITE statement. Commits only when apply=True; otherwise rolls back
    (dry-run). Returns the affected row count. Use this for every mutation so the
    dry-run guarantee holds uniformly."""
    conn = pool.get(dbk)
    cur = conn.cursor()
    try:
        cur.execute(query, params) if params is not None else cur.execute(query)
        n = cur.rowcount
        if apply:
            conn.commit()
            log(f"[apply] {dbk}: {n} row(s) affected, committed.")
        else:
            conn.rollback()
            log(f"[dry-run] {dbk}: {n} row(s) would be affected (rolled back).")
        return n
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


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


def run_corrections(pool, db_keys, apply=False, log=print):
    """Reference-table correction logic goes here.

    `pool.get(<db_key>)` returns a live psycopg2 connection for that database
    (one of DB_KEYS). Connections are reused across calls.

    Read with `_fetch(pool, dbk, sql, params)` (watchdog + auto-rollback).
    Write with `execute_write(pool, dbk, sql, params, apply=apply)` so nothing
    commits unless --apply was passed.

    Example skeleton:
        # inspect a reference table in main
        rows = _fetch(pool, "maindb",
            _sql.SQL("SELECT rid, code, name FROM {}.status_master ORDER BY rid")
                .format(_sql.Identifier(MAIN_SCHEMA)))
        # apply a correction (dry-run unless --apply)
        execute_write(pool, "maindb",
            _sql.SQL("UPDATE {}.status_master SET name=%s WHERE rid=%s")
                .format(_sql.Identifier(MAIN_SCHEMA)), ["Active", 3], apply=apply)
    """
    # ────────────────────────────────────────────────────────────────────────
    # TODO: correction logic to be provided next.
    # ────────────────────────────────────────────────────────────────────────
    mode = "APPLY (writes will commit)" if apply else "DRY-RUN (no commits)"
    log(f"\nmode: {mode}")
    log("(no correction logic yet — add it in run_corrections() in correct.py)")


def main():
    ap = argparse.ArgumentParser(description="Reference-table data corrections (base script).")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--db", nargs="*", choices=DB_KEYS, default=DB_KEYS,
                    help="Limit to specific DB key(s). Default: main + org.")
    ap.add_argument("--apply", action="store_true",
                    help="Commit corrections. Without this, runs dry-run (no writes committed).")
    args = ap.parse_args()

    if not args.config.exists():
        sys.exit(f"Config not found: {args.config}")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print("=" * 78)
    print("Reference-Table Data Corrections")
    print(f"time   : {stamp}")
    print(f"config : {args.config}")
    print(f"targets: {', '.join(args.db)}")
    print(f"mode   : {'APPLY' if args.apply else 'DRY-RUN'}")
    print("=" * 78)

    pool = db.ConnectionPool(db.load_config(args.config))
    try:
        connected = connect_all(pool, args.db)
        if len(connected) != len(args.db):
            missing = [k for k in args.db if k not in connected]
            sys.exit(f"\nCould not connect to: {', '.join(missing)}. Aborting.")
        print("\nAll target databases connected.\n" + "-" * 78)
        run_corrections(pool, connected, apply=args.apply)
    finally:
        pool.close_all()
        print("\n[cleanup] connections + tunnels closed.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
