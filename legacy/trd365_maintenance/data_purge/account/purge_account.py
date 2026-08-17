#!/usr/bin/env python3
"""
ACCOUNT purge sub-module — delete every record belonging to one or more accounts
across all three databases, with backup, audit, and a summary report.

Five phases per account (see engine/core.py for the shared machinery):
    1. ANALYSE  — resolve the account, capture id-sets, count impacted rows per
                  table.  ``--dry-run`` stops here (read-only preview).
    2. BACKUP   — copy impacted rows into the shared ``data_purge`` schema of each
                  impacted DB (``data_purge.bak_<table>``), tagged with run id.
    3. DELETE   — chunked, committed, children-before-parents, FK-blocked tables
                  deferred + retried until the ordering constraints are met.
    4. AUDIT    — verify ONLY intended rows were removed (0 residual in scope,
                  backups == deletes, no collateral).
    5. REPORT   — write a JSON + text summary to reports/.

Backups accumulate in one ``data_purge`` schema per DB (created if absent), one
``bak_<table>`` per source table, rows distinguished by ``_purge_run_id`` /
``_purge_entity_rid`` so many accounts (and later, other entities) coexist safely.

Usage:
    python purge_account.py --account-rid P001-abc                 # DRY RUN (default)
    python purge_account.py --account-rid P001-abc --apply
    python purge_account.py --csv input/accounts.csv --apply
    python purge_account.py --account-rid P001-abc --apply --chunk-size 2000

Input CSV must have an ``account_rid`` column (a ``status`` column is honoured:
rows not "to be processed"/"failed" are skipped; status is written back).
"""

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from engine import db, core, report  # noqa: E402
from account import manifest as M, scoping  # noqa: E402

STATE_DIR = HERE / "state"
REPORTS_DIR = HERE / "reports"
DEFAULT_CONFIG = ROOT / "config" / "db_config.json"
PICKUP = {"", "to be processed", "failed"}


def _now():
    return datetime.now(timezone.utc)


def _iso():
    return _now().isoformat()


def _safe(s):
    return "".join(c if c.isalnum() else "_" for c in str(s))


import json  # noqa: E402


def _load_cp(rid):
    p = STATE_DIR / f"{_safe(rid)}.json"
    if p.exists():
        with open(p) as fh:
            return json.load(fh)
    return None


def _save_cp(cp, dry_run):
    if dry_run:
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_DIR / f"{_safe(cp['entity_rid'])}.json", "w") as fh:
        json.dump(cp, fh, indent=2, default=str)


