#!/usr/bin/env python3
"""
Account deletion runner (new chunked/resumable approach).

Reads an input CSV of account ids with a status column, processes every account
marked "To be Processed" through all deletion steps (org -> main -> trd365ai),
deleting in small committed chunks, backing up first, then updates the status to
"Processed" (or "Failed") and writes a detailed metrics report per account.

Usage:
    python run.py                         # process all "To be Processed" rows
    python run.py --dry-run               # read-only: counts + unscoped check, no deletes
    python run.py --input input/accounts.csv --chunk-size 1000
    python run.py --accounts P001-abc P001-def   # only these rids (still must be in CSV)
    python run.py --full-counts           # also record whole-table row counts (slower)

Status values in the CSV:
    "To be Processed"  -> will be processed
    "Processed"        -> set on success (skipped on future runs)
    "Failed"           -> set on error (re-run resumes from the failed table)
    "Not Found"        -> account rid not in trd365.account (already deleted / wrong id)
"""

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine import db, engine, report  # noqa: E402

# Rows in these statuses are picked up. "failed" is included so a re-run resumes
# a previously-failed account from its checkpoint (deleting only what remains).
PICKUP_STATUSES = {"to be processed", "failed"}
DEFAULT_INPUT = HERE / "input" / "accounts.csv"
DEFAULT_CONFIG = HERE / "config" / "db_config.json"
STATE_DIR = HERE / "state"
REPORTS_DIR = HERE / "reports"


def read_csv(path):
    with open(path, newline="") as fh:
        r = csv.DictReader(fh)
        fields = list(r.fieldnames or [])
        rows = [dict(x) for x in r]
    if "account_rid" not in fields:
        sys.exit(f"Input CSV must have an 'account_rid' column. Found: {fields}")
    if "status" not in fields:
        fields.append("status")
        for x in rows:
            x.setdefault("status", "")
    for extra in ("processed_at", "note", "report"):
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


def _now():
    return datetime.now(timezone.utc).isoformat()


def main():
    ap = argparse.ArgumentParser(description="Chunked/resumable account deletion runner.")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--chunk-size", type=int, default=1000)
    ap.add_argument("--dry-run", action="store_true",
                    help="Read-only: counts + unscoped-table check, no backups/deletes.")
    ap.add_argument("--full-counts", action="store_true",
                    help="Also record whole-table row counts (slower on big shared tables).")
    ap.add_argument("--accounts", nargs="*", help="Limit to these account rids.")
    args = ap.parse_args()

    if not args.input.exists():
        sys.exit(f"Input CSV not found: {args.input}")

    fields, rows = read_csv(args.input)
    targets = [x for x in rows
               if x.get("status", "").strip().lower() in PICKUP_STATUSES
               and (not args.accounts or x["account_rid"].strip() in set(args.accounts))]
    if not targets:
        print("No rows with status 'To be Processed' or 'Failed' (matching filter). Nothing to do.")
        return

    print("=" * 78)
    print(f"Account Deletion Runner ({'DRY-RUN' if args.dry_run else 'LIVE'})")
    print(f"input      : {args.input}")
    print(f"accounts   : {len(targets)} to process")
    print(f"chunk size : {args.chunk_size}")
    print("=" * 78)

    pool = db.ConnectionPool(db.load_config(args.config))
    processed = failed = notfound = 0
    try:
        for row in targets:
            rid = row["account_rid"].strip()
            print("\n" + "#" * 78)
            print(f"# ACCOUNT: {rid}")
            print("#" * 78)
            try:
                acct = engine.resolve_account(pool, rid)
                if not acct.get("exists"):
                    # The account record itself is deleted late in the main step,
                    # BEFORE the ai step. If a prior run got that far and then
                    # failed, the account is gone but ai data may remain — resume
                    # the remaining steps from the checkpoint instead of skipping.
                    cp0 = engine.load_checkpoint(STATE_DIR, rid)
                    if cp0 and cp0.get("org_schema") and cp0.get("id_sets") is not None:
                        acct = {"rid": rid, "exists": True,
                                "r_number": cp0.get("r_number"),
                                "org_schema": cp0["org_schema"],
                                "storage_type": cp0.get("storage_type"),
                                "parent_rid": None}
                        print("  account record already deleted; resuming remaining "
                              "steps from checkpoint")
                    else:
                        row["status"] = "Not Found"
                        row["note"] = "rid not in trd365.account (already deleted or wrong id)"
                        row["processed_at"] = _now()
                        notfound += 1
                        if not args.dry_run:
                            write_csv(args.input, fields, rows)
                        print(f"  NOT FOUND — {row['note']}")
                        continue
                print(f"  r_number={acct['r_number']}  org_schema={acct['org_schema']}  "
                      f"storage_type={acct['storage_type']}")

                cp, ok = engine.process_account(
                    pool, acct, STATE_DIR, chunk_size=args.chunk_size,
                    dry_run=args.dry_run, full_counts=args.full_counts, log=print)

                txt, js = report.write_report(REPORTS_DIR, cp)
                summary = report.summarize(cp)
                tot = summary["totals"]
                row["report"] = Path(txt).name
                if args.dry_run:
                    print(f"  DRY-RUN complete. Report: {txt}")
                elif ok:
                    row["status"] = "Processed"
                    row["processed_at"] = _now()
                    note = f"deleted {tot['rows_deleted']} rows across {tot['tables_with_rows']} tables"
                    if tot["unscoped"]:
                        note += f"; {tot['unscoped']} UNSCOPED table(s) — see report"
                    row["note"] = note
                    processed += 1
                    print(f"  PROCESSED. Report: {txt}")
                else:
                    row["status"] = "Failed"
                    row["processed_at"] = _now()
                    row["note"] = cp.get("last_error", "failed")[:300]
                    failed += 1
                    pool.drop_all()  # in case the failure was connection-related
                    print(f"  FAILED: {row['note']}")
            except Exception as exc:
                # Never let one account (e.g. a dropped tunnel) crash the batch.
                # Mark it Failed, reset connections, and move on — a later re-run
                # resumes it from its checkpoint.
                row["status"] = "Failed"
                row["processed_at"] = _now()
                row["note"] = f"{type(exc).__name__}: {str(exc).strip()[:280]}"
                failed += 1
                pool.drop_all()
                print(f"  ERROR (account marked Failed, continuing): {row['note']}")
            if not args.dry_run:
                write_csv(args.input, fields, rows)
    finally:
        pool.close_all()

    print("\n" + "=" * 78)
    print(f"DONE — processed={processed}  failed={failed}  not_found={notfound}")
    print(f"Reports: {REPORTS_DIR}")
    print(f"State  : {STATE_DIR}")
    print("=" * 78)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Committed chunks are persisted; re-run to resume.")
        sys.exit(130)
