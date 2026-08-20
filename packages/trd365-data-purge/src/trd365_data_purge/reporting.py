"""Human- and machine-readable run reports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .checkpoint import Checkpoint

#: Statuses that mean the table was looked at but nothing was written.
QUIET_STATUSES = ("skipped", "empty", "dry-run")


def summarise(checkpoint: Checkpoint) -> dict[str, Any]:
    """Totals across every step, for the report header and the API."""
    totals = {
        "tables_processed": 0,
        "tables_with_rows": 0,
        "tables_unscoped": 0,
        "rows_deleted": 0,
        "rows_backed_up": 0,
        "rows_in_scope": 0,
    }
    unscoped: list[str] = []

    for step_key, tables in checkpoint.metrics.items():
        for table, metrics in tables.items():
            if table == "_step_seconds":
                continue
            totals["tables_processed"] += 1
            totals["rows_deleted"] += metrics.get("deleted", 0)
            totals["rows_backed_up"] += metrics.get("backed_up", 0)
            totals["rows_in_scope"] += metrics.get("scope_before", 0)
            if metrics.get("scope_before", 0) > 0:
                totals["tables_with_rows"] += 1
            if metrics.get("status") == "unscoped":
                totals["tables_unscoped"] += 1
                unscoped.append(f"{step_key}/{table}")

    totals["unscoped_tables"] = sorted(unscoped)
    return totals


def render_text(checkpoint: Checkpoint, applied: bool) -> str:
    """The report an operator reads."""
    totals = summarise(checkpoint)
    mode = "APPLY" if applied else "DRY RUN"
    lines = [
        "=" * 78,
        f"{checkpoint.entity.upper()} PURGE — {mode}",
        "=" * 78,
        f"environment : {checkpoint.environment}",
        f"entity rid  : {checkpoint.entity_rid}",
        f"run id      : {checkpoint.run_id}",
        f"started     : {checkpoint.started_at}",
        f"finished    : {checkpoint.finished_at or '(incomplete)'}",
        "",
        f"tables processed : {totals['tables_processed']}",
        f"tables with rows : {totals['tables_with_rows']}",
        f"rows in scope    : {totals['rows_in_scope']}",
        f"rows deleted     : {totals['rows_deleted']}",
        f"rows backed up   : {totals['rows_backed_up']}",
        "",
    ]

    if checkpoint.resolved:
        lines.append("resolved:")
        lines += [f"  {k}: {v}" for k, v in sorted(checkpoint.resolved.items())]
        lines.append("")

    for step_key, tables in checkpoint.metrics.items():
        seconds = tables.get("_step_seconds")
        header = f"--- {step_key}" + (f"  ({seconds}s)" if seconds is not None else "")
        lines.append(header)
        for table, metrics in sorted(tables.items()):
            if table == "_step_seconds":
                continue
            status = metrics.get("status", "?")
            if status in QUIET_STATUSES and metrics.get("scope_before", 0) == 0:
                continue
            lines.append(
                f"    {table:<44} {status:<11} "
                f"scope={metrics.get('scope_before', 0):<8} "
                f"deleted={metrics.get('deleted', 0):<8} "
                f"backed_up={metrics.get('backed_up', 0)}"
            )
            if metrics.get("note"):
                lines.append(f"        note: {metrics['note']}")
        lines.append("")

    if totals["unscoped_tables"]:
        lines += [
            "UNSCOPED — left untouched, need manual review:",
            *[f"  {t}" for t in totals["unscoped_tables"]],
            "",
        ]

    if checkpoint.audit_clean is None:
        lines.append("AUDIT: not performed (dry run)")
    elif checkpoint.audit_clean:
        lines.append("AUDIT: clean — no residual rows, backups match deletes, no collateral")
    else:
        lines.append(f"AUDIT: {len(checkpoint.findings)} FINDING(S)")
        for finding in checkpoint.findings:
            lines.append(f"  {finding['step']}/{finding['table']}: " + "; ".join(finding["issues"]))

    if checkpoint.error:
        lines += ["", f"ERROR: {checkpoint.error}"]

    return "\n".join(lines) + "\n"


def write_report(checkpoint: Checkpoint, applied: bool, out_dir: str | Path) -> dict[str, Path]:
    """Write the text and JSON reports; return their paths."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_rid = "".join(c if c.isalnum() or c in "-_" else "_" for c in checkpoint.entity_rid)[:80]
    stem = f"{checkpoint.entity}_{safe_rid}_{stamp}"

    text_path = directory / f"{stem}.txt"
    json_path = directory / f"{stem}.json"

    text_path.write_text(render_text(checkpoint, applied), encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {**checkpoint.to_dict(), "totals": summarise(checkpoint)}, indent=2, default=str
        ),
        encoding="utf-8",
    )
    return {"text": text_path, "json": json_path}
