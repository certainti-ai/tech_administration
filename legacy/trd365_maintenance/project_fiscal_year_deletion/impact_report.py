#!/usr/bin/env python3
"""Consolidate a dry-run's JSON report into per-table impact tables.

Two kinds of impact are reported, both straight from GET DIAGNOSTICS ROW_COUNT:
  * DELETES   — "Backed up + deleted <table>: <n>" (delete sections 2/3/7,
                emitted in deletion order, children before parents).
  * UPDATES   — "Recomputed <target>: <n>" (rollup/aggregate rows that SURVIVE
                but have their totals recomputed to exclude the removed fiscal).

Usage:
    python impact_report.py                     # newest report in reports/
    python impact_report.py reports/<file>.json # a specific report
"""
import glob
import json
import os
import re
import sys

DB = {2: "ORG  (thinkrd365_org)", 3: "MAIN (thinkrd365_main)", 7: "TRD365AI (public)"}
DELETED = re.compile(r"Backed up \+ deleted (.+?):\s*(\d+)\s*$")
RECOMPUTED = re.compile(r"Recomputed (.+?):\s*(\d+)\s*$")
SKIP_RECOMP = re.compile(r"skip (.+recompute[^)]*\))", re.I)
TAG = re.compile(r"^\[[^]]*\]\s*")


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        reports = glob.glob(os.path.join(here, "reports", "*.json"))
        if not reports:
            sys.exit("No JSON reports found in reports/. Run a --dry-run first.")
        path = max(reports, key=os.path.getmtime)

    run = json.load(open(path))
    print()
    print("IMPACT ANALYSIS  (dry-run, rolled back)")
    print(f"report          : {os.path.basename(path)}")
    print(f"project_fiscal  : {run['project_fiscal_id']}")
    print(f"schema          : {run.get('schema_name')}   is_last_fiscal: {run.get('is_last_fiscal')}")
    print(f"backup_schema   : {run.get('backup_schema')}")

    # ── DELETES ──────────────────────────────────────────────────────────────
    print()
    print("DELETES — rows that WOULD be removed, in deletion order (children → parents)")
    print("=" * 84)
    print(f"{'#':>3}  {'table':<50}{'rows':>8}  note")
    print("-" * 84)
    del_grand = 0
    order = 0
    del_by_db = {}
    for num in (2, 3, 7):
        sec = next((s for s in run["sections"] if s["num"] == num), None)
        if not sec:
            continue
        print(f"── {DB[num]} " + "─" * max(0, 66 - len(DB[num])))
        db_total = 0
        for n in sec["notices"]:
            t = n.replace("NOTICE:", "").strip()
            m = DELETED.search(t)
            if m and "Recomputed" not in t:
                order += 1
                rows = int(m.group(2))
                del_grand += rows
                db_total += rows
                flag = "" if rows == 0 else "  <== has rows"
                print(f"{order:>3}  {TAG.sub('', m.group(1)):<50}{rows:>8}{flag}")
            elif "skip" in t and "not found" in t:
                print(f"     {TAG.sub('', t):<50}{'—':>8}  (table absent)")
            elif "Skipped parent" in t:
                print(f"     · {TAG.sub('', t)}")
        del_by_db[num] = db_total
    print("-" * 84)
    for num in (2, 3, 7):
        if num in del_by_db:
            print(f"{DB[num]:<53}{del_by_db[num]:>8}")
    print(f"{'TOTAL rows to be DELETED':<53}{del_grand:>8}")
    print("=" * 84)

    # ── UPDATES / RECOMPUTES ─────────────────────────────────────────────────
    print()
    print("UPDATES — surviving parent/aggregate rows whose rollup totals get recomputed")
    print("=" * 84)
    print(f"{'target (recomputed)':<58}{'rows':>8}  note")
    print("-" * 84)
    upd_grand = 0
    upd_by_db = {}
    for num in (2, 3, 7):
        sec = next((s for s in run["sections"] if s["num"] == num), None)
        if not sec:
            continue
        rows_here = []
        for n in sec["notices"]:
            t = n.replace("NOTICE:", "").strip()
            m = RECOMPUTED.search(t)
            if m:
                rows_here.append(("upd", TAG.sub("", m.group(1)), int(m.group(2))))
            else:
                sk = SKIP_RECOMP.search(t)
                if sk:
                    rows_here.append(("skip", TAG.sub("", t), None))
        if not rows_here:
            continue
        print(f"── {DB[num]} " + "─" * max(0, 66 - len(DB[num])))
        db_total = 0
        for kind, lbl, rows in rows_here:
            if kind == "upd":
                upd_grand += rows
                db_total += rows
                flag = "" if rows == 0 else "  <== rows updated"
                print(f"{lbl[:58]:<58}{rows:>8}{flag}")
            else:
                print(f"{lbl[:58]:<58}{'—':>8}  (skipped)")
        upd_by_db[num] = db_total
    print("-" * 84)
    for num in (2, 3, 7):
        if num in upd_by_db:
            print(f"{DB[num]:<58}{upd_by_db[num]:>8}")
    print(f"{'TOTAL rows to be UPDATED (recomputed)':<58}{upd_grand:>8}")
    print("=" * 84)
    print()
    print(f"SUMMARY: {del_grand} row(s) deleted, {upd_grand} surviving row(s) recomputed.")


if __name__ == "__main__":
    main()
