"""
The generic, entity-agnostic purge engine.

Ported from ``legacy/trd365_maintenance/data_purge/engine/core.py``, which was
already the right shape: it knows nothing about accounts or cases. An entity
purge is a list of STEPS — one per database, each a child-before-parent ordered
list of tables — plus a *scoper* that turns a table into the WHERE clause
selecting the rows belonging to the target entity.

Five phases, unchanged from the original:

1. **Analyse** — resolve each table's predicate and count impacted rows. Read
   only, and also what a dry run stops at.
2. **Backup** — copy impacted rows into ``data_purge.bak_<table>`` in the *same*
   database, tagged with run id, entity and timestamp.
3. **Delete** — in small committed chunks, with the backup and the delete in the
   **same transaction**, so a backup row exists if and only if the source row
   was removed. Children before parents; anything still FK-blocked is deferred
   and retried on a later pass.
4. **Audit** — for every processed table: no in-scope rows remain, rows backed
   up equals rows deleted, and the table's total dropped by exactly the number
   deleted, so nothing was lost to an unexpected cascade.
5. **Report** — see :mod:`trd365_data_purge.reporting`.

What changed in the port
------------------------
The original cached column and foreign-key metadata in **module-level dicts
keyed by (schema, table) only** — not by database — and ``clear_caches()`` was
never called anywhere in the tree. In a one-shot CLI that is nearly harmless.
Under the Phase-2 orchestrator, which is a long-running process executing many
purges, it becomes two real problems: metadata cached from one database can be
served for another that happens to share a schema and table name, and a schema
change between jobs is never noticed. The cache is now keyed by database as
well, and owned by a :class:`SchemaCache` instance scoped to a single run, so it
cannot leak across jobs.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import psycopg2

#: Backups always land in this schema, in the same database as their source.
BACKUP_SCHEMA = "data_purge"

#: Appended to every ``data_purge.bak_<table>`` so a backup row can be traced
#: to the run that made it.
AUDIT_COLS: tuple[tuple[str, str], ...] = (
    ("_purge_run_at", "timestamptz"),
    ("_purge_run_id", "text"),
    ("_purge_entity", "text"),
    ("_purge_entity_rid", "text"),
)

#: Upper bound on FK-deferral retry passes before a run is declared stuck.
MAX_PASSES = 25

Log = Callable[[str], None]


def quote(identifier: str) -> str:
    """Quote an SQL identifier. Table and schema names come from the database's
    own catalog, but they are still interpolated into SQL, so they are quoted."""
    return '"' + identifier.replace('"', '""') + '"'


# --------------------------------------------------------------------------
# schema metadata, cached per run
# --------------------------------------------------------------------------


@dataclass
class SchemaCache:
    """
    Column and foreign-key metadata for the duration of one purge.

    Keyed by ``(db_key, schema, table)``. Instance-scoped rather than global, so
    a long-running service cannot serve one job's metadata to another.
    """

    _columns: dict[tuple[str, str, str], set[str]] = field(default_factory=dict)
    _fks: dict[tuple[str, str, str], list[tuple]] = field(default_factory=dict)
    _exists: dict[tuple[str, str, str], bool] = field(default_factory=dict)

    def table_exists(self, conn, db_key: str, schema: str, table: str) -> bool:
        key = (db_key, schema, table)
        if key not in self._exists:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_name=%s",
                    (schema, table),
                )
                self._exists[key] = cur.fetchone() is not None
        return self._exists[key]

    def columns(self, conn, db_key: str, schema: str, table: str) -> set[str]:
        key = (db_key, schema, table)
        if key not in self._columns:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=%s AND table_name=%s",
                    (schema, table),
                )
                self._columns[key] = {row[0] for row in cur.fetchall()}
        return self._columns[key]

    def single_column_fks(self, conn, db_key: str, schema: str, table: str) -> list[tuple]:
        """Single-column foreign keys as ``(local_col, ref_table, ref_col)``."""
        key = (db_key, schema, table)
        if key not in self._fks:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT (SELECT attname FROM pg_attribute
                            WHERE attrelid=c.conrelid AND attnum=c.conkey[1]),
                           rt.relname,
                           (SELECT attname FROM pg_attribute
                            WHERE attrelid=c.confrelid AND attnum=c.confkey[1])
                    FROM pg_constraint c
                    JOIN pg_class t  ON t.oid = c.conrelid
                    JOIN pg_class rt ON rt.oid = c.confrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname=%s AND t.relname=%s AND c.contype='f'
                      AND array_length(c.conkey, 1) = 1
                    """,
                    (schema, table),
                )
                self._fks[key] = cur.fetchall()
        return self._fks[key]


