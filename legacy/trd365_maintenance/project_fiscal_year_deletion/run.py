#!/usr/bin/env python3
"""Project fiscal-year deletion runner.

Reads an input CSV of projects (one project-fiscal per row, with a status
column) and, for every row marked "To be Processed", runs the base_sql section
scripts (SECTION 1 → 8) in order against the right database, substituting the
row's values into each script's FILL-IN variables and hand-carrying SECTION 1's
announced backup-schema name into the later sections. It then sets the row's
status to "Processed" (or "Failed") and writes a per-project report.

Usage:
    python run.py                       # process all "To be Processed" rows
    python run.py --dry-run             # run every section but roll back — nothing persists
    python run.py --input input/projects.csv
    python run.py --projects D001-abc D001-def   # only these project_fiscal_ids (must be in CSV)
    python run.py --sections 1 2 3      # run only these section numbers (advanced/debug)
    python run.py --verbose             # also stream each section's NOTICE output to the console

Status values in the CSV:
    "To be Processed"  -> will be processed
    "Processed"        -> set on success (skipped on future runs)
    "Failed"           -> set on error (re-runs from SECTION 1 with a fresh backup schema)

DRY-RUN details: each SECTION is a single DO block whose COMMIT/ROLLBACK is
controlled here. In dry-run we reuse one connection per database and never
commit, so later same-DB sections still see the earlier (uncommitted) backup
schema; at the end of each project every connection is rolled back, discarding
all backups and deletes.
"""

import argparse
import csv
import itertools
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine import db, report, runner  # noqa: E402

# Postgres SQLSTATEs raised when concurrent workers race on CREATE ... IF NOT
# EXISTS for the shared backup schema/tables. IF NOT EXISTS is not race-free, so
# the loser can still get one of these — safe to retry the whole project.
DDL_RACE_CODES = {"42P06", "42P07", "42710", "23505"}  # dup schema/table/object, unique_violation

PICKUP_STATUSES = {"to be processed", "failed"}
DEFAULT_INPUT = HERE / "input" / "projects.csv"
DEFAULT_CONFIG = HERE / "config" / "db_config.json"
DEFAULT_BASE_SQL = HERE / "base_sql"
REPORTS_DIR = HERE / "reports"

# Columns the runner reads/writes. Extra columns in the file are preserved.
INPUT_FIELDS = ["schema_name", "account_rid", "project_rid", "project_fiscal_id",
                "fiscal_year", "is_last_fiscal"]
STATUS_FIELDS = ["status", "processed_at", "note", "backup_schema", "report"]


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        r = csv.DictReader(fh)
        fields = list(r.fieldnames or [])
        rows = [dict(x) for x in r]
    if "project_fiscal_id" not in fields:
        sys.exit(f"Input CSV must have a 'project_fiscal_id' column. Found: {fields}")
    for extra in STATUS_FIELDS:
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


