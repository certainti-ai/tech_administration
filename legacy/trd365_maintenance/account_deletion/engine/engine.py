"""
Core deletion engine: account resolution, id-set capture, and chunked
backup+delete with intermediate commits, checkpointing, and metrics.

Design notes
------------
* Faithful to the vendor SECTION order (see deletion_manifest.py) so foreign
  keys are satisfied (children deleted before parents).
* Each table is processed by scope predicate at ACCOUNT level, but deleted in
  CHUNKS of `chunk_size` rows, each batch backed up then deleted then COMMITTED.
  -> intermediate commits, small transactions, low lock footprint.
* Resumable: a per-account checkpoint records completed tables. Re-running skips
  completed tables; a table interrupted mid-way is reprocessed but the predicate
  only matches the REMAINING rows, so it deletes/backs-up only what is left.
* Backups: rows are copied into a per-account backup schema (bak_<table>) with
  _backup_run_at / _backup_account_rid audit columns, one batch at a time, in the
  SAME transaction as their delete -> a backup row exists iff the source row was
  removed in that committed batch (no duplicates, even across restarts).
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

from . import deletion_manifest as M


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


def base_tables_with_account_rid(conn, schema):
    """All base tables in `schema` that have an account_rid column."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.table_name
            FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_schema = c.table_schema AND t.table_name = c.table_name
             AND t.table_type = 'BASE TABLE'
            WHERE c.table_schema = %s AND c.column_name = 'account_rid'""", (schema,))
        return {r[0] for r in cur.fetchall()}


def fk_children_with_account_rid(conn, schema, parent):
    """Base tables that FK-reference `parent` and have an account_rid column."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT t.relname
            FROM pg_constraint c
            JOIN pg_class t  ON t.oid = c.conrelid
            JOIN pg_class rt ON rt.oid = c.confrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = %s AND c.contype = 'f' AND rt.relname = %s""", (schema, parent))
        kids = {r[0] for r in cur.fetchall()}
    return {k for k in kids if "account_rid" in columns(conn, schema, k)}


def account_scopable_tables(conn, schema):
    """Base tables that can be scoped to an account: they have account_rid, OR
    they FK-reference a table that has account_rid (so build_predicate can scope
    them via that FK). Catches newer/renamed tables missing from the manifest."""
    with conn.cursor() as cur:
        cur.execute("""
            WITH acct AS (
              SELECT table_name FROM information_schema.columns
              WHERE table_schema=%s AND column_name='account_rid'
            )
            SELECT DISTINCT t.relname
            FROM pg_class t
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname=%s AND t.relkind='r'
              AND ( t.relname IN (SELECT table_name FROM acct)
                    OR EXISTS (
                      SELECT 1 FROM pg_constraint c
                      JOIN pg_class rt ON rt.oid = c.confrelid
                      WHERE c.conrelid = t.oid AND c.contype='f'
                        AND rt.relname IN (SELECT table_name FROM acct)))""",
                    (schema, schema))
        return {r[0] for r in cur.fetchall()}


def discover_extra_tables(conn, schema, kind, manifest_tables):
    """Tables to process that the static manifest missed (schema drift / newer
    releases). ORG (per-tenant schema): every account-scopable table. MAIN
    (shared): only account_rid tables that FK-reference the account record
    (enough to unblock its deletion, without over-reaching in the shared schema)."""
    known = set(manifest_tables) | set(SPECIAL_PREDICATES)
    if kind == "org":
        found = account_scopable_tables(conn, schema)
    elif kind == "main":
        found = fk_children_with_account_rid(conn, schema, "account")
    else:
        return []
    return sorted(found - known)


def count_where(conn, schema, table, where, params):
    with conn.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM {_q(schema)}.{_q(table)} WHERE {where}', params)
        return cur.fetchone()[0]


def count_all(conn, schema, table):
    with conn.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM {_q(schema)}.{_q(table)}')
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# account resolution (SECTION 1 logic)
# ---------------------------------------------------------------------------

def resolve_account(pool, rid):
    """Return dict with r_number, org_schema, storage_type, parent_rid, exists."""
    m = pool.get("maindb")
    with m.cursor() as cur:
        cur.execute("SELECT r_number, storage_type, parent_account_rid FROM trd365.account WHERE rid=%s", (rid,))
        row = cur.fetchone()
    m.rollback()
    if not row:
        return {"rid": rid, "exists": False}
    r_number, storage_type, parent_rid = row
    eff_r = r_number
    if storage_type == "store_in_parent" and parent_rid:
        with m.cursor() as cur:
            cur.execute("SELECT r_number FROM trd365.account WHERE rid=%s", (parent_rid,))
            pr = cur.fetchone()
        m.rollback()
        if pr:
            eff_r = pr[0]
    org_schema = "trd365_" + (eff_r or "").replace("ACC-", "")
    return {
        "rid": rid, "exists": True, "r_number": r_number, "storage_type": storage_type,
        "parent_rid": parent_rid, "org_schema": org_schema,
    }


def backup_schema_name(acct):
    r = (acct.get("r_number") or acct["rid"]).lower()
    safe = "".join(c if c.isalnum() else "_" for c in r).strip("_")
    return f"del_backup_{safe}"[:63]


# ---------------------------------------------------------------------------
# id-set capture (before any deletion) — used to scope tables lacking account_rid
# ---------------------------------------------------------------------------

# hub table -> how to select its rids for this account
def capture_id_sets(pool, acct):
    """Capture parent id-sets from the ORG schema before deletion (persisted in
    checkpoint). Also captures the fiscal set used to scope trd365ai."""
    o = pool.get("orgdb")
    sch = acct["org_schema"]
    rid = acct["rid"]
    sets = {}

    def rids(table, where, params):
        if not table_exists(o, sch, table):
            return []
        with o.cursor() as cur:
            cur.execute(f'SELECT rid FROM {_q(sch)}.{_q(table)} WHERE {where}', params)
            return [r[0] for r in cur.fetchall()]

    sets["cases"] = rids("cases", "account_rid=%s", (rid,))
    sets["project"] = rids("project", "account_rid=%s", (rid,))
    sets["project_fiscal"] = rids("project_fiscal", "account_rid=%s", (rid,))
    sets["resources"] = rids("resources", "account_rid=%s", (rid,))
    # interactions: prefer account_rid, else via fiscal
    if table_exists(o, sch, "interactions") and "account_rid" in columns(o, sch, "interactions"):
        sets["interactions"] = rids("interactions", "account_rid=%s", (rid,))
    else:
        sets["interactions"] = rids("interactions", "project_fiscal_rid = ANY(%s)", (sets["project_fiscal"],))
    # project_task: via fiscal
    sets["project_task"] = rids("project_task", "project_fiscal_rid = ANY(%s)", (sets["project_fiscal"],)) \
        if table_exists(o, sch, "project_task") else []
    # checklists: via cases
    sets["checklists"] = rids("checklists", "case_rid = ANY(%s)", (sets["cases"],)) \
        if table_exists(o, sch, "checklists") else []
    o.rollback()
    return sets


# ---------------------------------------------------------------------------
# predicate builder (FK-aware account scoping)
# ---------------------------------------------------------------------------

# Tables that the vendor scopes via a parent link rather than a direct
# account column. Each entry returns (where_sql, params) and does its own
# existence guard (returns a no-match predicate if the parent is absent).
def _sp_attach(parent):
    def f(conn, schema, rid):
        if not table_exists(conn, schema, parent):
            return "1=0", []
        return (f'attach_to IN (SELECT rid FROM {_q(schema)}.{_q(parent)} WHERE account_rid = %s)', [rid])
    return f


def _sp_user_group_entity_access(conn, schema, rid):
    return (f'entity_rid IN (SELECT rid FROM {_q(schema)}.project_fiscal_summary WHERE account_rid=%s) '
            f'OR entity_rid IN (SELECT project_rid FROM {_q(schema)}.project_summary WHERE account_rid=%s)',
            [rid, rid])


def _sp_chat_child(conn, schema, rid):
    if not table_exists(conn, schema, "chat_sessions"):
        return "1=0", []
    return (f'session_rid IN (SELECT session_rid FROM {_q(schema)}.chat_sessions WHERE account_rid = %s)', [rid])


def _sp_key_contact_details(conn, schema, rid):
    if table_exists(conn, schema, "project"):
        return (f'entity_rid IN (SELECT rid FROM {_q(schema)}.project WHERE account_rid = %s) OR entity_rid = %s',
                [rid, rid])
    return "entity_rid = %s", [rid]


def _sp_kafka_events(conn, schema, rid):
    if not table_exists(conn, schema, "document"):
        return "1=0", []
    sql = f'document_rid IN (SELECT rid FROM {_q(schema)}.document WHERE account_rid = %s)'
    params = [rid]
    if table_exists(conn, schema, "import"):
        sql += (f' OR document_upload_rid IN (SELECT i.rid FROM {_q(schema)}.import i '
                f'JOIN {_q(schema)}.document d ON i.document_rid = d.rid WHERE d.account_rid = %s)')
        params.append(rid)
    return sql, params


SPECIAL_PREDICATES = {
    "attachment_timeline": _sp_attach("attachments"),
    "notes_timeline": _sp_attach("notes"),
    "account_timeline_old": lambda conn, schema, rid: ("attach_to = %s", [rid]),
    "user_group_entity_access": _sp_user_group_entity_access,
    "account": lambda conn, schema, rid: ("rid = %s", [rid]),
    "key_contact_details": _sp_key_contact_details,
    "kafka_events": _sp_kafka_events,
    "chat_answers": _sp_chat_child,
    "chat_attachments": _sp_chat_child,
    "chat_audit_log": _sp_chat_child,
    "chat_branches": _sp_chat_child,
    "chat_messages": _sp_chat_child,
    "chat_questions": _sp_chat_child,
}


def build_predicate(conn, schema, table, acct, sets, kind):
    """Return (where_sql, params) scoping `table` to this account, or None if the
    table can't be scoped (caller flags it as unscoped).

    General rule (org/main): a row belongs to the account if its own account_rid
    matches, OR any of its foreign keys points at a row of an account-scoped
    parent table (one that itself has account_rid). Using the ACTUAL fk target
    — not the column name — is what makes this correct (e.g. project_history's
    project_rid actually references project_fiscal, not project).
    """
    rid = acct["rid"]
    if table in SPECIAL_PREDICATES:
        return SPECIAL_PREDICATES[table](conn, schema, rid)

    cols = columns(conn, schema, table)

    if kind == "ai":
        # trd365ai is a separate DB with no link back to org — scope by the
        # fiscal set captured from the org schema before deletion.
        for c in ("projectId", "projectid", "project_fiscal_rid"):
            if c in cols:
                return f'{_q(c)} = ANY(%s)', [sets["project_fiscal"]]
        return None

    conds, params = [], []
    if "account_rid" in cols:
        conds.append("account_rid = %s")
        params.append(rid)
    for local_col, ref_table, ref_col in single_col_fks(conn, schema, table):
        if not local_col or not ref_col or ref_table == table:
            continue
        # Only scope through parents that are themselves account-scoped.
        if "account_rid" in columns(conn, schema, ref_table):
            conds.append(f'{_q(local_col)} IN (SELECT {_q(ref_col)} FROM '
                         f'{_q(schema)}.{_q(ref_table)} WHERE account_rid = %s)')
            params.append(rid)

    # Fallback for UNAMBIGUOUS link columns that aren't declared as FKs in this
    # schema (schema drift). Only columns whose parent is unambiguous by
    # convention — deliberately excludes project_rid (which can reference
    # project OR project_fiscal). Parent is resolved to a same-schema table that
    # has both rid and account_rid; the redundant-OR is harmless if a FK already
    # covered the column.
    for col, candidates in _FALLBACK_PARENTS.items():
        if col not in cols:
            continue
        for parent in candidates:
            if not table_exists(conn, schema, parent):
                continue
            pcols = columns(conn, schema, parent)
            if "account_rid" in pcols and "rid" in pcols:
                conds.append(f'{_q(col)} IN (SELECT rid FROM {_q(schema)}.{_q(parent)} '
                             f'WHERE account_rid = %s)')
                params.append(rid)
                break

    if not conds:
        return None
    return " OR ".join(conds), params


# Unambiguous *_rid columns -> candidate parent table(s) in the same schema.
# NOTE: project_rid is intentionally omitted (ambiguous parent).
_FALLBACK_PARENTS = {
    "case_rid": ["cases", "case_summary"],
    "interaction_rid": ["interactions", "interactions_summary"],
    "project_fiscal_rid": ["project_fiscal", "project_fiscal_summary"],
    "resource_rid": ["resources"],
    "checklist_rid": ["checklists"],
    "session_rid": ["chat_sessions"],
    "task_rid": ["project_task", "task_summary"],
    "project_task_rid": ["project_task"],
}


# ---------------------------------------------------------------------------
# chunked backup + delete for one table
# ---------------------------------------------------------------------------

def process_table(conn, schema, table, acct, sets, kind, bak_schema, run_at,
                  chunk_size, dry_run, full_counts, log):
    """Returns a metrics dict for this table."""
    t0 = time.time()
    m = {"table": table, "schema": schema, "status": "ok",
         "scope_before": 0, "deleted": 0, "scope_after": 0, "batches": 0,
         "backed_up": 0, "seconds": 0.0, "note": ""}

    if not table_exists(conn, schema, table):
        m["status"] = "skipped"; m["note"] = "table not present"
        m["seconds"] = round(time.time() - t0, 3)
        log(f"    {table}: skip (not present)")
        return m

    pred = build_predicate(conn, schema, table, acct, sets, kind)
    if pred is None:
        m["status"] = "unscoped"; m["note"] = "no account-scope column; NOT touched"
        m["seconds"] = round(time.time() - t0, 3)
        log(f"    {table}: UNSCOPED — left untouched (needs manual review)")
        return m
    where, params = pred

    before = count_where(conn, schema, table, where, params)
    m["scope_before"] = before
    if full_counts:
        m["total_before"] = count_all(conn, schema, table)

    if before == 0:
        m["status"] = "empty"; m["seconds"] = round(time.time() - t0, 3)
        if full_counts:
            m["total_after"] = m.get("total_before")
        log(f"    {table}: 0 rows for account")
        return m

    if dry_run:
        m["status"] = "dry-run"; m["seconds"] = round(time.time() - t0, 3)
        log(f"    {table}: would back up + delete {before} row(s)")
        return m

    # ensure backup schema + table
    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS {_q(bak_schema)}')
        cur.execute(f'CREATE TABLE IF NOT EXISTS {_q(bak_schema)}.{_q("bak_"+table)} '
                    f'(LIKE {_q(schema)}.{_q(table)})')
        cur.execute(f'ALTER TABLE {_q(bak_schema)}.{_q("bak_"+table)} '
                    f'ADD COLUMN IF NOT EXISTS _backup_run_at timestamptz, '
                    f'ADD COLUMN IF NOT EXISTS _backup_account_rid text')
    conn.commit()

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
                    f'INSERT INTO {_q(bak_schema)}.{_q("bak_"+table)} '
                    f'SELECT t.*, %s, %s FROM {_q(schema)}.{_q(table)} t WHERE t.ctid = ANY(%s::tid[])',
                    [run_at, acct["rid"], ctids])
                bk = cur.rowcount
                cur.execute(f'DELETE FROM {_q(schema)}.{_q(table)} WHERE ctid = ANY(%s::tid[])', [ctids])
                dl = cur.rowcount
            conn.commit()
        except psycopg2.Error as exc:
            conn.rollback()  # undo this batch's backup+delete
            if getattr(exc, "pgcode", None) == "23503":   # foreign_key_violation
                fk_blocked = True
                m["note"] = "FK-blocked (deferred for retry): " + str(exc).strip().splitlines()[0]
                break
            raise
        backed += bk
        deleted += dl
        batches += 1
        if batches % 10 == 0:
            log(f"      {table}: {deleted}/{before} deleted ({batches} batches)")

    after = count_where(conn, schema, table, where, params)
    m.update({"deleted": deleted, "backed_up": backed, "batches": batches,
              "scope_after": after, "seconds": round(time.time() - t0, 3)})
    if full_counts:
        m["total_after"] = count_all(conn, schema, table)
    if fk_blocked:
        m["status"] = "fk_blocked"
        log(f"    {table}: FK-blocked after {deleted} row(s) — deferring for retry")
    else:
        log(f"    {table}: deleted {deleted} (backed up {backed}) in {batches} batch(es), "
            f"{m['seconds']}s, remaining {after}")
    return m


# ---------------------------------------------------------------------------
# checkpoint
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc).isoformat()


def load_checkpoint(state_dir, rid):
    p = Path(state_dir) / f"{_safe(rid)}.json"
    if p.exists():
        with open(p) as fh:
            return json.load(fh)
    return None


def save_checkpoint(state_dir, cp):
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    p = Path(state_dir) / f"{_safe(cp['account_rid'])}.json"
    with open(p, "w") as fh:
        json.dump(cp, fh, indent=2, default=str)


def _safe(rid):
    return "".join(c if c.isalnum() else "_" for c in rid)


# ---------------------------------------------------------------------------
# per-account orchestration
# ---------------------------------------------------------------------------

def process_account(pool, acct, state_dir, chunk_size=1000, dry_run=False,
                    full_counts=False, log=print):
    """Run all steps for one account. Returns (checkpoint, ok: bool)."""
    rid = acct["rid"]
    cp = load_checkpoint(state_dir, rid) or {
        "account_rid": rid, "r_number": acct.get("r_number"),
        "org_schema": acct.get("org_schema"), "storage_type": acct.get("storage_type"),
        "backup_schema": backup_schema_name(acct),
        "run_at": _now(), "started_at": _now(),
        "id_sets": None, "completed_tables": {}, "metrics": {}, "status": "in_progress",
        "last_error": None, "dry_run": dry_run,
    }
    cp["status"] = "in_progress"
    bak_schema = cp["backup_schema"]
    run_at = cp["run_at"]

    # Dry-runs are read-only and must NOT leave resumable state (a later live run
    # would otherwise treat it as a resume and reuse stale id-sets).
    def persist():
        if not dry_run:
            save_checkpoint(state_dir, cp)

    # capture id-sets once (persist for resume; critical for AI after org delete)
    if cp.get("id_sets") is None:
        log("  capturing id-sets from org schema (cases/fiscals/projects/resources)…")
        cp["id_sets"] = capture_id_sets(pool, acct)
        persist()
    sets = cp["id_sets"]
    log(f"  fiscals={len(sets.get('project_fiscal', []))} cases={len(sets.get('cases', []))} "
        f"resources={len(sets.get('resources', []))}")

    schema_for = {"org": acct["org_schema"], "main": M.MAIN_SCHEMA, "ai": M.AI_SCHEMA}

    MAX_PASSES = 25
    for step_key, db_key, kind, tables in M.STEPS:
        conn = pool.get(db_key)
        schema = schema_for[kind]
        # Augment the static manifest with account-scoped tables it missed
        # (schema drift / newer releases). Deferral passes handle their ordering.
        conn.rollback()
        extra = discover_extra_tables(conn, schema, kind, tables)
        if extra:
            log(f"  + {len(extra)} account-scoped table(s) not in manifest "
                f"(auto-discovered): {extra}")
            tables = list(tables) + extra
        done = set(cp["completed_tables"].get(step_key, []))
        cp["metrics"].setdefault(step_key, {})
        log(f"\n  === STEP {step_key} ({db_key} / {schema}) — {len(tables)} tables ===")
        step_t0 = time.time()

        worklist = [t for t in tables if t not in done]
        pass_no = 0
        # Multi-pass: FK-blocked tables are deferred and retried after their
        # children are deleted. Converges once ordering constraints are met.
        while worklist and pass_no < MAX_PASSES:
            pass_no += 1
            if pass_no > 1:
                log(f"  --- retry pass {pass_no}: {len(worklist)} deferred table(s) ---")
            deferred = []
            progressed = False
            for table in worklist:
                try:
                    conn.rollback()  # clean tx state
                    m = process_table(conn, schema, table, acct, sets, kind, bak_schema,
                                      run_at, chunk_size, dry_run, full_counts, log)
                except Exception as exc:
                    conn.rollback()
                    cp["last_error"] = f"{step_key}/{table}: {str(exc).strip()}"
                    cp["status"] = "failed"
                    persist()
                    log(f"    ERROR on {table}: {cp['last_error']}")
                    return cp, False
                cp["metrics"][step_key][table] = m
                if m["status"] == "fk_blocked":
                    deferred.append(table)
                    if m.get("deleted", 0) > 0:
                        progressed = True
                else:
                    if not dry_run:
                        done.add(table)
                        cp["completed_tables"][step_key] = sorted(done)
                        persist()
                    progressed = True
            worklist = deferred
            if worklist and not progressed:
                cp["last_error"] = (f"{step_key}: FK-blocked tables could not be resolved "
                                    f"after pass {pass_no}: {worklist}")
                cp["status"] = "failed"
                persist()
                log(f"    STUCK — {cp['last_error']}")
                return cp, False

        cp["metrics"][step_key]["_step_seconds"] = round(time.time() - step_t0, 3)
        persist()

    cp["status"] = "dry-run-complete" if dry_run else "completed"
    cp["finished_at"] = _now()
    persist()
    return cp, True