def count_where(conn, schema: str, table: str, where: str, params) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {quote(schema)}.{quote(table)} WHERE {where}", params)
        return cur.fetchone()[0]


def count_all(conn, schema: str, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {quote(schema)}.{quote(table)}")
        return cur.fetchone()[0]


# --------------------------------------------------------------------------
# backup target
# --------------------------------------------------------------------------


def ensure_backup_table(conn, bak_schema: str, schema: str, table: str) -> str:
    """Create ``<bak_schema>.bak_<table>`` LIKE the source, plus audit columns."""
    # Postgres truncates identifiers at 63 bytes; truncating here keeps the name
    # we use identical to the one the server stores.
    bak_table = f"bak_{table}"[:63]
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {quote(bak_schema)}")
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {quote(bak_schema)}.{quote(bak_table)} "
            f"(LIKE {quote(schema)}.{quote(table)} INCLUDING DEFAULTS)"
        )
        additions = ", ".join(
            f"ADD COLUMN IF NOT EXISTS {quote(name)} {sql_type}" for name, sql_type in AUDIT_COLS
        )
        cur.execute(f"ALTER TABLE {quote(bak_schema)}.{quote(bak_table)} {additions}")
    conn.commit()
    return bak_table


# --------------------------------------------------------------------------
# one table
# --------------------------------------------------------------------------

FK_VIOLATION = "23503"


@dataclass
class RunTag:
    """Stamped onto every backup row so it can be traced to its run."""

    run_at: str
    run_id: str
    entity: str
    entity_rid: str

    def as_row(self) -> list[str]:
        return [self.run_at, self.run_id, self.entity, self.entity_rid]


def new_metrics(table: str, schema: str) -> dict[str, Any]:
    return {
        "table": table,
        "schema": schema,
        "status": "ok",
        "scope_before": 0,
        "total_before": 0,
        "deleted": 0,
        "backed_up": 0,
        "batches": 0,
        "scope_after": 0,
        "total_after": 0,
        "seconds": 0.0,
        "note": "",
    }


def process_table(
    conn,
    cache: SchemaCache,
    db_key: str,
    schema: str,
    table: str,
    where: str,
    params,
    tag: RunTag,
    bak_schema: str,
    chunk_size: int,
    dry_run: bool,
    log: Log,
) -> dict[str, Any]:
    """
    Back up and delete one table's in-scope rows, in committed chunks.

    The backup insert and the delete run in the same transaction, so a backup
    row exists if and only if the source row was removed — the invariant the
    audit phase later checks. A foreign-key violation rolls that batch back and
    marks the table deferred rather than failing the run; the caller retries it
    once its children are gone.
    """
    started = time.time()
    metrics = new_metrics(table, schema)

    if not cache.table_exists(conn, db_key, schema, table):
        metrics["status"] = "skipped"
        metrics["note"] = "table not present"
        metrics["seconds"] = round(time.time() - started, 3)
        log(f"    {table}: skip (not present)")
        return metrics

    before = count_where(conn, schema, table, where, params)
    metrics["scope_before"] = before
    metrics["total_before"] = count_all(conn, schema, table)

    if before == 0:
        metrics["status"] = "empty"
        metrics["total_after"] = metrics["total_before"]
        metrics["seconds"] = round(time.time() - started, 3)
        log(f"    {table}: 0 rows in scope")
        return metrics

    if dry_run:
        metrics["status"] = "dry-run"
        metrics["seconds"] = round(time.time() - started, 3)
        log(f"    {table}: would back up + delete {before} of {metrics['total_before']} row(s)")
        return metrics

    bak_table = ensure_backup_table(conn, bak_schema, schema, table)
    deleted = backed_up = batches = 0
    fk_blocked = False

    while True:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT ctid FROM {quote(schema)}.{quote(table)} "
                f"WHERE {where} LIMIT {int(chunk_size)}",
                params,
            )
            ctids = [row[0] for row in cur.fetchall()]
        if not ctids:
            break

        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {quote(bak_schema)}.{quote(bak_table)} "
                    f"SELECT t.*, %s, %s, %s, %s FROM {quote(schema)}.{quote(table)} t "
                    f"WHERE t.ctid = ANY(%s::tid[])",
                    [*tag.as_row(), ctids],
                )
                backed_this_batch = cur.rowcount
                cur.execute(
                    f"DELETE FROM {quote(schema)}.{quote(table)} WHERE ctid = ANY(%s::tid[])",
                    [ctids],
                )
                deleted_this_batch = cur.rowcount
            conn.commit()
        except psycopg2.Error as exc:
            conn.rollback()
            if getattr(exc, "pgcode", None) == FK_VIOLATION:
                fk_blocked = True
                metrics["note"] = "FK-blocked (deferred): " + str(exc).strip().splitlines()[0]
                break
            raise

        backed_up += backed_this_batch
        deleted += deleted_this_batch
        batches += 1
        if batches % 10 == 0:
            log(f"      {table}: {deleted}/{before} deleted ({batches} batches)")

    metrics.update(
        {
            "deleted": deleted,
            "backed_up": backed_up,
            "batches": batches,
            "scope_after": count_where(conn, schema, table, where, params),
            "total_after": count_all(conn, schema, table),
            "seconds": round(time.time() - started, 3),
        }
    )

    if fk_blocked:
        metrics["status"] = "fk_blocked"
        log(f"    {table}: FK-blocked after {deleted} row(s) — deferring for retry")
    else:
        log(
            f"    {table}: deleted {deleted} (backed up {backed_up}) in {batches} batch(es), "
            f"{metrics['seconds']}s, remaining {metrics['scope_after']}"
        )
    return metrics


