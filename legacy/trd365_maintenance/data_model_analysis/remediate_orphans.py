#!/usr/bin/env python3
"""Backup + delete orphan records for ONE org tenant schema, with validation.

An "orphan record" here is a child row whose `{entity}_rid` points at a parent
`rid` that no longer exists (same-schema parents for project/resource/case/…, and
cross-DB main.trd365.account for account_rid). For the target schema this tool:

  1. IDENTIFIES orphan child rows per table and captures their exact `rid`s
     (the "specific ids" — every delete is scoped to these captured ids).
  2. BACKS UP the full rows into a fresh backup schema
     (orphan_bak_<schema>_<ts>.bak_<table>), in the SAME transaction as the
     delete so they commit or roll back together.
  3. DELETES the child rows by those captured ids.
  4. VALIDATES, before committing each table, that ONLY orphans were removed:
       - rows deleted == orphan ids captured   (no over-delete)
       - total_after == total_before - orphans (nothing extra gone)
       - re-check finds 0 remaining orphans     (all orphans gone)
     If any check fails, that table is ROLLED BACK and the run aborts.

Every child table modified lives in the org DB, so each table is a single-DB
transaction. Tables without a `rid` primary key are reported and SKIPPED (can't
delete-by-specific-id safely).

Usage:
    python remediate_orphans.py --schema trd365_00416              # DRY RUN (default): report only
    python remediate_orphans.py --schema trd365_00416 --apply      # backup + delete + validate
    python remediate_orphans.py --schema trd365_00416 --tables project_timeline,project_history --apply
"""

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2  # noqa: E402  (error types for retry)
import psycopg2.errors  # noqa: E402
CONN_ERRS = (psycopg2.OperationalError, psycopg2.InterfaceError)
FK_ERR = psycopg2.errors.ForeignKeyViolation

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine import db  # noqa: E402
from model_analysis import (catalog, resolve_parent, _fetch, PRIMARY,  # noqa: E402
                            BACKUP_TABLE_RE)
from psycopg2 import sql as S_  # noqa: E402

CHUNK = 5000  # ids per backup/delete batch


def build_edges(pool, schema, main_schema, acct_parent):
    """Return (edges, org_cat). edges: (table, col, entity, pdbk, pschema, ptable)."""
    org_cat = catalog(pool, "orgdb", schema)
    rid_tables = {t for t, d in org_cat.items() if d["has_rid"]}
    edges = []
    for t, d in org_cat.items():
        if BACKUP_TABLE_RE.search(t):
            continue
        for col in d["rid_cols"]:
            if col == "account_rid":
                if acct_parent:
                    edges.append((t, col, "account", "maindb", main_schema, "account"))
            else:
                ptbl, _ = resolve_parent(col, rid_tables)
                if ptbl:
                    ek = {"project": "project", "resources": "resource", "cases": "case"}.get(ptbl, ptbl)
                    edges.append((t, col, ek, "orgdb", schema, ptbl))
    return edges, org_cat


def orphan_child_rids(pool, schema, table, col, entity, ptable, acct_valid):
    """rids of child rows in `table` whose `col` is orphaned (parent rid absent)."""
    if entity == "account":  # cross-DB: filter child rows against main account set
        rows = _fetch(pool, "orgdb", S_.SQL(
            "SELECT rid, {c} FROM {s}.{t} WHERE {c} IS NOT NULL"
        ).format(c=S_.Identifier(col), s=S_.Identifier(schema), t=S_.Identifier(table)))
        return {rid for rid, val in rows if val not in acct_valid}
    rows = _fetch(pool, "orgdb", S_.SQL(
        "SELECT c.rid FROM {s}.{t} c WHERE c.{col} IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM {s}.{pt} p WHERE p.rid = c.{col})"
    ).format(s=S_.Identifier(schema), t=S_.Identifier(table),
             col=S_.Identifier(col), pt=S_.Identifier(ptable)))
    return {r[0] for r in rows}