def process_project(pool, sections, row, backup_schema, dry_run, verbose, log,
                    hb_interval=15):
    """Run every selected section for one project. Returns the run dict.

    `backup_schema` is the single execution-wide backup schema name — the same
    value for every project in this run, forced into all 8 sections.
    `hb_interval` is the seconds between "still running…" heartbeats (0 = off)."""
    now = datetime.now(timezone.utc)
    run = {
        "dry_run": dry_run,
        "started_at": now.isoformat(),
        "started_at_stamp": now.strftime("%Y%m%d_%H%M%S"),
        "project_fiscal_id": row["project_fiscal_id"].strip(),
        "schema_name": row.get("schema_name", "").strip(),
        "account_rid": row.get("account_rid", "").strip(),
        "project_rid": row.get("project_rid", "").strip(),
        "is_last_fiscal": runner.to_bool(row.get("is_last_fiscal")),
        "backup_schema": backup_schema,
        "sections": [],
        "status": "Processed",
        "error": None,
        "error_code": None,
    }

    for section in sections:
        srec = {"num": section["num"], "name": section["name"],
                "db_key": section["db_key"], "status": "pending",
                "seconds": 0.0, "notices": []}
        run["sections"].append(srec)
        start_clock = datetime.now(timezone.utc).strftime("%H:%M:%S")
        log(f"\n  ── SECTION {section['num']} [{section['db_key']}] {section['name']}"
            f"  (started {start_clock} UTC)")

        def heartbeat(elapsed, last, _num=section["num"], _db=section["db_key"]):
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            tail = f"  | {last[:110]}" if last else ""
            log(f"     [{ts}] SECTION {_num} [{_db}] still running… {elapsed}s{tail}")

        try:
            sql, applied = runner.prepare_sql(section, row, run["backup_schema"])
            t0 = time.time()
            notices = runner.run_section(pool, section, sql, dry_run,
                                         heartbeat=(heartbeat if hb_interval > 0 else None),
                                         interval=hb_interval)
            srec["seconds"] = round(time.time() - t0, 2)
            srec["notices"] = notices
            srec["status"] = "ok"

            if section["num"] == 1:
                announced = runner.parse_backup_schema(notices)
                log(f"     backup schema = {run['backup_schema']}")
                if announced and announced != run["backup_schema"]:
                    # SECTION 1 should echo the name we injected; a mismatch means
                    # the override didn't take — stop before later sections write
                    # into the wrong schema.
                    raise runner.RunnerError(
                        f"SECTION 1 announced backup schema '{announced}' but the "
                        f"runner injected '{run['backup_schema']}' — override failed.")

            if verbose:
                for n in notices:
                    log(f"       {n}")
            log(f"     done in {srec['seconds']}s"
                + ("  (dry-run: uncommitted)" if dry_run else "  (committed)"))
        except Exception as exc:
            srec["status"] = "failed"
            run["status"] = "Failed"
            run["error"] = f"SECTION {section['num']}: {type(exc).__name__}: {str(exc).strip()[:400]}"
            run["error_code"] = getattr(exc, "pgcode", None)
            # The failed DO block aborted its transaction; roll every connection
            # back so a later re-run (and, in a batch, the next project) is clean.
            pool.rollback_all()
            log(f"     FAILED: {run['error']}")
            break

    run["finished_at"] = _now()
    if dry_run:
        # Discard everything this project did — dry-run never persists.
        pool.rollback_all()
    return run


def _failed_run(row, backup_schema, dry_run, exc):
    """Minimal run dict when process_project itself blows up (e.g. dropped tunnel)."""
    return {
        "dry_run": dry_run,
        "started_at_stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        "project_fiscal_id": row["project_fiscal_id"].strip(),
        "backup_schema": backup_schema, "sections": [], "status": "Failed",
        "error": f"{type(exc).__name__}: {str(exc).strip()[:300]}",
        "error_code": getattr(exc, "pgcode", None),
    }


def _finalize(run, row, args, fields, rows, counters, lock, total):
    """Write the report, update the row's status and (live only) persist the CSV.
    Thread-safe: CSV writes and shared counters are guarded by `lock`."""
    txt, _ = report.write_report(REPORTS_DIR, run)
    with lock:
        row["report"] = Path(txt).name
        if run.get("backup_schema"):
            row["backup_schema"] = run["backup_schema"]
        counters["done"] += 1
        ok = run["status"] == "Processed"
        counters["processed" if ok else "failed"] += 1
        if not args.dry_run:  # dry-run never changes the input CSV
            row["processed_at"] = _now()
            if ok:
                row["status"] = "Processed"
                row["note"] = (f"deleted across {len(run.get('sections', []))} sections; "
                               f"backup={run.get('backup_schema')}")
            else:
                row["status"] = "Failed"
                row["note"] = (run.get("error") or "failed")[:300]
            write_csv(args.input, fields, rows)
        d, p, f = counters["done"], counters["processed"], counters["failed"]
    print(f"[done {d}/{total}] {run['project_fiscal_id']}  {run['status']}"
          + (f"  — {run.get('error')}" if not ok else "")
          + f"   (ok={p} failed={f})")
    return txt


