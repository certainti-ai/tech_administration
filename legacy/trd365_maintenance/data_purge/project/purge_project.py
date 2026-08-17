#!/usr/bin/env python3
"""
PROJECT purge sub-module — delete a whole project (all its fiscal years) across
ORG + MAIN + TRD365AI, WITH parent-aggregate recompute, backup, and audit.

A project deletion = delete each of the project's project-fiscals in turn, using
the vetted vendor SECTION 1–8 flow (delete + recompute), with is_last_fiscal=TRUE
on the FINAL fiscal so its run also removes the project-level rows and recomputes
the account-level aggregates. The recompute logic is reused verbatim from the
vendor SQL (base_sql/) rather than re-derived — that is what keeps financial
totals correct.

Five phases (per fiscal, via the vendor sections):
  1. ANALYSE  — SECTION 1/6 pre-counts (and the whole run in --dry-run).
  2. BACKUP   — into the shared `data_purge` schema (bak_org_/bak_main_/bak_ai_).
  3. DELETE   — SECTION 2/3/7 (children-first; fiscal row last; project row on the
                final fiscal).
  4. RECOMPUTE— account_fiscal / project / resource_fiscal / case_projects /
                project_summary / account totals (inside SECTION 2/3).
  5. AUDIT+REPORT — SECTION 4/5/8 post-delete diffs + a summary report.

Usage:
    python purge_project.py --account-id ACC-00459 --project-rid P001-…            # DRY RUN
    python purge_project.py --account-id ACC-00459 --project-rid P001-… --apply
    python purge_project.py --account-rid P001-… --project-code "Infosys FY25 Project 1" --apply
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from engine import db_pfy as db  # noqa: E402  (vendor pool w/ NoticeSink)
from project_fiscal import resolve, fiscal_flow  # noqa: E402

REPORTS_DIR = HERE / "reports"
DEFAULT_CONFIG = ROOT / "config" / "db_config.json"
_DEL_RE = re.compile(r"deleted\s+([a-z0-9_]+)\s*:\s*(\d+)", re.I)


def _now():
    return datetime.now(timezone.utc)


def _safe(s):
    return "".join(c if c.isalnum() else "_" for c in str(s))


def _fiscal_deleted(run):
    """Sum rows-deleted across a fiscal's section notices."""
    tot = 0
    per = {}
    for s in run["sections"]:
        for n in s["notices"]:
            m = _DEL_RE.search(n)
            if m:
                per[m.group(1)] = per.get(m.group(1), 0) + int(m.group(2))
                tot += int(m.group(2))
    return tot, per


def write_report(entity_rid, ctx, fiscal_runs, dry_run):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = _now().strftime("%Y%m%d_%H%M%S")
    base = REPORTS_DIR / f"project_{_safe(entity_rid)}_{ts}"
    grand = 0
    fiscals_out = []
    for fr in fiscal_runs:
        tot, per = _fiscal_deleted(fr)
        grand += tot
        fiscals_out.append({"project_fiscal_id": fr["project_fiscal_id"],
                            "fiscal_year": fr["fiscal_year"], "is_last_fiscal": fr["is_last_fiscal"],
                            "status": fr["status"], "error": fr["error"],
                            "rows_deleted": tot, "by_table": per,
                            "sections": [{"name": s["name"], "db": s["db_key"],
                                          "status": s["status"], "seconds": s["seconds"],
                                          "error": s.get("error")} for s in fr["sections"]]})
    rep = {"entity": "project", "entity_rid": entity_rid, "context": ctx,
           "mode": "dry-run" if dry_run else "apply",
           "backup_schema": fiscal_flow.BACKUP_SCHEMA,
           "fiscals": fiscals_out, "total_rows_deleted": grand,
           "generated_at": _now().isoformat()}
    with open(str(base) + ".json", "w") as fh:
        json.dump(rep, fh, indent=2, default=str)
    with open(str(base) + ".txt", "w") as fh:
        fh.write(_render(rep))
    return str(base) + ".txt", rep


