#!/usr/bin/env python3
"""
INTERACTION purge sub-module — delete one interaction and its subtree across
ORG + MAIN, with backup + audit. Pure subtree delete (no recompute).

Five phases: analyse → backup (shared `data_purge`) → delete (children-first,
multi-pass FK) → audit → report.

Note: `chat_sessions` references an interaction softly (no FK) and is NOT owned —
it is never touched by this module.

Usage:
    python purge_interaction.py --account-id ACC-00459 --interaction-rid P001-…            # DRY RUN
    python purge_interaction.py --account-id ACC-00459 --interaction-rid P001-… --apply
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from engine import db_pfy as db, subtree_purge, report  # noqa: E402
from project_fiscal import resolve  # noqa: E402
from interaction import scoping_interaction as SI  # noqa: E402

REPORTS_DIR = HERE / "reports"


def main():
    ap = argparse.ArgumentParser(description="Delete one interaction and its subtree (backup + audit).")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "db_config.json")
    ap.add_argument("--account-id", help="Account r_number (ACC-…) or account_rid.")
    ap.add_argument("--account-rid", help="Alias for --account-id.")
    ap.add_argument("--interaction-rid", required=True, help="Interaction rid to delete.")
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
        o = pool.get("orgdb")
        with o.cursor() as cur:
            cur.execute(f'SELECT 1 FROM "{schema}".interactions WHERE rid=%s', (args.interaction_rid,))
            found = cur.fetchone()
        o.rollback()
        if not found:
            sys.exit(f"Interaction not found in {schema}: {args.interaction_rid}")

        schema_for = {"org": schema, "main": SI.MAIN_SCHEMA}
        scoper = SI.InteractionScoper(args.interaction_rid)
        ctx = {"account_rid": acct["account_rid"], "r_number": acct["r_number"],
               "org_schema": schema, "interaction_rid": args.interaction_rid}

        print("=" * 78)
        print(f"INTERACTION PURGE  ({'DRY-RUN' if dry_run else 'LIVE APPLY'})")
        print(f"account     : {acct['r_number']}  ({acct['account_rid']})")
        print(f"schema      : {schema}")
        print(f"interaction : {args.interaction_rid}")
        print(f"backup      : schema '{subtree_purge.core.BACKUP_SCHEMA}' (per DB)")
        print("=" * 78)

        run, ok = subtree_purge.purge_entity(pool, "interaction", args.interaction_rid, schema_for,
                                             SI.STEPS, scoper, args.chunk_size, dry_run,
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