def _run_concurrent(args, sections, targets, fields, rows, exec_backup_schema):
    """Process projects across N worker threads, each with its own ConnectionPool.

    LIVE uses the one shared backup schema (serialize the first project to create
    it + core bak_ tables, then fan out). DRY-RUN gives each worker its OWN
    throwaway schema so uncommitted-DDL locks don't serialize the workers."""
    config = db.load_config(args.config)
    lock = threading.Lock()
    counters = {"done": 0, "processed": 0, "failed": 0}
    total = len(targets)
    local = threading.local()
    pools = []
    widx = itertools.count()

    def get_pool():
        p = getattr(local, "pool", None)
        if p is None:
            with lock:
                local.widx = next(widx)
                p = db.ConnectionPool(config)
                pools.append(p)
            local.pool = p
        return p

    def schema_for_worker():
        if not args.dry_run:
            return exec_backup_schema  # shared, persisted
        return f"{exec_backup_schema[:40]}_dw{getattr(local, 'widx', 0)}"  # throwaway per worker

    def work(row):
        attempts = 0
        while True:
            attempts += 1
            pool = get_pool()
            bs = schema_for_worker()
            try:
                run = process_project(pool, sections, row, bs, args.dry_run,
                                      False, lambda *a: None, hb_interval=0)
            except Exception as exc:
                pool.drop_all()
                run = _failed_run(row, bs, args.dry_run, exc)
            if (run["status"] == "Failed" and run.get("error_code") in DDL_RACE_CODES
                    and attempts < 4):
                pool.drop_all()               # concurrent CREATE race — retry the whole project
                time.sleep(0.3 * attempts)
                continue
            return run

    try:
        # LIVE: create the shared schema + core bak_ tables via the first project
        # before fanning out, so the workers mostly hit IF-NOT-EXISTS no-ops.
        rest = targets
        if not args.dry_run and targets:
            print(f"[setup] first project serially to create backup schema {exec_backup_schema} …")
            _finalize(work(targets[0]), targets[0], args, fields, rows, counters, lock, total)
            rest = targets[1:]

        if rest:
            with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
                futs = {ex.submit(work, r): r for r in rest}
                for fut in as_completed(futs):
                    r = futs[fut]
                    try:
                        run = fut.result()
                    except Exception as exc:
                        run = _failed_run(r, exec_backup_schema, args.dry_run, exc)
                    _finalize(run, r, args, fields, rows, counters, lock, total)
    finally:
        for p in pools:
            p.close_all()
    return counters