# --------------------------------------------------------------------------
# orchestration across steps / databases
# --------------------------------------------------------------------------


class Scoper(Protocol):
    def predicate(self, conn, schema: str, table: str, kind: str): ...


def run_steps(
    pool,
    steps,
    schema_for: dict[str, str],
    scoper,
    tag: RunTag,
    cache: SchemaCache,
    *,
    bak_schema: str = BACKUP_SCHEMA,
    chunk_size: int,
    dry_run: bool,
    log: Log,
    metrics: dict,
    completed: dict,
    persist: Callable[[], None],
    on_rows: Callable[[str, int], None] | None = None,
) -> tuple[bool, str | None]:
    """
    Execute every step in order, children before parents, retrying FK-blocked
    tables on later passes.

    ``persist`` is called after each table so a killed run resumes cleanly, and
    ``on_rows`` reports ``(qualified_table, deleted)`` so the caller can record
    row counts in the audit trail as the run proceeds rather than at the end.
    """
    for step_key, db_key, kind, tables in steps:
        conn = pool.get(db_key)
        schema = schema_for[kind]
        conn.rollback()

        tables = list(tables)
        if hasattr(scoper, "discover"):
            extra = scoper.discover(conn, schema, kind, tables)
            if extra:
                log(f"  + {len(extra)} scoped table(s) not in manifest (auto-discovered): {extra}")
                tables += extra

        done = set(completed.get(step_key, []))
        metrics.setdefault(step_key, {})
        log(f"\n  === STEP {step_key} ({db_key} / {schema}) — {len(tables)} tables ===")
        step_started = time.time()

        worklist = [t for t in tables if t not in done]
        pass_no = 0

        while worklist and pass_no < MAX_PASSES:
            pass_no += 1
            if pass_no > 1:
                log(f"  --- retry pass {pass_no}: {len(worklist)} deferred table(s) ---")
            deferred: list[str] = []
            progressed = False

            for table in worklist:
                try:
                    conn.rollback()
                    if not cache.table_exists(conn, db_key, schema, table):
                        # Checked before scoping, not after. A table that is not
                        # in this schema has no columns, so asking the scoper
                        # would return None and report it as needing manual
                        # review — turning "the manifest covers releases this
                        # tenant does not have" into eighty false review items.
                        table_metrics = new_metrics(table, schema)
                        table_metrics["status"] = "skipped"
                        table_metrics["note"] = "table not present"
                        log(f"    {table}: skip (not present)")
                        metrics[step_key][table] = table_metrics
                        if not dry_run:
                            done.add(table)
                            completed[step_key] = sorted(done)
                        progressed = True
                        continue

                    predicate = scoper.predicate(conn, schema, table, kind)
                    if predicate is None:
                        # The table is here, and nothing ties it to the entity.
                        # That is a real finding: reported for a human, never
                        # guessed at.
                        table_metrics = new_metrics(table, schema)
                        table_metrics["status"] = "unscoped"
                        table_metrics["note"] = "no scope column; NOT touched"
                        log(f"    {table}: UNSCOPED — left untouched (needs manual review)")
                    else:
                        where, params = predicate
                        table_metrics = process_table(
                            conn, cache, db_key, schema, table, where, params, tag,
                            bak_schema, chunk_size, dry_run, log,
                        )
                except Exception as exc:  # noqa: BLE001 — returned to the caller
                    conn.rollback()
                    error = f"{step_key}/{table}: {str(exc).strip()}"
                    log(f"    ERROR on {table}: {error}")
                    return False, error

                metrics[step_key][table] = table_metrics

                if table_metrics["status"] == "fk_blocked":
                    deferred.append(table)
                    if table_metrics.get("deleted", 0) > 0:
                        progressed = True
                else:
                    if not dry_run:
                        done.add(table)
                        completed[step_key] = sorted(done)
                        persist()
                    progressed = True

                if on_rows is not None and table_metrics.get("deleted", 0):
                    on_rows(f"{schema}.{table}", table_metrics["deleted"])

            worklist = deferred
            if worklist and not progressed:
                # Every remaining table is blocked and none moved: retrying
                # cannot help, so stop rather than spin to MAX_PASSES.
                error = (
                    f"{step_key}: FK-blocked tables could not be resolved after "
                    f"pass {pass_no}: {worklist}"
                )
                log(f"    STUCK — {error}")
                return False, error

        if worklist:
            error = f"{step_key}: still FK-blocked after {MAX_PASSES} passes: {worklist}"
            log(f"    STUCK — {error}")
            return False, error

        metrics[step_key]["_step_seconds"] = round(time.time() - step_started, 3)
        persist()

    return True, None


