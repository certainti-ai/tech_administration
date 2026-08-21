"""
The write path: what the application touches, in the order it touches it.

A port of ``legacy/trd365_maintenance/manual-rd-percent-update/index.js`` steps
6 and 7, which in turn trace ``entity-module/src/services/schemaService.ts``
``updateQreAdjustmentCalculation()`` and ``insertQreAdjustmentHistory()``.

Seven writes across two databases:

============================================  ========  ============================
table                                         database  condition
============================================  ========  ============================
``project_fiscal``                            org       always
``project_resource_fiscal``                   org       always
``case_projects``                             org       ``cases`` exists, non-closed
``case_project_resource_fiscal``              org       not mapped to a closed case
``project_timeline``                          org       always (audit)
``project_qre_adjustment_history``            org       always (audit)
``project_fiscal_summary``                    main      always
============================================  ========  ============================

**Two transactions, not one.** The main and org databases are separate Postgres
servers, so nothing can span them. The application does not try either — it awaits
two connections in sequence — so this does the same, in the same order. If the org
transaction commits and the main one then fails, the result is exactly the partial
state the application itself can leave, and the main statement is idempotent
(same key, same computed values) so re-running that record alone is safe.

**Every update is preceded by a snapshot of the rows it is about to overwrite,**
inside the same transaction, so a backup and its mutation always commit or roll
back together. The snapshot's ``WHERE`` matches the update's exactly — including
the closed-case joins — so a row that is not going to be touched is not captured
either, and the backup is a true record of what changed.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from trd365_core.datamodel import DEFAULT_MAIN_SCHEMA

from .calculation import Qre

Log = Callable[[str], None]

#: What the application records as the author of a change made through the UI
#: handler. This tool is not a user, so it writes the same literal the legacy tool
#: did rather than inventing an identity that no lookup would resolve.
SYSTEM_USER = "system"

#: The row-snapshot table, created per schema on first use.
BACKUP_TABLE = "rd_percent_backup"

#: Prefix for generated rids. ``project_qre_adjustment_history.rid`` has no
#: database-level default in the tenant schemas — the model's default is a
#: Sequelize literal applied client-side — so a raw insert that omits it violates
#: NOT NULL. Generating it the same way the ORM would produces an identical row
#: whether or not the column default exists.
RID_PREFIX = "P001-"

#: The audit-trail vocabulary the application uses, so a timeline entry written
#: here is indistinguishable from one the UI produced.
EVENT_NAME = "adjusted"
ENTITY_NAME = "QRE Percent"


@dataclass
class Backup:
    """What was snapshotted, so the report can say what could be restored."""

    run_id: str
    rows: dict[str, int] = field(default_factory=dict)

    def record(self, database: str, schema: str, table: str, count: int) -> None:
        if count:
            self.rows[f"{database}.{schema}.{table}"] = (
                self.rows.get(f"{database}.{schema}.{table}", 0) + count
            )

    @property
    def total(self) -> int:
        return sum(self.rows.values())


@dataclass
class Applied:
    """Which statements ran, and how many rows each changed."""

    backup: Backup
    updated: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    def record(self, table: str, count: int) -> None:
        self.updated[table] = count

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.backup.run_id,
            "rows_backed_up": dict(sorted(self.backup.rows.items())),
            "rows_updated": dict(sorted(self.updated.items())),
            "skipped": self.skipped,
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _one(conn, sql: str, params: tuple) -> tuple | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _execute(conn, sql: str, params: tuple) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def table_exists(conn, schema: str, table: str) -> bool:
    row = _one(
        conn,
        "SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
        (schema, table),
    )
    return row is not None


def ensure_backup_table(conn, schema: str) -> str:
    """
    Create the snapshot table if it is not there, and return its qualified name.

    Deliberately its own statement rather than part of a record's transaction: the
    table should survive a record whose write later rolls back. Only the snapshot
    *rows* are transactional with their update.
    """
    qualified = f"{quote(schema)}.{quote(BACKUP_TABLE)}"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {qualified} (
              id BIGSERIAL PRIMARY KEY,
              run_id TEXT NOT NULL,
              table_name TEXT NOT NULL,
              row_rid TEXT NOT NULL,
              row_data JSONB NOT NULL,
              backed_up_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    conn.commit()
    return qualified


def snapshot(
    conn, backup_table: str, run_id: str, table_name: str, source: str, where: str, params: tuple
) -> int:
    """
    Copy the rows an update is about to change into the snapshot table.

    ``where`` is the update's own predicate, so the two always select the same
    rows. Passing anything else would produce a backup that does not describe the
    change.
    """
    return _execute(
        conn,
        f"INSERT INTO {backup_table} (run_id, table_name, row_rid, row_data) "
        f"SELECT %s, %s, t.rid, to_jsonb(t) FROM {source} t WHERE {where}",
        (run_id, table_name, *params),
    )


# ---------------------------------------------------------------------------
# the org-side writes
# ---------------------------------------------------------------------------


def apply_org(
    conn,
    *,
    schema: str,
    project_fiscal_rid: str,
    project_rid: str,
    project_code: str | None,
    account_rid: str,
    qre: Qre,
    closed_status_rid: str | None,
    event_type_rid: str | None,
    created_by_name: str | None,
    comments: str | None,
    applied: Applied,
    log: Log,
) -> None:
    """Everything in the tenant's org schema, in one transaction."""
    backup_table = ensure_backup_table(conn, schema)
    run_id = applied.backup.run_id
    q = qre

    # project_fiscal — the one place this writes rd_percent_potential_ai, which
    # the live endpoint never touches. See calculation.py.
    source = f"{quote(schema)}.{quote('project_fiscal')}"
    applied.backup.record(
        "org",
        schema,
        "project_fiscal",
        snapshot(conn, backup_table, run_id, "project_fiscal", source, "t.rid = %s",
                 (project_fiscal_rid,)),
    )
    applied.record(
        "project_fiscal",
        _execute(
            conn,
            f"UPDATE {source} SET rd_percent_potential_ai=%s, rd_percent_adjustment=%s, "
            f"rd_percent_final=%s, qre_final=%s, qre_fte=%s, qre_subcon=%s, qre_nonlabor=%s, "
            f"modified_by=%s, modified_datetime=now(), is_qualified=%s WHERE rid=%s",
            (q.potential_ai, q.adjustment, q.net_percent, q.final, q.fte, q.subcon,
             q.nonlabor, SYSTEM_USER, q.is_qualified, project_fiscal_rid),
        ),
    )

    # project_resource_fiscal — no rd_percent_potential_ai and no is_qualified
    # here; the application sets neither on this table.
    source = f"{quote(schema)}.{quote('project_resource_fiscal')}"
    applied.backup.record(
        "org",
        schema,
        "project_resource_fiscal",
        snapshot(conn, backup_table, run_id, "project_resource_fiscal", source,
                 "t.project_fiscal_rid = %s", (project_fiscal_rid,)),
    )
    applied.record(
        "project_resource_fiscal",
        _execute(
            conn,
            f"UPDATE {source} SET rd_percent_adjustment=%s, rd_percent_final=%s, qre_final=%s, "
            f"qre_fte=%s, qre_subcon=%s, qre_nonlabor=%s, modified_by=%s, "
            f"modified_datetime=now() WHERE project_fiscal_rid=%s",
            (q.adjustment, q.net_percent, q.final, q.fte, q.subcon, q.nonlabor,
             SYSTEM_USER, project_fiscal_rid),
        ),
    )

    _apply_case_module(
        conn,
        backup_table=backup_table,
        schema=schema,
        project_fiscal_rid=project_fiscal_rid,
        qre=q,
        closed_status_rid=closed_status_rid,
        applied=applied,
        log=log,
    )

    # The audit timeline entry. rid, r_number, created_datetime and event_datetime
    # are left to the table's own defaults, exactly as the application's insert
    # does — it never sets them either.
    applied.record(
        "project_timeline",
        _execute(
            conn,
            f"INSERT INTO {quote(schema)}.{quote('project_timeline')} ("
            f"created_by, event_type_rid, event_name, descriptions, account_rid, "
            f"entity_name, entity_rid, created_by_name, project_rid) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (SYSTEM_USER, event_type_rid, EVENT_NAME, f"for {project_code}", account_rid,
             ENTITY_NAME, project_fiscal_rid, created_by_name, project_rid),
        ),
    )

    # The adjustment history row. Stores the *delta*, matching the application's
    # field naming, not the final percentage.
    applied.record(
        "project_qre_adjustment_history",
        _execute(
            conn,
            f"INSERT INTO {quote(schema)}.{quote('project_qre_adjustment_history')} ("
            f"rid, project_fiscal_rid, account_rid, rd_percent_adjustment, comment, "
            f"created_by, created_datetime) "
            f"VALUES (%s::text || gen_random_uuid(), %s, %s, %s, %s, %s, now())",
            (RID_PREFIX, project_fiscal_rid, account_rid, q.adjustment, comments, SYSTEM_USER),
        ),
    )


