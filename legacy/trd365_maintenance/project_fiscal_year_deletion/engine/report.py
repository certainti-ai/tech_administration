"""Per-project run report (human .txt + machine .json), plus NOTICE capture."""

import json
from pathlib import Path


def _safe(name):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(name))


def write_report(reports_dir, run):
    """`run` is the dict assembled per project in run.py. Writes <fiscal>_<ts>.txt
    and .json and returns (txt_path, json_path)."""
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
    stem = f"{_safe(run['project_fiscal_id'])}_{run['started_at_stamp']}"
    txt_path = Path(reports_dir) / f"{stem}.txt"
    json_path = Path(reports_dir) / f"{stem}.json"

    lines = []
    lines.append("=" * 78)
    lines.append(f"FISCAL-YEAR DELETION REPORT ({'DRY-RUN' if run['dry_run'] else 'LIVE'})")
    lines.append("=" * 78)
    lines.append(f"schema_name        : {run.get('schema_name')}")
    lines.append(f"account_rid        : {run.get('account_rid')}")
    lines.append(f"project_rid        : {run.get('project_rid')}")
    lines.append(f"project_fiscal_id  : {run['project_fiscal_id']}")
    lines.append(f"is_last_fiscal     : {run.get('is_last_fiscal')}")
    lines.append(f"backup_schema      : {run.get('backup_schema') or '(not captured)'}")
    lines.append(f"started_at         : {run.get('started_at')}")
    lines.append(f"finished_at        : {run.get('finished_at')}")
    lines.append(f"overall status     : {run['status']}")
    if run.get("error"):
        lines.append(f"error              : {run['error']}")
    lines.append("-" * 78)
    lines.append(f"{'section':<40} {'db':<10} {'status':<10} {'seconds':>8}")
    lines.append(f"{'-------':<40} {'--':<10} {'------':<10} {'-------':>8}")
    for s in run["sections"]:
        lines.append(f"{s['name']:<40} {s['db_key']:<10} {s['status']:<10} "
                     f"{s.get('seconds', 0):>8.2f}")
    lines.append("=" * 78)
    for s in run["sections"]:
        if s.get("notices"):
            lines.append("")
            lines.append(f"--- NOTICE output: {s['name']} ({s['db_key']}) ---")
            lines.extend("  " + n for n in s["notices"])
    txt = "\n".join(lines) + "\n"
    txt_path.write_text(txt)
    json_path.write_text(json.dumps(run, indent=2, default=str))
    return str(txt_path), str(json_path)