# --------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------


def audit(
    pool, steps, schema_for: dict[str, str], scoper, metrics: dict, dry_run: bool, log: Log
) -> tuple[list[dict], bool | None]:
    """
    Verify that only the intended rows were removed. Read-only.

    Three checks per processed table: no in-scope rows remain, every delete was
    backed up, and the table's total fell by exactly the number deleted — the
    last being what catches rows lost to an unexpected cascade.

    Returns ``(findings, clean)``; ``clean`` is ``None`` after a dry run, which
    the report shows as "not performed" rather than as a pass.
    """
    findings: list[dict] = []
    if dry_run:
        log("\n  === AUDIT === (skipped in dry-run)")
        return findings, None

    log("\n  === AUDIT — verifying only intended rows were deleted ===")
    for step_key, db_key, kind, _tables in steps:
        conn = pool.get(db_key)
        conn.rollback()
        schema = schema_for[kind]

        for table, table_metrics in metrics.get(step_key, {}).items():
            if table == "_step_seconds":
                continue
            if table_metrics.get("status") in ("skipped", "empty", "unscoped"):
                continue

            issues: list[str] = []

            try:
                predicate = scoper.predicate(conn, schema, table, kind)
                conn.rollback()
                if predicate is not None:
                    where, params = predicate
                    remaining = count_where(conn, schema, table, where, params)
                    if remaining != 0:
                        issues.append(f"{remaining} in-scope row(s) still present")
            except Exception as exc:  # noqa: BLE001 — reported as a finding
                conn.rollback()
                issues.append(f"scope recheck error: {str(exc).strip()[:80]}")

            if table_metrics.get("backed_up", 0) != table_metrics.get("deleted", 0):
                issues.append(
                    f"backed_up {table_metrics.get('backed_up')} "
                    f"!= deleted {table_metrics.get('deleted')}"
                )

            total_before = table_metrics.get("total_before")
            total_after = table_metrics.get("total_after")
            deleted = table_metrics.get("deleted", 0)
            if (
                total_before is not None
                and total_after is not None
                and total_after != total_before - deleted
            ):
                issues.append(
                    f"collateral: total {total_before}->{total_after} "
                    f"but only {deleted} deleted"
                )

            if issues:
                findings.append({"step": step_key, "table": table, "issues": issues})
                log(f"    {table}: " + "; ".join(issues))

    if findings:
        log(f"  AUDIT FOUND {len(findings)} issue(s)")
    else:
        log("  audit clean — no residual rows, backups match deletes, no collateral")
    return findings, not findings