def _apply_case_module(
    conn,
    *,
    backup_table: str,
    schema: str,
    project_fiscal_rid: str,
    qre: Qre,
    closed_status_rid: str | None,
    applied: Applied,
    log: Log,
) -> None:
    """
    The case module's copies of the same figures, where they exist and may change.

    Two conditions, both the application's and both about closed cases, whose
    financials are frozen by design:

    * ``case_projects`` is updated only for rows attached to a case that is *not*
      closed;
    * ``case_project_resource_fiscal`` is skipped entirely if the project is mapped
      to *any* closed case — not per row, all or nothing.
    """
    if not table_exists(conn, schema, "cases"):
        applied.skipped.append("case_projects: no cases table in this schema")
        applied.skipped.append("case_project_resource_fiscal: no cases table in this schema")
        return
    if not closed_status_rid:
        # Without it there is no way to tell a closed case from an open one, and
        # updating everything would rewrite frozen financials.
        applied.skipped.append("case_projects: no closed case status could be resolved")
        applied.skipped.append(
            "case_project_resource_fiscal: no closed case status could be resolved"
        )
        return

    q = qre
    source = (
        f"{quote(schema)}.{quote('case_projects')} cp "
        f"JOIN {quote(schema)}.{quote('cases')} c ON cp.case_rid = c.rid"
    )
    # The snapshot uses the update's own join and filter, so only rows that will
    # actually change are captured.
    captured = _execute(
        conn,
        f"INSERT INTO {backup_table} (run_id, table_name, row_rid, row_data) "
        f"SELECT %s, %s, cp.rid, to_jsonb(cp) FROM {source} "
        f"WHERE cp.project_fiscal_rid = %s AND c.status_rid <> %s",
        (applied.backup.run_id, "case_projects", project_fiscal_rid, closed_status_rid),
    )
    applied.backup.record("org", schema, "case_projects", captured)
    applied.record(
        "case_projects",
        _execute(
            conn,
            f"UPDATE {quote(schema)}.{quote('case_projects')} cp "
            f"SET qre_fte=%s, qre_subcon=%s, qre_nonlabor=%s, qre_final=%s, "
            f"rd_percent_adjustment=%s, rd_percent_final=%s, modified_by=%s, "
            f"modified_datetime=now() "
            f"FROM {quote(schema)}.{quote('cases')} c "
            f"WHERE cp.case_rid = c.rid AND cp.project_fiscal_rid = %s AND c.status_rid <> %s",
            (q.fte, q.subcon, q.nonlabor, q.final, q.adjustment, q.net_percent, SYSTEM_USER,
             project_fiscal_rid, closed_status_rid),
        ),
    )

    mapped_to_closed = _one(
        conn,
        f"SELECT 1 FROM {quote(schema)}.{quote('cases')} c "
        f"LEFT JOIN {quote(schema)}.{quote('case_projects')} cp ON cp.case_rid = c.rid "
        f"WHERE cp.project_fiscal_rid = %s AND c.status_rid = %s LIMIT 1",
        (project_fiscal_rid, closed_status_rid),
    )
    if mapped_to_closed is not None:
        log("    case_project_resource_fiscal: skipped — mapped to a closed case")
        applied.skipped.append("case_project_resource_fiscal: mapped to a closed case")
        return
    if not table_exists(conn, schema, "case_project_resource_fiscal"):
        applied.skipped.append("case_project_resource_fiscal: not present in this schema")
        return

    source = f"{quote(schema)}.{quote('case_project_resource_fiscal')}"
    applied.backup.record(
        "org",
        schema,
        "case_project_resource_fiscal",
        snapshot(conn, backup_table, applied.backup.run_id, "case_project_resource_fiscal",
                 source, "t.project_fiscal_rid = %s", (project_fiscal_rid,)),
    )
    applied.record(
        "case_project_resource_fiscal",
        _execute(
            conn,
            f"UPDATE {source} SET rd_percent_adjustment=%s, rd_percent_final=%s, qre_final=%s, "
            f"qre_fte=%s, qre_subcon=%s, qre_nonlabor=%s, modified_by=%s, "
            f"modified_datetime=now() WHERE project_fiscal_rid=%s",
            (q.adjustment, q.net_percent, q.final, q.fte, q.subcon, q.nonlabor,
             SYSTEM_USER, project_fiscal_rid),
        ),
    )