def orphan_count(pool, schema, table, col, entity, ptable, acct_valid):
    """Count orphans for one edge without needing the child's rid (for no-rid tables)."""
    if entity == "account":
        rows = _fetch(pool, "orgdb", S_.SQL(
            "SELECT {c} FROM {s}.{t} WHERE {c} IS NOT NULL"
        ).format(c=S_.Identifier(col), s=S_.Identifier(schema), t=S_.Identifier(table)))
        return sum(1 for (v,) in rows if v not in acct_valid)
    return _fetch(pool, "orgdb", S_.SQL(
        "SELECT count(*) FROM {s}.{t} c WHERE c.{col} IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM {s}.{pt} p WHERE p.rid=c.{col})"
    ).format(s=S_.Identifier(schema), t=S_.Identifier(table),
             col=S_.Identifier(col), pt=S_.Identifier(ptable)))[0][0]


def remaining_orphans(cur, schema, table, col, entity, ptable, acct_valid):
    """Count orphans for one edge using an existing cursor (post-delete, in-txn)."""
    if entity == "account":
        cur.execute(S_.SQL("SELECT {c} FROM {s}.{t} WHERE {c} IS NOT NULL").format(
            c=S_.Identifier(col), s=S_.Identifier(schema), t=S_.Identifier(table)))
        return sum(1 for (v,) in cur.fetchall() if v not in acct_valid)
    cur.execute(S_.SQL(
        "SELECT count(*) FROM {s}.{t} c WHERE c.{col} IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM {s}.{pt} p WHERE p.rid=c.{col})"
    ).format(s=S_.Identifier(schema), t=S_.Identifier(table),
             col=S_.Identifier(col), pt=S_.Identifier(ptable)))
    return cur.fetchone()[0]


