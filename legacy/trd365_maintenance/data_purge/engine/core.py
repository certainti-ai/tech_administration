"""
Generic id-based purge engine (shared by every data_purge sub-module).

An entity purge (account / resource / project / project_fiscal / case /
interaction) is expressed as a list of STEPS — one per database — each a
child-before-parent ordered list of tables.  The engine, given a per-table
*scope predicate* that selects the rows belonging to the target entity, runs the
same five phases for every sub-module:

    1. ANALYSE  — resolve scope predicate per table, count impacted rows
                  (read-only; this is also the dry-run).
    2. BACKUP   — copy impacted rows into the shared ``data_purge`` schema
                  (``data_purge.bak_<table>``) of the SAME database, tagged with
                  run id / entity / entity_rid / timestamp.
    3. DELETE   — delete the impacted rows in small committed chunks, backup and
                  delete in the SAME transaction so a backup row exists iff the
                  source row was removed.  Children are deleted before parents
                  (manifest order); any table still FK-blocked is deferred and
                  retried (multi-pass) until the ordering constraints are met.
    4. AUDIT    — re-check every processed table: in-scope rows remaining == 0,
                  rows_backed_up == rows_deleted, and
                  total_after == total_before - deleted  (no collateral rows lost
                  to an unexpected cascade).  Any deviation is flagged.
    5. REPORT   — see report.py.

Backups always land in the same DB as their source table, so the ``data_purge``
schema is created (if absent) in each of the three databases as needed.

This module is entity-agnostic: the sub-module supplies STEPS, a ``schema_for``
map, and a ``Scoper`` (predicate + optional extra-table discovery).  Nothing here
knows what an "account" or a "case" is.
"""

import time

import psycopg2

BACKUP_SCHEMA = "data_purge"

# audit columns appended to every data_purge.bak_<table>
AUDIT_COLS = [
    ("_purge_run_at", "timestamptz"),
    ("_purge_run_id", "text"),
    ("_purge_entity", "text"),
    ("_purge_entity_rid", "text"),
]


# ---------------------------------------------------------------------------
# small SQL helpers
# ---------------------------------------------------------------------------

def _q(ident):
    return '"' + ident.replace('"', '""') + '"'


def table_exists(conn, schema, table):
    with conn.cursor() as cur:
        cur.execute("""SELECT 1 FROM information_schema.tables
                       WHERE table_schema=%s AND table_name=%s""", (schema, table))
        return cur.fetchone() is not None


_COLS_CACHE = {}
_FK_CACHE = {}


def columns(conn, schema, table):
    key = (schema, table)
    if key not in _COLS_CACHE:
        with conn.cursor() as cur:
            cur.execute("""SELECT column_name FROM information_schema.columns
                           WHERE table_schema=%s AND table_name=%s""", (schema, table))
            _COLS_CACHE[key] = {r[0] for r in cur.fetchall()}
    return _COLS_CACHE[key]