# ---------------------------------------------------------------------------
# the main-side write
# ---------------------------------------------------------------------------


def apply_main(
    conn, *, project_fiscal_rid: str, qre: Qre, applied: Applied
) -> None:
    """
    The shared summary row, in its own transaction on the other server.

    Idempotent: the same key and the same computed values. So if the org
    transaction has already committed and this fails, re-running just this record
    is safe.
    """
    backup_table = ensure_backup_table(conn, DEFAULT_MAIN_SCHEMA)
    source = f"{quote(DEFAULT_MAIN_SCHEMA)}.{quote('project_fiscal_summary')}"
    applied.backup.record(
        "main",
        DEFAULT_MAIN_SCHEMA,
        "project_fiscal_summary",
        snapshot(conn, backup_table, applied.backup.run_id, "project_fiscal_summary", source,
                 "t.project_fiscal_rid = %s", (project_fiscal_rid,)),
    )
    q = qre
    applied.record(
        "project_fiscal_summary",
        _execute(
            conn,
            f"UPDATE {source} SET rd_percent_adjustment=%s, rd_percent_final=%s, qre_final=%s, "
            f"qre_fte=%s, qre_subcon=%s, qre_nonlabor=%s, modified_by=%s, "
            f"modified_datetime=now(), is_qualified=%s WHERE project_fiscal_rid=%s",
            (q.adjustment, q.net_percent, q.final, q.fte, q.subcon, q.nonlabor,
             SYSTEM_USER, q.is_qualified, project_fiscal_rid),
        ),
    )


def new_run_id() -> str:
    return str(uuid.uuid4())