def main():
    ap = argparse.ArgumentParser(description="Backup + delete orphan records for one schema, with validation.")
    ap.add_argument("--config", type=Path, default=HERE / "config" / "db_config.json")
    ap.add_argument("--schema", default="trd365_00416", help="Org tenant schema to remediate.")
    ap.add_argument("--main-schema", default="trd365")
    ap.add_argument("--tables", help="Comma-separated subset of child tables (default: all with orphans).")
    ap.add_argument("--exclude-entities", help="Comma-separated entities/parent tables to skip "
                    "(global-lookup masters are auto-excluded regardless).")
    ap.add_argument("--apply", action="store_true", help="Actually back up + delete. Omit for DRY RUN.")
    ap.add_argument("--out-dir", type=Path, default=HERE / "reports")
    args = ap.parse_args()
    dry = not args.apply
    only = set(t.strip() for t in args.tables.split(",")) if args.tables else None

    pool = db.ConnectionPool(db.load_config(args.config))
    schema = args.schema
    run_at = datetime.now(timezone.utc)
    stamp = run_at.strftime("%Y%m%d_%H%M%S")
    bak_schema = f"orphan_bak_{schema}_{stamp}"[:63]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = args.out_dir / f"orphan_cleanup_{schema}_{stamp}.csv"
    log = print
    try:
        log("=" * 90)
        log(f"ORPHAN REMEDIATION  |  schema={schema}  |  mode={'DRY-RUN' if dry else 'APPLY'}")
        if not dry:
            log(f"backup schema = {bak_schema}")
        log("=" * 90)

        acct_parent = bool(_fetch(pool, "maindb",
            "SELECT 1 FROM information_schema.columns WHERE table_schema=%s AND "
            "table_name='account' AND column_name='rid'", [args.main_schema]))
        acct_valid = set()
        if acct_parent:
            acct_valid = {r[0] for r in _fetch(pool, "maindb", S_.SQL(
                "SELECT rid FROM {}.{}").format(S_.Identifier(args.main_schema), S_.Identifier("account")))}
        log(f"valid account rids in main.{args.main_schema}.account: {len(acct_valid)}\n")

        edges, org_cat = build_edges(pool, schema, args.main_schema, acct_parent)

        # ── SAFETY: exclude global-lookup entities ─────────────────────────────
        # An entity whose per-tenant parent table is EMPTY but which has a master
        # table in main.trd365 (e.g. interaction_type) is global reference data —
        # its "orphans" are false positives (the real parent is the master), so
        # never delete those rows.
        parents = {(psch, ptbl) for (_, _, ek, dbk, psch, ptbl) in edges if ek != "account"}
        global_excl = set()
        for (psch, ptbl) in parents:
            cnt = _fetch(pool, "orgdb", S_.SQL("SELECT count(*) FROM {s}.{t}").format(
                s=S_.Identifier(psch), t=S_.Identifier(ptbl)))[0][0]
            if cnt == 0 and _fetch(pool, "maindb",
                    "SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
                    [args.main_schema, ptbl]):
                global_excl.add(ptbl)
        manual_excl = set(e.strip() for e in (args.exclude_entities or "").split(",") if e.strip())
        if global_excl:
            log(f"EXCLUDING global-lookup entities (empty per-tenant + master in main): {sorted(global_excl)}")
        if manual_excl:
            log(f"EXCLUDING (via --exclude-entities): {sorted(manual_excl)}")
        edges = [e for e in edges if e[5] not in global_excl and e[2] not in manual_excl and e[5] not in manual_excl]
        log("")

        # group edges by child table
        by_table = {}
        for (t, col, ek, pdbk, psch, ptbl) in edges:
            by_table.setdefault(t, []).append((col, ek, ptbl))

        def process_table(t):
            """Identify + (dry) report or (apply) backup/delete/validate one table.
            Returns (row_dict_or_None, abort_bool). Raises CONN_ERRS for the caller
            to retry on a dropped tunnel (nothing is committed until validation passes)."""
            has_rid = org_cat.get(t, {}).get("has_rid", False)
            if not has_rid:
                # cannot delete-by-specific-id without a rid PK; count-only report
                per_col = {col: orphan_count(pool, schema, t, col, ek, ptbl, acct_valid)
                           for (col, ek, ptbl) in by_table[t]}
                tot = sum(per_col.values())
                if not tot:
                    return None, False
                cols_desc = ", ".join(f"{c}={n}" for c, n in per_col.items() if n)
                log(f"  SKIP {t}: orphan rows present but NO rid PK — cannot delete-by-id safely. ({cols_desc})")
                return {"schema": schema, "table": t, "orphan_rows": tot,
                        "action": "SKIPPED (no rid PK)", "by_column": cols_desc}, False
            union, per_col = set(), {}
            for (col, ek, ptbl) in by_table[t]:
                rids = orphan_child_rids(pool, schema, t, col, ek, ptbl, acct_valid)
                per_col[col] = len(rids)
                union |= rids
            if not union:
                return None, False
            total_before = _fetch(pool, "orgdb", S_.SQL("SELECT count(*) FROM {s}.{t}").format(
                s=S_.Identifier(schema), t=S_.Identifier(t)))[0][0]
            cols_desc = ", ".join(f"{c}={n}" for c, n in per_col.items() if n)
            log(f"  {t}: {len(union)} orphan rows of {total_before} total  ({cols_desc})")
            if dry:
                return {"schema": schema, "table": t, "orphan_rows": len(union),
                        "action": "would delete", "by_column": cols_desc}, False

            # ── APPLY: backup + delete + validate in one transaction ───────────
            ids = list(union)
            conn = pool.get("orgdb")
            cur = conn.cursor()
            try:
                cur.execute(S_.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(S_.Identifier(bak_schema)))
                bakt = f"bak_{t}"[:63]
                cur.execute(S_.SQL("CREATE TABLE IF NOT EXISTS {bs}.{bt} (LIKE {s}.{t} INCLUDING DEFAULTS)").format(
                    bs=S_.Identifier(bak_schema), bt=S_.Identifier(bakt), s=S_.Identifier(schema), t=S_.Identifier(t)))
                cur.execute(S_.SQL("ALTER TABLE {bs}.{bt} ADD COLUMN IF NOT EXISTS _orphan_run_at TIMESTAMPTZ").format(
                    bs=S_.Identifier(bak_schema), bt=S_.Identifier(bakt)))
                backed = deleted = 0
                for i in range(0, len(ids), CHUNK):
                    chunk = ids[i:i + CHUNK]
                    cur.execute(S_.SQL(
                        "INSERT INTO {bs}.{bt} SELECT c.*, %s FROM {s}.{t} c WHERE c.rid = ANY(%s)"
                    ).format(bs=S_.Identifier(bak_schema), bt=S_.Identifier(bakt),
                             s=S_.Identifier(schema), t=S_.Identifier(t)), [run_at, chunk])
                    backed += cur.rowcount
                    cur.execute(S_.SQL("DELETE FROM {s}.{t} WHERE rid = ANY(%s)").format(
                        s=S_.Identifier(schema), t=S_.Identifier(t)), [chunk])
                    deleted += cur.rowcount
                cur.execute(S_.SQL("SELECT count(*) FROM {s}.{t}").format(
                    s=S_.Identifier(schema), t=S_.Identifier(t)))
                total_after = cur.fetchone()[0]
                remain = sum(remaining_orphans(cur, schema, t, col, ek, ptbl, acct_valid)
                             for (col, ek, ptbl) in by_table[t])
                ok = (backed == len(union) and deleted == len(union)
                      and total_after == total_before - len(union) and remain == 0)
                if ok:
                    conn.commit()
                    log(f"     ✓ backed up {backed}, deleted {deleted}, "
                        f"{total_before}->{total_after}, remaining_orphans={remain}  COMMITTED")
                    return {"schema": schema, "table": t, "orphan_rows": len(union),
                            "action": f"deleted {deleted}", "by_column": cols_desc}, False
                conn.rollback()
                log(f"     ✗ VALIDATION FAILED (backed={backed} deleted={deleted} "
                    f"before={total_before} after={total_after} remaining={remain} expected_del={len(union)}) "
                    f"— ROLLED BACK. Aborting run.")
                return {"schema": schema, "table": t, "orphan_rows": len(union),
                        "action": "VALIDATION FAILED - rolled back", "by_column": cols_desc}, True
            except CONN_ERRS:
                conn.rollback()
                raise  # caller retries; nothing committed
            except FK_ERR as exc:
                # This table's orphans are blocked by dependent rows in another
                # table (real DB FK constraint). Skip it and continue the schema —
                # do NOT abort. (e.g. account_details blocked by ~38 child tables
                # in store_in_parent schemas; handle that residue separately.)
                conn.rollback()
                detail = str(exc).strip().split("\n")[0][:140]
                log(f"     ⚠ FK-BLOCKED on {t}: {detail} — ROLLED BACK, SKIPPING (continuing schema).")
                return {"schema": schema, "table": t, "orphan_rows": len(union),
                        "action": "SKIPPED (FK-blocked by dependents)", "by_column": cols_desc}, False
            except Exception as exc:
                conn.rollback()
                log(f"     ✗ ERROR on {t}: {type(exc).__name__}: {str(exc).strip()[:120]} — ROLLED BACK. Aborting.")
                return {"schema": schema, "table": t, "orphan_rows": len(union),
                        "action": f"ERROR: {type(exc).__name__}", "by_column": cols_desc}, True

        rows_out = []
        grand_del = 0
        abort = False
        for t in sorted(by_table):
            if only and t not in only:
                continue
            row, abort = None, False
            for attempt in range(1, 5):  # retry per table on dropped tunnel
                try:
                    row, abort = process_table(t)
                    break
                except CONN_ERRS as exc:
                    if attempt < 4:
                        log(f"     [retry] {t}: connection dropped, reconnecting ({attempt}/3)…")
                        pool.drop_all(); time.sleep(3 * attempt)
                    else:
                        log(f"  {t}: FAILED after retries ({str(exc).strip()[:60]}) — skipped")
                        row, abort = ({"schema": schema, "table": t, "orphan_rows": "",
                                       "action": "conn-error skipped", "by_column": ""}, False)
                except Exception as exc:  # identification error: skip (dry) / stop (apply)
                    log(f"  {t}: ERROR {type(exc).__name__}: {str(exc).strip()[:90]} — "
                        + ("skipped" if dry else "aborting"))
                    row, abort = ({"schema": schema, "table": t, "orphan_rows": "",
                                   "action": f"ERROR: {type(exc).__name__}", "by_column": ""}, not dry)
                    break
            if row:
                rows_out.append(row)
                if "deleted" in row["action"]:
                    grand_del += int(row["action"].split()[1])
                elif "would delete" in row["action"]:
                    grand_del += row["orphan_rows"]
            if abort:
                break

        with open(report, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["schema", "table", "orphan_rows", "action", "by_column"])
            w.writeheader(); w.writerows(rows_out)

        log("\n" + "=" * 90)
        log(f"{'DRY-RUN — would delete' if dry else 'APPLIED — deleted'} {grand_del} orphan rows "
            f"across {len([r for r in rows_out if 'delete' in r['action'] or 'would' in r['action']])} table(s)")
        if not dry:
            log(f"backups in schema: {bak_schema}  (restore from orphan_bak_*.bak_<table>)")
        log(f"report: {report}")
        log("=" * 90)
    finally:
        pool.close_all()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
