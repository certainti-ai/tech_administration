"""Status report generation from an account checkpoint."""

import json
from datetime import datetime, timezone
from pathlib import Path


def _safe(rid):
    return "".join(c if c.isalnum() else "_" for c in rid)


def summarize(cp):
    """Roll checkpoint metrics up into a report dict with many metrics."""
    steps = []
    grand = {"tables_processed": 0, "tables_with_rows": 0, "rows_in_scope": 0,
             "rows_deleted": 0, "rows_backed_up": 0, "batches": 0, "unscoped": 0,
             "skipped": 0, "residual_nonzero": 0, "seconds": 0.0}
    per_table_rows = []    # (deleted, step, table)
    per_table_scope = []   # (scope_before, step, table) — useful for dry-run
    per_table_time = []

    for step_key, _db, _kind, _tables in _STEP_ORDER(cp):
        tm = cp["metrics"].get(step_key, {})
        step_secs = tm.get("_step_seconds", 0.0)
        rows = {"step": step_key, "step_seconds": step_secs,
                "tables": 0, "rows_in_scope": 0, "rows_deleted": 0,
                "rows_backed_up": 0, "batches": 0, "unscoped": [], "residual": []}
        for table, m in tm.items():
            if table == "_step_seconds":
                continue
            rows["tables"] += 1
            grand["tables_processed"] += 1
            sb = m.get("scope_before", 0)
            rows["rows_in_scope"] += sb
            grand["rows_in_scope"] += sb
            per_table_scope.append((sb, step_key, table))
            d = m.get("deleted", 0)
            rows["rows_deleted"] += d
            rows["rows_backed_up"] += m.get("backed_up", 0)
            rows["batches"] += m.get("batches", 0)
            grand["rows_deleted"] += d
            grand["rows_backed_up"] += m.get("backed_up", 0)
            grand["batches"] += m.get("batches", 0)
            grand["seconds"] += m.get("seconds", 0.0)
            if m.get("scope_before", 0) > 0 or d > 0:
                grand["tables_with_rows"] += 1
            if m.get("status") == "unscoped":
                grand["unscoped"] += 1
                rows["unscoped"].append(table)
            if m.get("status") == "skipped":
                grand["skipped"] += 1
            if m.get("scope_after", 0) > 0:
                grand["residual_nonzero"] += 1
                rows["residual"].append({"table": table, "remaining": m["scope_after"]})
            per_table_rows.append((d, step_key, table))
            per_table_time.append((m.get("seconds", 0.0), step_key, table))
        steps.append(rows)

    per_table_rows.sort(reverse=True)
    per_table_scope.sort(reverse=True)
    per_table_time.sort(reverse=True)
    return {
        "account_rid": cp["account_rid"],
        "r_number": cp.get("r_number"),
        "org_schema": cp.get("org_schema"),
        "storage_type": cp.get("storage_type"),
        "backup_schema": cp.get("backup_schema"),
        "status": cp.get("status"),
        "started_at": cp.get("started_at"),
        "finished_at": cp.get("finished_at"),
        "last_error": cp.get("last_error"),
        "id_set_sizes": {k: len(v) for k, v in (cp.get("id_sets") or {}).items()},
        "totals": grand,
        "steps": steps,
        "top_tables_by_rows": [{"table": t, "step": s, "deleted": d}
                               for d, s, t in per_table_rows[:15] if d > 0],
        "top_tables_by_scope": [{"table": t, "step": s, "in_scope": sb}
                                for sb, s, t in per_table_scope[:20] if sb > 0],
        "slowest_tables": [{"table": t, "step": s, "seconds": round(sec, 3)}
                           for sec, s, t in per_table_time[:15] if sec > 0],
    }


def _STEP_ORDER(cp):
    from . import deletion_manifest as M
    return M.STEPS


def write_report(reports_dir, cp):
    rep = summarize(cp)
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = Path(reports_dir) / f"{_safe(cp['account_rid'])}_{ts}"
    with open(str(base) + ".json", "w") as fh:
        json.dump(rep, fh, indent=2, default=str)
    with open(str(base) + ".txt", "w") as fh:
        fh.write(_render_text(rep))
    return str(base) + ".txt", str(base) + ".json"


def _render_text(r):
    L = []
    W = 78
    L.append("=" * W)
    L.append(f"ACCOUNT DELETION REPORT — {r['account_rid']}")
    L.append("=" * W)
    L.append(f"r_number      : {r['r_number']}")
    L.append(f"org_schema    : {r['org_schema']}  (storage_type={r['storage_type']})")
    L.append(f"backup_schema : {r['backup_schema']}")
    L.append(f"status        : {r['status']}")
    L.append(f"started       : {r['started_at']}")
    L.append(f"finished      : {r['finished_at']}")
    if r["last_error"]:
        L.append(f"last_error    : {r['last_error']}")
    L.append(f"id-sets       : " + ", ".join(f"{k}={v}" for k, v in r["id_set_sizes"].items()))
    t = r["totals"]
    L.append("-" * W)
    L.append("TOTALS")
    L.append(f"  tables processed      : {t['tables_processed']}")
    L.append(f"  tables with data      : {t['tables_with_rows']}")
    L.append(f"  rows in scope         : {t['rows_in_scope']:,}   (would be deleted)")
    L.append(f"  rows deleted          : {t['rows_deleted']:,}")
    L.append(f"  rows backed up        : {t['rows_backed_up']:,}")
    L.append(f"  delete batches        : {t['batches']:,}")
    L.append(f"  unscoped tables       : {t['unscoped']}")
    L.append(f"  residual (>0 left)    : {t['residual_nonzero']}")
    L.append(f"  total time (s)        : {t['seconds']:.2f}")
    for s in r["steps"]:
        L.append("-" * W)
        L.append(f"STEP {s['step']}  —  {s['tables']} tables, "
                 f"{s['rows_in_scope']:,} in scope, {s['rows_deleted']:,} deleted, "
                 f"{s['rows_backed_up']:,} backed up, {s['batches']:,} batches, "
                 f"{s['step_seconds']:.2f}s")
        if s["unscoped"]:
            L.append(f"  ⚠ UNSCOPED (not touched): {', '.join(s['unscoped'])}")
        if s["residual"]:
            L.append("  ⚠ RESIDUAL rows remain:")
            for x in s["residual"]:
                L.append(f"      {x['table']}: {x['remaining']}")
    L.append("-" * W)
    L.append("TABLES WITH DATA (rows in scope = would be deleted)")
    for x in r["top_tables_by_scope"]:
        L.append(f"  {x['in_scope']:>10,}  {x['step']:<12} {x['table']}")
    if r["top_tables_by_rows"]:
        L.append("-" * W)
        L.append("TOP TABLES BY ROWS DELETED")
        for x in r["top_tables_by_rows"]:
            L.append(f"  {x['deleted']:>10,}  {x['step']:<12} {x['table']}")
    L.append("-" * W)
    L.append("SLOWEST TABLES")
    for x in r["slowest_tables"]:
        L.append(f"  {x['seconds']:>8.2f}s  {x['step']:<12} {x['table']}")
    L.append("=" * W)
    return "\n".join(L) + "\n"