def purge_one_account(pool, rid, chunk_size, dry_run, log=print):
    """Run the 5 phases for one account. Returns (run_dict, ok)."""
    acct = scoping.resolve_account(pool, rid)

    cp = _load_cp(rid)
    if not acct.get("exists"):
        # The account row itself is deleted late in the MAIN step (before AI). If
        # a prior run got that far then failed, resume the rest from checkpoint.
        if cp and cp.get("context", {}).get("org_schema") and cp.get("id_sets") is not None:
            ctx = cp["context"]
            acct = {"rid": rid, "exists": True, "r_number": ctx.get("r_number"),
                    "org_schema": ctx["org_schema"], "storage_type": ctx.get("storage_type"),
                    "parent_rid": None}
            log("  account record already deleted; resuming remaining phases from checkpoint")
        else:
            return {"entity": "account", "entity_rid": rid, "status": "not_found",
                    "run_id": "", "backup_schema": core.BACKUP_SCHEMA, "metrics": {},
                    "steps_meta": [], "context": {},
                    "note": "rid not in trd365.account (already deleted or wrong id)"}, True

    run_id = (cp or {}).get("run_id") or f"account_{_safe(rid)}_{_now().strftime('%Y%m%d_%H%M%S')}"
    cp = cp or {
        "entity": "account", "entity_rid": rid, "run_id": run_id,
        "backup_schema": core.BACKUP_SCHEMA, "run_at": _iso(), "started_at": _iso(),
        "context": {"r_number": acct.get("r_number"), "org_schema": acct.get("org_schema"),
                    "storage_type": acct.get("storage_type")},
        "id_sets": None, "completed_tables": {}, "metrics": {}, "status": "in_progress",
        "last_error": None,
    }
    cp["status"] = "in_progress"

    # ── PHASE 1: ANALYSE (capture id-sets) ────────────────────────────────────
    if cp.get("id_sets") is None:
        log("  [1/5] ANALYSE — capturing id-sets (cases/fiscals/projects/resources)…")
        cp["id_sets"] = scoping.capture_id_sets(pool, acct)
        _save_cp(cp, dry_run)
    sets = cp["id_sets"]
    cp["context"]["id_set_sizes"] = {k: len(v) for k, v in sets.items()}
    log("        fiscals=%d cases=%d projects=%d resources=%d interactions=%d" % (
        len(sets.get("project_fiscal", [])), len(sets.get("cases", [])),
        len(sets.get("project", [])), len(sets.get("resources", [])),
        len(sets.get("interactions", []))))

    scoper = scoping.AccountScoper(acct, sets)
    schema_for = {"org": acct["org_schema"], "main": M.MAIN_SCHEMA, "ai": M.AI_SCHEMA}
    tag = (cp["run_at"], run_id, "account", rid)

    # ── PHASES 2+3: BACKUP + DELETE (chunked, children-first, multi-pass) ──────
    log("  [2/5+3/5] %s — backup into %s + delete (children-first)…" % (
        "ANALYSE (dry-run: counts only)" if dry_run else "BACKUP + DELETE", core.BACKUP_SCHEMA))
    ok, err = core.run_steps(
        pool, M.STEPS, schema_for, scoper, tag, core.BACKUP_SCHEMA,
        chunk_size, dry_run, log, cp["metrics"], cp["completed_tables"],
        lambda: _save_cp(cp, dry_run))
    if not ok:
        cp["status"] = "failed"; cp["last_error"] = err
        _save_cp(cp, dry_run)

    # ── PHASE 4: AUDIT ────────────────────────────────────────────────────────
    findings, clean = ([], None)
    if ok:
        findings, clean = core.audit(pool, M.STEPS, schema_for, scoper, cp["metrics"], dry_run, log)
    cp["audit"] = {"findings": findings, "clean": clean}
    if ok:
        cp["status"] = "dry-run-complete" if dry_run else ("completed" if clean else "completed-with-audit-warnings")
    cp["finished_at"] = _iso()
    _save_cp(cp, dry_run)

    # build the run dict for the report (steps_meta gives db/schema labels)
    cp["steps_meta"] = [{"step": s, "db": d, "schema": schema_for[k]}
                        for (s, d, k, _t) in M.STEPS]
    return cp, ok


def read_csv(path):
    with open(path, newline="") as fh:
        r = csv.DictReader(fh)
        fields = list(r.fieldnames or [])
        rows = [dict(x) for x in r]
    if "account_rid" not in fields:
        sys.exit(f"Input CSV must have an 'account_rid' column. Found: {fields}")
    for extra in ("status", "processed_at", "note", "report"):
        if extra not in fields:
            fields.append(extra)
            for x in rows:
                x.setdefault(extra, "")
    return fields, rows


def write_csv(path, fields, rows):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for x in rows:
            w.writerow({k: x.get(k, "") for k in fields})
    Path(tmp).replace(path)