def single_col_fks(conn, schema, table):
    """Single-column FKs of `table`: list of (local_col, ref_table, ref_col)."""
    key = (schema, table)
    if key not in _FK_CACHE:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT (SELECT attname FROM pg_attribute WHERE attrelid=c.conrelid AND attnum=c.conkey[1]),
                       rt.relname,
                       (SELECT attname FROM pg_attribute WHERE attrelid=c.confrelid AND attnum=c.confkey[1])
                FROM pg_constraint c
                JOIN pg_class t  ON t.oid = c.conrelid
                JOIN pg_class rt ON rt.oid = c.confrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname=%s AND t.relname=%s AND c.contype='f'
                  AND array_length(c.conkey, 1) = 1""", (schema, table))
            _FK_CACHE[key] = cur.fetchall()
    return _FK_CACHE[key]


def clear_caches():
    _COLS_CACHE.clear()
    _FK_CACHE.clear()


def count_where(conn, schema, table, where, params):
    with conn.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM {_q(schema)}.{_q(table)} WHERE {where}', params)
        return cur.fetchone()[0]


def count_all(conn, schema, table):
    with conn.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM {_q(schema)}.{_q(table)}')
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# backup target
# ---------------------------------------------------------------------------

def ensure_backup_table(conn, bak_schema, schema, table):
    """Create data_purge.bak_<table> (LIKE source) + audit columns, if absent."""
    bakt = f"bak_{table}"[:63]
    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS {_q(bak_schema)}')
        cur.execute(f'CREATE TABLE IF NOT EXISTS {_q(bak_schema)}.{_q(bakt)} '
                    f'(LIKE {_q(schema)}.{_q(table)} INCLUDING DEFAULTS)')
        add = ", ".join(f'ADD COLUMN IF NOT EXISTS {_q(c)} {t}' for c, t in AUDIT_COLS)
        cur.execute(f'ALTER TABLE {_q(bak_schema)}.{_q(bakt)} {add}')
    conn.commit()
    return bakt


# ---------------------------------------------------------------------------
# chunked backup + delete for one table
# ---------------------------------------------------------------------------

def process_table(conn, schema, table, where, params, tag, bak_schema,
                  chunk_size, dry_run, log):
    """Back up + delete the in-scope rows of one table in committed chunks.

    `tag` = (run_at, run_id, entity, entity_rid) appended to each backup row.
    Returns a metrics dict. FK violations set status 'fk_blocked' (deferred by
    the caller for a later pass), after rolling the offending batch back.
    """
    t0 = time.time()
    m = {"table": table, "schema": schema, "status": "ok",
         "scope_before": 0, "total_before": 0, "deleted": 0, "backed_up": 0,
         "batches": 0, "scope_after": 0, "total_after": 0, "seconds": 0.0, "note": ""}

    if not table_exists(conn, schema, table):
        m["status"] = "skipped"; m["note"] = "table not present"
        m["seconds"] = round(time.time() - t0, 3)
        log(f"    {table}: skip (not present)")
        return m

    before = count_where(conn, schema, table, where, params)
    m["scope_before"] = before
    m["total_before"] = count_all(conn, schema, table)
    if before == 0:
        m["status"] = "empty"; m["total_after"] = m["total_before"]
        m["seconds"] = round(time.time() - t0, 3)
        log(f"    {table}: 0 rows in scope")
        return m

    if dry_run:
        m["status"] = "dry-run"; m["seconds"] = round(time.time() - t0, 3)
        log(f"    {table}: would back up + delete {before} of {m['total_before']} row(s)")
        return m

    bakt = ensure_backup_table(conn, bak_schema, schema, table)
    run_at, run_id, entity, entity_rid = tag
    deleted = backed = batches = 0
    fk_blocked = False
    while True:
        with conn.cursor() as cur:
            cur.execute(f'SELECT ctid FROM {_q(schema)}.{_q(table)} WHERE {where} LIMIT {chunk_size}', params)
            ctids = [r[0] for r in cur.fetchall()]
        if not ctids:
            break
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f'INSERT INTO {_q(bak_schema)}.{_q(bakt)} '
                    f'SELECT t.*, %s, %s, %s, %s FROM {_q(schema)}.{_q(table)} t '
                    f'WHERE t.ctid = ANY(%s::tid[])',
                    [run_at, run_id, entity, entity_rid, ctids])
                bk = cur.rowcount
                cur.execute(f'DELETE FROM {_q(schema)}.{_q(table)} WHERE ctid = ANY(%s::tid[])', [ctids])
                dl = cur.rowcount
            conn.commit()
        except psycopg2.Error as exc:
            conn.rollback()
            if getattr(exc, "pgcode", None) == "23503":   # foreign_key_violation
                fk_blocked = True
                m["note"] = "FK-blocked (deferred): " + str(exc).strip().splitlines()[0]
                break
            raise
        backed += bk
        deleted += dl
        batches += 1
        if batches % 10 == 0:
            log(f"      {table}: {deleted}/{before} deleted ({batches} batches)")

    m.update({"deleted": deleted, "backed_up": backed, "batches": batches,
              "scope_after": count_where(conn, schema, table, where, params),
              "total_after": count_all(conn, schema, table),
              "seconds": round(time.time() - t0, 3)})
    if fk_blocked:
        m["status"] = "fk_blocked"
        log(f"    {table}: FK-blocked after {deleted} row(s) — deferring for retry")
    else:
        log(f"    {table}: deleted {deleted} (backed up {backed}) in {batches} batch(es), "
            f"{m['seconds']}s, remaining {m['scope_after']}")
    return m


# ---------------------------------------------------------------------------
# multi-pass orchestration across steps / databases
# ---------------------------------------------------------------------------

MAX_PASSES = 25


def run_steps(pool, steps, schema_for, scoper, tag, bak_schema,
              chunk_size, dry_run, log, metrics, completed, persist):
    """Execute every STEP (one DB each) in order, children-before-parents, with
    FK-blocked tables deferred and retried.  Mutates `metrics`/`completed` and
    calls persist() after each table so a killed run resumes cleanly.

    scoper.predicate(conn, schema, table, kind) -> (where, params) | None
    scoper.discover(conn, schema, kind, tables) -> [extra tables]  (optional)

    Returns (ok: bool, last_error: str|None).
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
        step_t0 = time.time()

        worklist = [t for t in tables if t not in done]
        pass_no = 0
        while worklist and pass_no < MAX_PASSES:
            pass_no += 1
            if pass_no > 1:
                log(f"  --- retry pass {pass_no}: {len(worklist)} deferred table(s) ---")
            deferred, progressed = [], False
            for table in worklist:
                try:
                    conn.rollback()
                    pred = scoper.predicate(conn, schema, table, kind)
                    if pred is None:
                        m = {"table": table, "schema": schema, "status": "unscoped",
                             "scope_before": 0, "deleted": 0, "backed_up": 0, "batches": 0,
                             "scope_after": 0, "seconds": 0.0,
                             "note": "no scope column; NOT touched"}
                        log(f"    {table}: UNSCOPED — left untouched (needs manual review)")
                    else:
                        where, params = pred
                        m = process_table(conn, schema, table, where, params, tag,
                                           bak_schema, chunk_size, dry_run, log)
                except Exception as exc:
                    conn.rollback()
                    err = f"{step_key}/{table}: {str(exc).strip()}"
                    log(f"    ERROR on {table}: {err}")
                    return False, err
                metrics[step_key][table] = m
                if m["status"] == "fk_blocked":
                    deferred.append(table)
                    if m.get("deleted", 0) > 0:
                        progressed = True
                else:
                    if not dry_run:
                        done.add(table)
                        completed[step_key] = sorted(done)
                        persist()
                    progressed = True
            worklist = deferred
            if worklist and not progressed:
                err = (f"{step_key}: FK-blocked tables could not be resolved after "
                       f"pass {pass_no}: {worklist}")
                log(f"    STUCK — {err}")
                return False, err
        metrics[step_key]["_step_seconds"] = round(time.time() - step_t0, 3)
        persist()
    return True, None


