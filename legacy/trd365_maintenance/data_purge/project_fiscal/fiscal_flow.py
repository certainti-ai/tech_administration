"""
Run the vendor SECTION 1–8 flow for ONE project-fiscal.

This is the atomic delete+recompute unit shared by the project_fiscal sub-module
(one fiscal) and the project sub-module (iterate a project's fiscals). It reuses
the vetted vendor SQL in base_sql/ verbatim — parameterised per fiscal — rather
than re-deriving the financial recompute, which is exactly what makes it safe.

Phase mapping (per fiscal):
  * SECTION 1 (ORG) / 6 (AI)   → ANALYSE: pre-delete snapshot + counts
  * SECTION 2 (ORG) / 3 (MAIN) / 7 (AI) → BACKUP + DELETE + RECOMPUTE
  * SECTION 4 (ORG) / 5 (MAIN) / 8 (AI) → AUDIT: post-delete diff (verify)
Backups land in the shared `data_purge` schema (bak_org_/bak_main_/bak_ai_<table>),
tagged with _backup_project_fiscal_id / _backup_run_at.
"""

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from engine import section_runner as R  # noqa: E402

BASE_SQL = HERE / "base_sql"
BACKUP_SCHEMA = "data_purge"   # unified framework backup schema (shared per DB)


def load_sections(only_nums=None):
    secs = R.discover_sections(BASE_SQL)
    if only_nums:
        secs = [s for s in secs if s["num"] in set(only_nums)]
    return secs


def run_one_fiscal(pool, sections, row, backup_schema, dry_run, log=print,
                   verbose=False, hb_interval=15):
    """Run the given sections for one fiscal `row`. Commits per section in live
    mode; in dry-run leaves txns open and rolls back all used DBs at the end.
    Returns a run dict with per-section metrics/notices."""
    run = {"project_fiscal_id": row["project_fiscal_id"], "schema_name": row["schema_name"],
           "project_rid": row["project_rid"], "fiscal_year": row.get("fiscal_year"),
           "is_last_fiscal": R.to_bool(row.get("is_last_fiscal")),
           "backup_schema": backup_schema, "sections": [], "status": "ok", "error": None}
    used_dbs = []
    try:
        for section in sections:
            srec = {"num": section["num"], "name": section["name"],
                    "db_key": section["db_key"], "status": "pending", "seconds": 0.0,
                    "rows": None, "notices": []}
            run["sections"].append(srec)
            if section["db_key"] not in used_dbs:
                used_dbs.append(section["db_key"])
            try:
                sql, _applied = R.prepare_sql(section, row, backup_schema)
            except R.RunnerError as exc:
                srec["status"] = "error"; srec["error"] = str(exc)
                run["status"] = "error"; run["error"] = str(exc)
                break
            t0 = time.time()

            def hb(elapsed, last):
                log(f"      … {section['name']} running {elapsed}s"
                    + (f" — {last}" if (verbose and last) else ""))

            try:
                notices = R.run_section(pool, section, sql, dry_run,
                                        heartbeat=hb, interval=hb_interval)
            except Exception as exc:
                srec["status"] = "error"; srec["error"] = str(exc)[:300]
                srec["seconds"] = round(time.time() - t0, 2)
                run["status"] = "error"; run["error"] = f"{section['name']}: {str(exc).strip()[:280]}"
                break
            srec["seconds"] = round(time.time() - t0, 2)
            srec["status"] = "ok"
            srec["notices"] = [str(n).rstrip() for n in notices]
            if verbose:
                for n in srec["notices"]:
                    log(f"      {n}")
            else:
                # surface the key summary NOTICE lines only
                for n in srec["notices"]:
                    if "deleted" in n.lower() or "recompute" in n.lower() or "SECTION" in n:
                        log(f"      {n}")
    finally:
        if dry_run:
            # discard everything this fiscal did (backup schema + deletes + recompute)
            for dbk in used_dbs:
                try:
                    pool.get(dbk).rollback()
                except Exception:
                    pass
    return run
