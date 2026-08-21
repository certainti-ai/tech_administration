"""
Running the SECTION 1-8 flow for one project fiscal.

This is the atomic delete-and-recompute unit. A project fiscal purge runs it once;
a project purge runs it once per fiscal year, with the final one carrying
``is_last_fiscal`` so that its run also removes the project row and recomputes the
account-level totals.

Phase mapping, per fiscal:

======================  ===================================================
sections                what they do
======================  ===================================================
1 (org), 6 (ai)         analyse: pre-delete counts and a snapshot
2 (org), 3 (main), 7    back up, delete, and **recompute** the aggregates
4 (org), 5 (main), 8    audit: post-delete diffs
======================  ===================================================

Ported from ``legacy/trd365_maintenance/data_purge/project_fiscal/
fiscal_flow.py``. One behaviour changed, deliberately: the legacy version caught
every exception from a section, recorded it, and broke out of the loop leaving the
transaction open for the caller's ``finally`` to roll back — but on the *apply*
path it had already committed the sections before the failure, so the run stopped
half-applied with no record of which half. That is unavoidable with SQL that
commits per section, so instead of pretending otherwise this reports the last
section that committed, by name, in the result. A resumed run needs to know.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .. import sections as S

Log = Callable[[str], None]


@dataclass
class SectionOutcome:
    """What happened to one section."""

    number: int
    name: str
    db_key: str
    status: str = "pending"
    seconds: float = 0.0
    committed: bool = False
    error: str | None = None
    notices: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.number,
            "name": self.name,
            "db": self.db_key,
            "status": self.status,
            "seconds": self.seconds,
            "committed": self.committed,
            "error": self.error,
            "notices": self.notices,
        }


@dataclass
class FiscalOutcome:
    """What happened to one fiscal year's worth of sections."""

    project_fiscal_id: str
    project_rid: str
    schema_name: str
    fiscal_year: object
    is_last_fiscal: bool
    backup_schema: str
    sections: list[SectionOutcome] = field(default_factory=list)
    status: str = "ok"
    error: str | None = None

    @property
    def last_committed(self) -> SectionOutcome | None:
        """The furthest section that actually committed, for a resumed run."""
        committed = [outcome for outcome in self.sections if outcome.committed]
        return committed[-1] if committed else None

    def to_dict(self) -> dict[str, Any]:
        last = self.last_committed
        return {
            "project_fiscal_id": self.project_fiscal_id,
            "project_rid": self.project_rid,
            "schema_name": self.schema_name,
            "fiscal_year": self.fiscal_year,
            "is_last_fiscal": self.is_last_fiscal,
            "backup_schema": self.backup_schema,
            "status": self.status,
            "error": self.error,
            "last_committed_section": last.name if last else None,
            "sections": [outcome.to_dict() for outcome in self.sections],
        }


#: NOTICE lines worth showing without ``--verbose``: what was deleted, what was
#: recomputed, and each section's own banner.
_INTERESTING = ("deleted", "recompute", "section")


def _worth_showing(notice: str) -> bool:
    return any(word in notice.lower() for word in _INTERESTING)


def run_fiscal(
    pool,
    section_list: list[S.Section],
    params: Mapping[str, Any],
    *,
    backup_schema: str,
    dry_run: bool,
    log: Log,
    verbose: bool = False,
    heartbeat_seconds: int = 15,
) -> FiscalOutcome:
    """
    Run the sections for one fiscal.

    Applying commits each section as it succeeds, because the sections depend on
    each other's committed state. A dry run leaves every transaction open and rolls
    them all back at the end — which is why a later section can still see the
    backup schema an earlier one created while none of it is kept.
    """
    outcome = FiscalOutcome(
        project_fiscal_id=str(params["project_fiscal_id"]),
        project_rid=str(params["project_rid"]),
        schema_name=str(params["schema_name"]),
        fiscal_year=params.get("fiscal_year"),
        is_last_fiscal=S.as_bool(params.get("is_last_fiscal")),
        backup_schema=backup_schema,
    )
    touched: list[str] = []

    try:
        for section in section_list:
            record = SectionOutcome(
                number=section.number, name=section.name, db_key=section.db_key
            )
            outcome.sections.append(record)
            if section.db_key not in touched:
                touched.append(section.db_key)

            try:
                prepared = S.prepare(section, params, backup_schema)
            except S.SectionError as exc:
                record.status = "refused"
                record.error = str(exc)
                outcome.status = "error"
                outcome.error = str(exc)
                break

            log(f"    {section.name} on {section.db_key}")

            def progress(elapsed: int, latest: str | None, name=section.name) -> None:
                line = f"      … {name} running {elapsed}s"
                if verbose and latest:
                    line += f" — {latest}"
                log(line)

            started = time.time()
            try:
                notices = S.execute(
                    pool,
                    prepared,
                    dry_run=dry_run,
                    on_progress=progress,
                    interval=heartbeat_seconds,
                )
            except Exception as exc:
                record.status = "error"
                record.error = str(exc).strip()[:300]
                record.seconds = round(time.time() - started, 2)
                outcome.status = "error"
                outcome.error = f"{section.name}: {str(exc).strip()[:280]}"
                break

            record.seconds = round(time.time() - started, 2)
            record.status = "ok"
            record.committed = not dry_run
            record.notices = notices

            for notice in notices:
                if verbose or _worth_showing(notice):
                    log(f"      {notice}")
    finally:
        if dry_run:
            # Discard everything this fiscal did: the backup schema, the deletes
            # and the recompute.
            for db_key in touched:
                try:
                    pool.get(db_key).rollback()
                except Exception:  # noqa: BLE001 — a failed rollback must not mask the result
                    log(f"      warning: could not roll back {db_key}")

    return outcome