# ---------------------------------------------------------------------------
# AUDIT — verify ONLY the intended rows were removed
# ---------------------------------------------------------------------------

def audit(pool, steps, schema_for, scoper, metrics, dry_run, log):
    """Post-delete verification. For every processed table confirm:
        - in-scope rows remaining == 0            (all intended rows gone)
        - rows_backed_up == rows_deleted          (every delete was backed up)
        - total_after == total_before - deleted   (no collateral rows removed)
    Returns (findings: list[dict], clean: bool). Read-only.
    """
    findings = []
    if dry_run:
        log("\n  === AUDIT === (skipped in dry-run)")
        return findings, None  # None => report shows "not performed", not "clean"

    log("\n  === AUDIT — verifying only intended rows were deleted ===")
    for step_key, db_key, kind, _tables in steps:
        conn = pool.get(db_key)
        conn.rollback()
        schema = schema_for[kind]
        tm = metrics.get(step_key, {})
        for table, m in tm.items():
            if table == "_step_seconds" or m.get("status") in ("skipped", "empty", "unscoped"):
                continue
            issues = []
            # 1. residual in-scope rows
            try:
                pred = scoper.predicate(conn, schema, table, kind)
                conn.rollback()
                if pred is not None:
                    where, params = pred
                    remaining = count_where(conn, schema, table, where, params)
                    if remaining != 0:
                        issues.append(f"{remaining} in-scope row(s) still present")
            except Exception as exc:
                conn.rollback()
                issues.append(f"scope recheck error: {str(exc).strip()[:80]}")
            # 2. backup integrity
            if m.get("backed_up", 0) != m.get("deleted", 0):
                issues.append(f"backed_up {m.get('backed_up')} != deleted {m.get('deleted')}")
            # 3. collateral: total must drop by exactly `deleted`
            tb, ta, dl = m.get("total_before"), m.get("total_after"), m.get("deleted", 0)
            if tb is not None and ta is not None and ta != tb - dl:
                issues.append(f"collateral: total {tb}->{ta} but only {dl} deleted "
                              f"(expected {tb - dl})")
            if issues:
                findings.append({"step": step_key, "schema": schema, "table": table,
                                 "issues": issues})
                log(f"    ⚠ {table}: " + "; ".join(issues))
    if not findings:
        log("    ✓ audit clean — every processed table: 0 residual, backups match, no collateral")
    return findings, not findings
