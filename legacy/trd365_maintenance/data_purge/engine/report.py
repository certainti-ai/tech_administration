"""Summary report for one entity purge (JSON + human-readable text).

Entity-agnostic: driven entirely by the ``run`` dict that purge_<entity>.py
assembles (entity/rid/context, per-step per-table metrics, audit findings).
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def _safe(s):
    return "".join(c if c.isalnum() else "_" for c in str(s))


def summarize(run):
    grand = {"tables_processed": 0, "tables_with_rows": 0, "rows_in_scope": 0,
             "rows_deleted": 0, "rows_backed_up": 0, "batches": 0, "unscoped": 0,
             "skipped": 0, "residual_nonzero": 0, "seconds": 0.0}
    steps_out, per_rows, per_scope = [], [], []
    label = {s["step"]: (s["db"], s["schema"]) for s in run["steps_meta"]}

    for meta in run["steps_meta"]:
        step_key = meta["step"]
        tm = run["metrics"].get(step_key, {})
        srow = {"step": step_key, "db": meta["db"], "schema": meta["schema"],
                "step_seconds": tm.get("_step_seconds", 0.0),
                "tables": 0, "rows_in_scope": 0, "rows_deleted": 0,
                "rows_backed_up": 0, "batches": 0, "unscoped": [], "residual": []}
        for table, m in tm.items():
            if table == "_step_seconds":
                continue
            srow["tables"] += 1
            grand["tables_processed"] += 1
            sb = m.get("scope_before", 0); d = m.get("deleted", 0)
            srow["rows_in_scope"] += sb; srow["rows_deleted"] += d
            srow["rows_backed_up"] += m.get("backed_up", 0); srow["batches"] += m.get("batches", 0)
            grand["rows_in_scope"] += sb; grand["rows_deleted"] += d
            grand["rows_backed_up"] += m.get("backed_up", 0); grand["batches"] += m.get("batches", 0)
            grand["seconds"] += m.get("seconds", 0.0)
            if sb > 0 or d > 0:
                grand["tables_with_rows"] += 1
            if m.get("status") == "unscoped":
                grand["unscoped"] += 1; srow["unscoped"].append(table)
            if m.get("status") == "skipped":
                grand["skipped"] += 1
            if m.get("scope_after", 0) > 0:
                grand["residual_nonzero"] += 1
                srow["residual"].append({"table": table, "remaining": m["scope_after"]})
            per_rows.append((d, step_key, table))
            per_scope.append((sb, step_key, table))
        steps_out.append(srow)

    per_rows.sort(reverse=True); per_scope.sort(reverse=True)
    audit = run.get("audit") or {"findings": [], "clean": None}
    return {
        "entity": run["entity"], "entity_rid": run["entity_rid"],
        "run_id": run["run_id"], "backup_schema": run["backup_schema"],
        "context": run.get("context", {}),
        "status": run.get("status"), "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"), "last_error": run.get("last_error"),
        "totals": grand, "steps": steps_out,
        "audit_clean": audit.get("clean"), "audit_findings": audit.get("findings", []),
        "top_tables_by_scope": [{"table": t, "step": s, "in_scope": sb}
                                for sb, s, t in per_scope[:25] if sb > 0],
        "top_tables_by_rows": [{"table": t, "step": s, "deleted": d}
                               for d, s, t in per_rows[:25] if d > 0],
    }


def write_report(reports_dir, run):
    rep = summarize(run)
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = Path(reports_dir) / f"{run['entity']}_{_safe(run['entity_rid'])}_{ts}"
    with open(str(base) + ".json", "w") as fh:
        json.dump(rep, fh, indent=2, default=str)
    with open(str(base) + ".txt", "w") as fh:
        fh.write(_render_text(rep))
    return str(base) + ".txt", str(base) + ".json"


def _render_text(r):
    L, W = [], 78
    L.append("=" * W)
    L.append(f"DATA PURGE REPORT — {r['entity'].upper()} {r['entity_rid']}")
    L.append("=" * W)
    for k, v in r["context"].items():
        L.append(f"{k:<20}: {v}")
    L.append(f"{'run_id':<20}: {r['run_id']}")
    L.append(f"{'backup_schema':<20}: {r['backup_schema']}  (bak_<table> in each impacted DB)")
    L.append(f"{'status':<20}: {r['status']}")
    L.append(f"{'started':<20}: {r['started_at']}")
    L.append(f"{'finished':<20}: {r['finished_at']}")
    if r["last_error"]:
        L.append(f"{'last_error':<20}: {r['last_error']}")
    t = r["totals"]
    L.append("-" * W)
    L.append("TOTALS")
    L.append(f"  tables processed   : {t['tables_processed']}")
    L.append(f"  tables with data   : {t['tables_with_rows']}")
    L.append(f"  rows in scope      : {t['rows_in_scope']:,}   (impacted / would delete)")
    L.append(f"  rows deleted       : {t['rows_deleted']:,}")
    L.append(f"  rows backed up     : {t['rows_backed_up']:,}")
    L.append(f"  delete batches     : {t['batches']:,}")
    L.append(f"  unscoped tables    : {t['unscoped']}")
    L.append(f"  residual (>0 left) : {t['residual_nonzero']}")
    L.append(f"  total time (s)     : {t['seconds']:.2f}")
    # AUDIT
    L.append("-" * W)
    if r["audit_clean"] is None:
        L.append("AUDIT : (dry-run — not performed)")
    elif r["audit_clean"]:
        L.append("AUDIT : ✓ CLEAN — every processed table: 0 residual in-scope rows, "
                 "backups == deletes, no collateral rows removed")
    else:
        L.append(f"AUDIT : ✗ {len(r['audit_findings'])} ISSUE(S) — review before trusting this run")
        for f in r["audit_findings"]:
            L.append(f"    {f['schema']}.{f['table']}: " + "; ".join(f["issues"]))
    # per-step
    for s in r["steps"]:
        L.append("-" * W)
        L.append(f"STEP {s['step']}  ({s['db']} / {s['schema']})  —  {s['tables']} tables, "
                 f"{s['rows_in_scope']:,} in scope, {s['rows_deleted']:,} deleted, "
                 f"{s['rows_backed_up']:,} backed up, {s['batches']:,} batches, {s['step_seconds']:.2f}s")
        if s["unscoped"]:
            L.append(f"  ⚠ UNSCOPED (not touched): {', '.join(s['unscoped'])}")
        if s["residual"]:
            L.append("  ⚠ RESIDUAL rows remain:")
            for x in s["residual"]:
                L.append(f"      {x['table']}: {x['remaining']}")
    L.append("-" * W)
    L.append("TABLES WITH DATA (rows in scope = impacted)")
    for x in r["top_tables_by_scope"]:
        L.append(f"  {x['in_scope']:>10,}  {x['step']:<14} {x['table']}")
    L.append("=" * W)
    return "\n".join(L) + "\n"
