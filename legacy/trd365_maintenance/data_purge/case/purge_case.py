#!/usr/bin/env python3
"""
CASE purge sub-module — delete one case (credit study) and its whole subtree
across ORG + MAIN, with backup + audit. Pure subtree delete (no recompute — no
surviving aggregate depends on a case).

Five phases: analyse → backup (into shared `data_purge`) → delete (children-first,
multi-pass FK) → audit (0 residual, backups==deletes, no collateral) → report.

Usage:
    python purge_case.py --account-id ACC-00459 --case-rid P001-…            # DRY RUN
    python purge_case.py --account-id ACC-00459 --case-rid P001-… --apply
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from engine import db_pfy as db, subtree_purge, report  # noqa: E402
from project_fiscal import resolve  # noqa: E402  (account resolution)
from case import scoping_case as SC  # noqa: E402

REPORTS_DIR = HERE / "reports"


def main():
    ap = argparse.ArgumentParser(description="Delete one case and its subtree (backup + audit).")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "db_config.json")
    ap.add_argument("--account-id", help="Account r_number (ACC-…) or account_rid.")
    ap.add_argument("--account-rid", help="Alias for --account-id.")
    ap.add_argument("--case-rid", required=True, help="Case rid to delete.")
    ap.add_argument("--chunk-size", type=int, default=1000)
    ap.add_argument("--apply", action="store_true", help="Actually back up + delete. Omit for DRY RUN.")
    args = ap.parse_args()
    dry_run = not args.apply
    account_ref = args.account_id or args.account_rid
    if not account_ref:
        sys.exit("Provide --account-id (or --account-rid).")

    pool = db.ConnectionPool(db.load_config(args.config))
    try:
        acct = resolve.resolve_account(pool, account_ref)
        if not acct.get("exists"):
            sys.exit(f"Account not found: {account_ref}")
        schema = acct["org_schema"]
        # sanity: case exists in this schema
        o = pool.get("orgdb")
        with o.cursor() as cur:
            cur.execute(f'SELECT 1 FROM "{schema}".cases WHERE rid=%s', (args.case_rid,))
            found = cur.fetchone()
        o.rollback()
        if not found:
            sys.exit(f"Case not found in {schema}: {args.case_rid}")

        schema_for = {"org": schema, "main": SC.MAIN_SCHEMA}
        scoper = SC.CaseScoper(args.case_rid)
        ctx = {"account_rid": acct["account_rid"], "r_number": acct["r_number"],
               "org_schema": schema, "case_rid": args.case_rid}

        print("=" * 78)
        print(f"CASE PURGE  ({'DRY-RUN' if dry_run else 'LIVE APPLY'})")
        print(f"account : {acct['r_number']}  ({acct['account_rid']})")
        print(f"schema  : {schema}")
        print(f"case    : {args.case_rid}")
        print(f"backup  : schema '{subtree_purge.core.BACKUP_SCHEMA}' (per DB)")
        print("=" * 78)

        run, ok = subtree_purge.purge_entity(pool, "case", args.case_rid, schema_for,
                                             SC.STEPS, scoper, args.chunk_size, dry_run,
                                             log=print, context=ctx)
        txt, js = report.write_report(REPORTS_DIR, run)
        rep = report.summarize(run)
        tot = rep["totals"]
        print("\n" + "=" * 78)
        if dry_run:
            print(f"DRY-RUN — {tot['rows_in_scope']:,} rows in scope across "
                  f"{tot['tables_with_rows']} tables. Report: {txt}")
        else:
            print(f"{'DONE' if ok else 'FAILED'} — deleted {tot['rows_deleted']:,} rows; "
                  f"audit {'CLEAN' if rep['audit_clean'] else 'WARNINGS'}. Report: {txt}")
            if not ok:
                print(f"  error: {run.get('last_error')}"); pool.drop_all()
        print("=" * 78)
    finally:
        pool.close_all()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted."); sys.exit(130)