def main():
    ap = argparse.ArgumentParser(description="Project fiscal-year deletion runner.")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--base-sql", type=Path, default=DEFAULT_BASE_SQL)
    ap.add_argument("--dry-run", action="store_true",
                    help="Run every section but roll back — nothing is committed.")
    ap.add_argument("--backup-schema", default=None,
                    help="Backup schema name for this whole execution (all projects "
                         "back up into it). Default: backup_release_v5_3_3_run_<ts>.")
    ap.add_argument("--projects", nargs="*",
                    help="Limit to these project_fiscal_ids (still must be in the CSV).")
    ap.add_argument("--sections", nargs="*", type=int,
                    help="Run only these section numbers (advanced/debug; may break "
                         "the backup-schema hand-off if SECTION 1 is skipped).")
    ap.add_argument("--verbose", action="store_true",
                    help="Stream each section's NOTICE output to the console.")
    ap.add_argument("--heartbeat", type=int, default=15, metavar="SECONDS",
                    help="Seconds between 'still running…' progress ticks while a "
                         "section runs (0 to disable). Default 15.")
    ap.add_argument("--concurrency", type=int, default=1, metavar="N",
                    help="Process N projects in parallel, each with its own DB "
                         "connections. Default 1 (serial). Try 4-8 for large batches.")
    ap.add_argument("--limit", type=int, default=None, metavar="N",
                    help="Process at most the first N matching projects (for measured "
                         "test runs / staged rollouts).")
    args = ap.parse_args()
    if args.concurrency < 1:
        args.concurrency = 1

    if not args.input.exists():
        sys.exit(f"Input CSV not found: {args.input}")

    sections = runner.discover_sections(args.base_sql)
    if args.sections:
        wanted = set(args.sections)
        sections = [s for s in sections if s["num"] in wanted]
        if not sections:
            sys.exit(f"No sections match --sections {sorted(wanted)}")

    fields, rows = read_csv(args.input)
    targets = [x for x in rows
               if x.get("status", "").strip().lower() in PICKUP_STATUSES
               and (not args.projects or x["project_fiscal_id"].strip() in set(args.projects))]
    if not targets:
        print("No rows with status 'To be Processed' or 'Failed' (matching filter). Nothing to do.")
        return
    if args.limit is not None and args.limit >= 0:
        targets = targets[:args.limit]
        if not targets:
            print("--limit 0 — nothing to do.")
            return

    # One backup schema for the whole execution — every project backs up into it.
    exec_backup_schema = args.backup_schema or (
        "backup_release_v5_3_3_run_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))

    print("=" * 78)
    print(f"Fiscal-Year Deletion Runner ({'DRY-RUN' if args.dry_run else 'LIVE'})")
    print(f"input        : {args.input}")
    print(f"projects     : {len(targets)} to process")
    print(f"sections     : {', '.join(str(s['num']) for s in sections)}")
    print(f"backup schema: {exec_backup_schema}"
          + ("  (shared by all projects this run)" if args.concurrency == 1 or not args.dry_run
             else "  (per-worker throwaway schemas in dry-run)"))
    print(f"concurrency  : {args.concurrency} worker(s)")
    print("=" * 78)

    processed = failed = 0
    total = len(targets)

    # ── Concurrent path ──────────────────────────────────────────────────────
    if args.concurrency > 1:
        counters = _run_concurrent(args, sections, targets, fields, rows, exec_backup_schema)
        processed, failed = counters["processed"], counters["failed"]
        print("\n" + "=" * 78)
        print(f"DONE — processed={processed}  failed={failed}"
              + ("  (dry-run: no status changes)" if args.dry_run else ""))
        print(f"Reports: {REPORTS_DIR}")
        print("=" * 78)
        return

    # ── Serial path (concurrency == 1) ───────────────────────────────────────
    pool = db.ConnectionPool(db.load_config(args.config))
    batch_t0 = time.time()
    try:
        for idx, row in enumerate(targets, 1):
            rid = row["project_fiscal_id"].strip()
            print("\n" + "#" * 78)
            print(f"# PROJECT {idx}/{total}  FISCAL: {rid}  "
                  f"(schema={row.get('schema_name','').strip()})")
            print(f"# elapsed {int(time.time() - batch_t0)}s into batch  |  "
                  f"processed={processed} failed={failed} remaining={total - idx + 1}")
            print("#" * 78)
            try:
                run = process_project(pool, sections, row, exec_backup_schema,
                                       args.dry_run, args.verbose, print,
                                       hb_interval=args.heartbeat)
            except Exception as exc:
                # Never let one project crash the batch (e.g. a dropped tunnel).
                pool.drop_all()
                row["status"] = "Failed"
                row["processed_at"] = _now()
                row["note"] = f"{type(exc).__name__}: {str(exc).strip()[:280]}"
                failed += 1
                print(f"  ERROR (project marked Failed, continuing): {row['note']}")
                if not args.dry_run:
                    write_csv(args.input, fields, rows)
                continue

            txt, js = report.write_report(REPORTS_DIR, run)
            row["report"] = Path(txt).name
            if run.get("backup_schema"):
                row["backup_schema"] = run["backup_schema"]

            if args.dry_run:
                print(f"  DRY-RUN complete ({run['status']}). Report: {txt}")
                # Dry-run does not change the CSV status.
            elif run["status"] == "Processed":
                row["status"] = "Processed"
                row["processed_at"] = _now()
                row["note"] = f"deleted across {len(run['sections'])} sections; backup={run['backup_schema']}"
                processed += 1
                print(f"  PROCESSED. Report: {txt}")
                write_csv(args.input, fields, rows)
            else:
                row["status"] = "Failed"
                row["processed_at"] = _now()
                row["note"] = (run.get("error") or "failed")[:300]
                failed += 1
                pool.drop_all()  # reset connections in case the failure was connection-related
                print(f"  FAILED: {row['note']}  Report: {txt}")
                write_csv(args.input, fields, rows)
    finally:
        pool.close_all()

    print("\n" + "=" * 78)
    print(f"DONE — processed={processed}  failed={failed}"
          + ("  (dry-run: no status changes)" if args.dry_run else ""))
    print(f"Reports: {REPORTS_DIR}")
    print("=" * 78)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