def _render(r):
    L, W = [], 78
    L.append("=" * W)
    L.append(f"PROJECT PURGE REPORT — {r['entity_rid']}  ({r['mode'].upper()})")
    L.append("=" * W)
    for k, v in r["context"].items():
        L.append(f"{k:<16}: {v}")
    L.append(f"{'backup_schema':<16}: {r['backup_schema']}")
    L.append(f"{'fiscals':<16}: {len(r['fiscals'])}")
    L.append(f"{'rows deleted':<16}: {r['total_rows_deleted']:,}"
             + ("   (would delete — dry-run)" if r["mode"] == "dry-run" else ""))
    for f in r["fiscals"]:
        L.append("-" * W)
        L.append(f"FISCAL {f['project_fiscal_id']}  year={f['fiscal_year']}  "
                 f"last={f['is_last_fiscal']}  status={f['status']}  rows={f['rows_deleted']:,}")
        if f["error"]:
            L.append(f"  ERROR: {f['error']}")
        for s in f["sections"]:
            flag = "" if s["status"] == "ok" else f"  <<{s['status']}>>"
            L.append(f"    {s['name']:<44} {s['db']:<9} {s['seconds']:>6.1f}s{flag}")
        if f["by_table"]:
            top = sorted(f["by_table"].items(), key=lambda x: -x[1])[:12]
            L.append("    rows by table: " + ", ".join(f"{t}={n}" for t, n in top))
    L.append("=" * W)
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Delete a whole project (all fiscals) with recompute.")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--account-id", help="Account r_number (ACC-…) or account_rid.")
    ap.add_argument("--account-rid", help="Alias for --account-id (account_rid).")
    ap.add_argument("--project-rid", help="Project rid (P001-…/D001-…).")
    ap.add_argument("--project-code", help="Project code/name (resolved within the account schema).")
    ap.add_argument("--apply", action="store_true", help="Actually run (delete+recompute). Omit for DRY RUN.")
    ap.add_argument("--verbose", action="store_true", help="Stream every section NOTICE line.")
    args = ap.parse_args()
    dry_run = not args.apply
    account_ref = args.account_id or args.account_rid
    project_ref = args.project_rid or args.project_code
    if not account_ref or not project_ref:
        sys.exit("Provide --account-id (or --account-rid) AND --project-rid (or --project-code).")

    pool = db.ConnectionPool(db.load_config(args.config))
    try:
        acct = resolve.resolve_account(pool, account_ref)
        if not acct.get("exists"):
            sys.exit(f"Account not found: {account_ref}")
        project_rid = resolve.resolve_project(pool, acct["org_schema"], project_ref)
        if not project_rid:
            sys.exit(f"Project not found in {acct['org_schema']}: {project_ref}")
        fiscals = resolve.project_fiscals(pool, acct["org_schema"], project_rid)
        ctx = {"account_rid": acct["account_rid"], "r_number": acct["r_number"],
               "org_schema": acct["org_schema"], "project_rid": project_rid}

        print("=" * 78)
        print(f"PROJECT PURGE  ({'DRY-RUN' if dry_run else 'LIVE APPLY'})")
        print(f"account   : {acct['r_number']}  ({acct['account_rid']})")
        print(f"schema    : {acct['org_schema']}")
        print(f"project   : {project_rid}")
        print(f"fiscals   : {len(fiscals)}  ->  " +
              ", ".join(f"{f['fiscal_year']}" for f in fiscals) if fiscals else "(none)")
        print(f"backup    : schema '{fiscal_flow.BACKUP_SCHEMA}' (per DB)")
        print("=" * 78)
        if not fiscals:
            print("Project has no project_fiscal rows — nothing to delete."); return

        rows = resolve.build_fiscal_rows(acct, project_rid, fiscals)
        sections = fiscal_flow.load_sections()
        fiscal_runs = []
        for i, row in enumerate(rows, 1):
            print(f"\n{'#'*78}\n# FISCAL {i}/{len(rows)}: {row['project_fiscal_id']}  "
                  f"year={row['fiscal_year']}  is_last_fiscal={row['is_last_fiscal']}\n{'#'*78}")
            fr = fiscal_flow.run_one_fiscal(pool, sections, row, fiscal_flow.BACKUP_SCHEMA,
                                            dry_run, log=print, verbose=args.verbose)
            fiscal_runs.append(fr)
            tot, _ = _fiscal_deleted(fr)
            print(f"  -> fiscal {row['project_fiscal_id']}: status={fr['status']}, "
                  f"{'would delete' if dry_run else 'deleted'} ~{tot} rows")
            if fr["status"] != "ok":
                print(f"  !! STOPPING — fiscal failed: {fr['error']}")
                if not dry_run:
                    pool.drop_all()
                break

        txt, rep = write_report(project_rid, ctx, fiscal_runs, dry_run)
        print("\n" + "=" * 78)
        print(f"{'DRY-RUN' if dry_run else 'DONE'} — {len(fiscal_runs)} fiscal(s), "
              f"~{rep['total_rows_deleted']:,} rows {'would be ' if dry_run else ''}deleted")
        print(f"Report: {txt}")
        print("=" * 78)
    finally:
        pool.close_all()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. In live mode, committed sections persist; re-run to continue.")
        sys.exit(130)