def main():
    ap = argparse.ArgumentParser(description="Account data-purge sub-module (backup + delete + audit).")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--account-rid", nargs="*", help="One or more account rids.")
    ap.add_argument("--csv", type=Path, help="Input CSV with an account_rid column.")
    ap.add_argument("--chunk-size", type=int, default=1000)
    ap.add_argument("--apply", action="store_true", help="Actually back up + delete. Omit for DRY RUN.")
    args = ap.parse_args()
    dry_run = not args.apply

    rids, csv_rows, fields = [], None, None
    if args.csv:
        if not args.csv.exists():
            sys.exit(f"Input CSV not found: {args.csv}")
        fields, csv_rows = read_csv(args.csv)
        want = set(args.account_rid or [])
        rids = [x["account_rid"].strip() for x in csv_rows
                if x.get("status", "").strip().lower() in PICKUP
                and (not want or x["account_rid"].strip() in want)]
    elif args.account_rid:
        rids = [r.strip() for r in args.account_rid]
    else:
        sys.exit("Provide --account-rid <rid...> or --csv <file>.")
    if not rids:
        print("Nothing to process."); return

    print("=" * 78)
    print(f"ACCOUNT DATA PURGE  ({'DRY-RUN' if dry_run else 'LIVE APPLY'})")
    print(f"accounts   : {len(rids)}")
    print(f"chunk size : {args.chunk_size}")
    print(f"backup     : schema '{core.BACKUP_SCHEMA}' (per DB)")
    print("=" * 78)

    pool = db.ConnectionPool(db.load_config(args.config))
    processed = failed = notfound = 0
    try:
        for rid in rids:
            print("\n" + "#" * 78)
            print(f"# ACCOUNT: {rid}")
            print("#" * 78)
            row = next((x for x in (csv_rows or []) if x["account_rid"].strip() == rid), None)
            try:
                run, ok = purge_one_account(pool, rid, args.chunk_size, dry_run)
                if run.get("status") == "not_found":
                    notfound += 1
                    print(f"  NOT FOUND — {run.get('note')}")
                    if row is not None:
                        row.update(status="Not Found", processed_at=_iso(), note=run.get("note", ""))
                    continue
                txt, js = report.write_report(REPORTS_DIR, run)
                rep = report.summarize(run)
                tot = rep["totals"]
                if row is not None:
                    row["report"] = Path(txt).name
                if dry_run:
                    print(f"  [5/5] DRY-RUN analysis complete — {tot['rows_in_scope']:,} rows in scope "
                          f"across {tot['tables_with_rows']} tables. Report: {txt}")
                elif ok:
                    status = "Processed" if rep["audit_clean"] else "Processed (audit warnings)"
                    note = f"deleted {tot['rows_deleted']:,} rows across {tot['tables_with_rows']} tables"
                    if not rep["audit_clean"]:
                        note += f"; {len(rep['audit_findings'])} audit finding(s)"
                    if tot["unscoped"]:
                        note += f"; {tot['unscoped']} UNSCOPED table(s)"
                    processed += 1
                    if row is not None:
                        row.update(status=status, processed_at=_iso(), note=note)
                    print(f"  [5/5] {status}. {note}. Report: {txt}")
                else:
                    failed += 1
                    if row is not None:
                        row.update(status="Failed", processed_at=_iso(),
                                   note=(run.get("last_error") or "failed")[:300])
                    pool.drop_all()
                    print(f"  FAILED: {run.get('last_error')}")
            except Exception as exc:
                failed += 1
                if row is not None:
                    row.update(status="Failed", processed_at=_iso(),
                               note=f"{type(exc).__name__}: {str(exc).strip()[:280]}")
                pool.drop_all()
                print(f"  ERROR (marked Failed, continuing): {type(exc).__name__}: {str(exc).strip()[:200]}")
            finally:
                if csv_rows and not dry_run:
                    write_csv(args.csv, fields, csv_rows)
    finally:
        pool.close_all()

    print("\n" + "=" * 78)
    print(f"DONE — processed={processed}  failed={failed}  not_found={notfound}")
    print(f"Reports: {REPORTS_DIR}")
    print("=" * 78)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Committed chunks are persisted; re-run to resume.")
        sys.exit(130)
