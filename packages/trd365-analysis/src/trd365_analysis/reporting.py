"""
Run outputs: two CSVs an operator can sort, and a summary they can read.

The CSV column names match the legacy tool's, so the spreadsheets and filters
people already have keep working across the port.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trd365_core.model_snapshot import ModelSnapshot

from . import deviations as dev
from .orphans import SchemaScan, totals

ORPHAN_COLUMNS = [
    "schema",
    "child_table",
    "column",
    "entity",
    "parent_table",
    "rows",
    "samples",
    "error",
]

DEVIATION_COLUMNS = ["schema", "child_table", "column", "prefix", "classification"]


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def write_orphans_csv(scans: list[SchemaScan], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ORPHAN_COLUMNS)
        writer.writeheader()
        for scan in scans:
            for orphan in scan.orphans:
                writer.writerow(orphan.to_row())
    return path


def write_deviations_csv(snapshot: ModelSnapshot, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DEVIATION_COLUMNS)
        writer.writeheader()
        for classification in (dev.TYPO, dev.UNKNOWN, dev.GLOBAL_LOOKUP, dev.POLYMORPHIC):
            for schema, table, column in dev.occurrences(snapshot, classification):
                writer.writerow(
                    {
                        "schema": schema,
                        "child_table": table,
                        "column": column,
                        "prefix": column.removesuffix("_rid"),
                        "classification": classification,
                    }
                )
    return path


def deviation_counts(snapshot: ModelSnapshot) -> dict[str, int]:
    """Kept as a name in this module; the implementation lives on the snapshot."""
    return snapshot.deviation_counts()


def summary(
    snapshot: ModelSnapshot,
    scans: list[SchemaScan],
    changes: list[dev.Reclassification],
) -> dict[str, Any]:
    """The machine-readable digest. Also the shape the health dashboard wants."""
    return {
        "environment": snapshot.environment,
        "version": snapshot.version,
        "fingerprint": snapshot.fingerprint,
        "generated_at": snapshot.generated_at,
        "schemas": len(snapshot.schemas),
        "model": snapshot.summary(),
        "deviations": deviation_counts(snapshot),
        "reclassified": len(changes),
        "false_alarms_withdrawn": len([c for c in changes if c.is_downgrade]),
        "orphans": totals(scans) if scans else None,
    }


def render_text(
    snapshot: ModelSnapshot,
    scans: list[SchemaScan],
    changes: list[dev.Reclassification],
) -> str:
    counts = deviation_counts(snapshot)
    lines = [
        "=" * 78,
        f"DATA-MODEL ANALYSIS — {snapshot.environment}",
        "=" * 78,
        f"version     : {snapshot.version}",
        f"fingerprint : {snapshot.fingerprint[:16]}",
        f"generated   : {snapshot.generated_at}",
        f"schemas     : {len(snapshot.schemas)}",
        "",
        "model:",
        *[f"  {key}: {value}" for key, value in sorted(snapshot.summary().items())],
        "",
        "naming deviations:",
        *[f"  {name}: {count}" for name, count in sorted(counts.items())],
    ]

    if changes:
        withdrawn = [c for c in changes if c.is_downgrade]
        lines += [
            "",
            f"cross-schema reclassification changed {len(changes)} prefix(es)"
            + (f", withdrawing {len(withdrawn)} false typo(s)" if withdrawn else ""),
        ]
        for change in changes[:20]:
            lines.append(f"  {change.schema}.{change.prefix}: {change.was} -> {change.now}")
        if len(changes) > 20:
            lines.append(f"  … and {len(changes) - 20} more, in the deviations CSV")

    typos = dev.occurrences(snapshot, dev.TYPO)
    if typos:
        lines += ["", f"LIKELY TYPOS — {len(typos)} column(s), worth a human look:"]
        for schema, table, column in typos[:20]:
            lines.append(f"  {schema}.{table}.{column}")
        if len(typos) > 20:
            lines.append(f"  … and {len(typos) - 20} more, in the deviations CSV")

    if scans:
        orphan_totals = totals(scans)
        lines += [
            "",
            "orphan rows:",
            *[f"  {key}: {value}" for key, value in sorted(orphan_totals.items())],
        ]
        worst = sorted(
            (o for scan in scans for o in scan.orphans if o.checked),
            key=lambda o: o.rows,
            reverse=True,
        )[:15]
        if worst:
            lines.append("  worst edges:")
            for orphan in worst:
                lines.append(
                    f"    {orphan.schema}.{orphan.child_table}.{orphan.column:<24} "
                    f"{orphan.rows:>8} -> {orphan.parent_table}"
                )
        failed = [o for scan in scans for o in scan.failed_edges]
        if failed:
            lines.append(f"  {len(failed)} edge(s) could not be checked — see the CSV")
    else:
        lines += ["", "orphan scan: not performed"]

    return "\n".join(lines) + "\n"


def write_reports(
    snapshot: ModelSnapshot,
    scans: list[SchemaScan],
    changes: list[dev.Reclassification],
    out_dir: str | Path,
) -> dict[str, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    at = stamp()

    text_path = directory / f"data_model_{snapshot.environment}_{at}.txt"
    text_path.write_text(render_text(snapshot, scans, changes), encoding="utf-8")

    paths = {
        "text": text_path,
        "deviations": write_deviations_csv(
            snapshot, directory / f"deviations_{snapshot.environment}_{at}.csv"
        ),
    }
    if scans:
        paths["orphans"] = write_orphans_csv(
            scans, directory / f"orphans_{snapshot.environment}_{at}.csv"
        )
    return paths
