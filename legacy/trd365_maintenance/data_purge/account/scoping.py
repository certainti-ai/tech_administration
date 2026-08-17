"""
Account scoping — resolve an account, capture its id-sets, and build the
per-table WHERE predicate that selects exactly the rows belonging to it.

Faithful to the vendor's SECTION-1 resolution and SECTION-2/3/7 scoping, ported
from the account_deletion engine.  The generic purge engine (engine/core.py)
drives an ``AccountScoper`` instance via ``.predicate()`` / ``.discover()``.
"""

from engine import core
from engine.core import _q, table_exists, columns, single_col_fks
from . import manifest as M


# ---------------------------------------------------------------------------
# resolution (SECTION 1)
# ---------------------------------------------------------------------------

def resolve_account(pool, rid):
    """Return dict: r_number, org_schema, storage_type, parent_rid, exists."""
    m = pool.get("maindb")
    with m.cursor() as cur:
        cur.execute("SELECT r_number, storage_type, parent_account_rid "
                    "FROM trd365.account WHERE rid=%s", (rid,))
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
    return {"rid": rid, "exists": True, "r_number": r_number, "storage_type": storage_type,
            "parent_rid": parent_rid, "org_schema": org_schema}


# ---------------------------------------------------------------------------
# id-set capture (before any deletion) — scopes tables lacking account_rid,
# and (critically) the fiscal set used to reach trd365ai after org is deleted.
# ---------------------------------------------------------------------------

def capture_id_sets(pool, acct):
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
    if table_exists(o, sch, "interactions") and "account_rid" in columns(o, sch, "interactions"):
        sets["interactions"] = rids("interactions", "account_rid=%s", (rid,))
    else:
        sets["interactions"] = rids("interactions", "project_fiscal_rid = ANY(%s)", (sets["project_fiscal"],))
    sets["project_task"] = (rids("project_task", "project_fiscal_rid = ANY(%s)", (sets["project_fiscal"],))
                            if table_exists(o, sch, "project_task") else [])
    sets["checklists"] = (rids("checklists", "case_rid = ANY(%s)", (sets["cases"],))
                          if table_exists(o, sch, "checklists") else [])
    o.rollback()
    return sets


# ---------------------------------------------------------------------------
# special predicates — vendor scopes these via a parent link, not account_rid
# ---------------------------------------------------------------------------

def _sp_attach(parent):
    def f(conn, schema, rid, sets):
        if not table_exists(conn, schema, parent):
            return "1=0", []
        return (f'attach_to IN (SELECT rid FROM {_q(schema)}.{_q(parent)} WHERE account_rid = %s)', [rid])
    return f


def _sp_user_group_entity_access(conn, schema, rid, sets):
    return (f'entity_rid IN (SELECT rid FROM {_q(schema)}.project_fiscal_summary WHERE account_rid=%s) '
            f'OR entity_rid IN (SELECT project_rid FROM {_q(schema)}.project_summary WHERE account_rid=%s)',
            [rid, rid])


def _sp_chat_child(conn, schema, rid, sets):
    if not table_exists(conn, schema, "chat_sessions"):
        return "1=0", []
    return (f'session_rid IN (SELECT session_rid FROM {_q(schema)}.chat_sessions WHERE account_rid = %s)', [rid])


def _sp_key_contact_details(conn, schema, rid, sets):
    if table_exists(conn, schema, "project"):
        return (f'entity_rid IN (SELECT rid FROM {_q(schema)}.project WHERE account_rid = %s) OR entity_rid = %s',
                [rid, rid])
    return "entity_rid = %s", [rid]


def _sp_kafka_events(conn, schema, rid, sets):
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
    "account_timeline_old": lambda conn, schema, rid, sets: ("attach_to = %s", [rid]),
    "user_group_entity_access": _sp_user_group_entity_access,
    "account": lambda conn, schema, rid, sets: ("rid = %s", [rid]),
    "key_contact_details": _sp_key_contact_details,
    "kafka_events": _sp_kafka_events,
    "chat_answers": _sp_chat_child, "chat_attachments": _sp_chat_child,
    "chat_audit_log": _sp_chat_child, "chat_branches": _sp_chat_child,
    "chat_messages": _sp_chat_child, "chat_questions": _sp_chat_child,
}

# Unambiguous *_rid columns -> candidate parent table(s). project_rid omitted
# (ambiguous: references project OR project_fiscal depending on table).
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
# discovery of account-scoped tables missing from the static manifest
# ---------------------------------------------------------------------------

def _account_scopable_tables(conn, schema):
    with conn.cursor() as cur:
        cur.execute("""
            WITH acct AS (
              SELECT table_name FROM information_schema.columns
              WHERE table_schema=%s AND column_name='account_rid'
            )
            SELECT DISTINCT t.relname FROM pg_class t
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname=%s AND t.relkind='r'
              AND ( t.relname IN (SELECT table_name FROM acct)
                    OR EXISTS (SELECT 1 FROM pg_constraint c
                               JOIN pg_class rt ON rt.oid = c.confrelid
                               WHERE c.conrelid = t.oid AND c.contype='f'
                                 AND rt.relname IN (SELECT table_name FROM acct)))""",
                    (schema, schema))
        return {r[0] for r in cur.fetchall()}


def _fk_children_with_account_rid(conn, schema, parent):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT t.relname FROM pg_constraint c
            JOIN pg_class t  ON t.oid = c.conrelid
            JOIN pg_class rt ON rt.oid = c.confrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname=%s AND c.contype='f' AND rt.relname=%s""", (schema, parent))
        kids = {r[0] for r in cur.fetchall()}
    return {k for k in kids if "account_rid" in columns(conn, schema, k)}


# ---------------------------------------------------------------------------
# the Scoper the engine drives
# ---------------------------------------------------------------------------

class AccountScoper:
    def __init__(self, acct, sets):
        self.acct = acct
        self.sets = sets
        self.rid = acct["rid"]

    def discover(self, conn, schema, kind, manifest_tables):
        known = set(manifest_tables) | set(SPECIAL_PREDICATES)
        if kind == "org":
            found = _account_scopable_tables(conn, schema)
        elif kind == "main":
            found = _fk_children_with_account_rid(conn, schema, "account")
        else:
            return []
        return sorted(found - known)

    def predicate(self, conn, schema, table, kind):
        """(where, params) scoping `table` to this account, or None if unscopable."""
        rid = self.rid
        if table in SPECIAL_PREDICATES:
            return SPECIAL_PREDICATES[table](conn, schema, rid, self.sets)

        cols = columns(conn, schema, table)

        if kind == "ai":
            # trd365ai has no link back to org — scope by the captured fiscal set.
            for c in ("projectId", "projectid", "project_fiscal_rid"):
                if c in cols:
                    return f'{_q(c)} = ANY(%s)', [self.sets["project_fiscal"]]
            return None

        conds, params = [], []
        if "account_rid" in cols:
            conds.append("account_rid = %s")
            params.append(rid)
        for local_col, ref_table, ref_col in single_col_fks(conn, schema, table):
            if not local_col or not ref_col or ref_table == table:
                continue
            if "account_rid" in columns(conn, schema, ref_table):
                conds.append(f'{_q(local_col)} IN (SELECT {_q(ref_col)} FROM '
                             f'{_q(schema)}.{_q(ref_table)} WHERE account_rid = %s)')
                params.append(rid)

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


SCHEMA_FOR = {"main": M.MAIN_SCHEMA, "ai": M.AI_SCHEMA}  # 'org' filled in per-account
