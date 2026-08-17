#!/usr/bin/env python3
"""
PROJECT_FISCAL purge sub-module — delete ONE project fiscal-year across ORG +
MAIN + TRD365AI, WITH parent-aggregate recompute, backup, and audit.

This is the atomic unit the project sub-module iterates. It runs the vetted vendor
SECTION 1–8 flow (base_sql/) for a single fiscal:
  * is_last_fiscal is computed automatically (TRUE only if this is the project's
    ONLY remaining fiscal — then the project row + project-level children are also
    removed). Override with --last-fiscal / --not-last-fiscal.
  * When is_last_fiscal is FALSE the parent `project` is KEPT and its rollups (and
    the account-level aggregates) are RECOMPUTED to exclude this fiscal.

Usage:
    python purge_project_fiscal.py --account-id ACC-00459 --project-fiscal-rid P001-…           # DRY RUN
    python purge_project_fiscal.py --account-id ACC-00459 --project-fiscal-rid P001-… --apply
    python purge_project_fiscal.py --account-rid P001-… --project-fiscal-rid P001-… --apply --not-last-fiscal
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from engine import db_pfy as db  # noqa: E402
from project_fiscal import resolve, fiscal_flow  # noqa: E402
# reuse the project sub-module's report writer for a consistent format
sys.path.insert(0, str(ROOT / "project"))
import purge_project as PP  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Delete ONE project fiscal (with recompute).")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "db_config.json")
    ap.add_argument("--account-id", help="Account r_number (ACC-…) or account_rid.")
    ap.add_argument("--account-rid", help="Alias for --account-id.")
    ap.add_argument("--project-fiscal-rid", required=True, help="project_fiscal rid to delete.")
    ap.add_argument("--apply", action="store_true", help="Actually run. Omit for DRY RUN.")
    ap.add_argument("--verbose", action="store_true")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--last-fiscal", dest="last", action="store_true", default=None,
                   help="Force is_last_fiscal=TRUE (also delete the project row).")
    g.add_argument("--not-last-fiscal", dest="last", action="store_false",
                   help="Force is_last_fiscal=FALSE (keep + recompute the project).")
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
        fi = resolve.resolve_fiscal(pool, schema, args.project_fiscal_rid)
        if not fi:
            sys.exit(f"project_fiscal not found in {schema}: {args.project_fiscal_rid}")
        project_rid = fi["project_rid"]
        # is_last_fiscal: does the project have other fiscals?
        all_fiscals = resolve.project_fiscals(pool, schema, project_rid)
        computed_last = len(all_fiscals) <= 1
        is_last = computed_last if args.last is None else args.last

        row = {"schema_name": schema, "account_rid": acct["account_rid"],
               "project_rid": project_rid, "project_fiscal_id": args.project_fiscal_rid,
               "fiscal_year": fi["fiscal_year"] if fi["fiscal_year"] is not None else "",
               "is_last_fiscal": is_last}
        ctx = {"account_rid": acct["account_rid"], "r_number": acct["r_number"],
               "org_schema": schema, "project_rid": project_rid}

        print("=" * 78)
        print(f"PROJECT_FISCAL PURGE  ({'DRY-RUN' if dry_run else 'LIVE APPLY'})")
        print(f"account   : {acct['r_number']}  ({acct['account_rid']})")
        print(f"schema    : {schema}")
        print(f"project   : {project_rid}")
        print(f"fiscal    : {args.project_fiscal_rid}  year={row['fiscal_year']}")
        print(f"is_last_fiscal : {is_last}"
              + (f"  (computed: project has {len(all_fiscals)} fiscal(s))" if args.last is None
                 else "  (forced)"))
        print(f"backup    : schema '{fiscal_flow.BACKUP_SCHEMA}' (per DB)")
        print("=" * 78)

        sections = fiscal_flow.load_sections()
        fr = fiscal_flow.run_one_fiscal(pool, sections, row, fiscal_flow.BACKUP_SCHEMA,
                                        dry_run, log=print, verbose=args.verbose)
        if fr["status"] != "ok" and not dry_run:
            pool.drop_all()
        txt, rep = PP.write_report(project_rid, ctx, [fr], dry_run)
        print("\n" + "=" * 78)
        print(f"{'DRY-RUN' if dry_run else 'DONE'} — status={fr['status']}, "
              f"~{rep['total_rows_deleted']:,} rows {'would be ' if dry_run else ''}deleted")
        if fr["error"]:
            print(f"ERROR: {fr['error']}")
        print(f"Report: {txt}")
        print("=" * 78)
    finally:
        pool.close_all()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted."); sys.exit(130)
