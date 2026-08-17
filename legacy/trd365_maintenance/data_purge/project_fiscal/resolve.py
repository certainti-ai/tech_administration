"""
Resolution for project / project-fiscal purges.

Turns human inputs (account id or rid, project rid or code) into the exact
parameters the vendor SECTION SQL needs per fiscal:
    schema_name, account_rid, project_rid, project_fiscal_id, fiscal_year,
    is_last_fiscal.

All lookups go through the MAIN account table (to resolve the tenant schema, incl.
store_in_parent) and then the tenant ORG schema's project / project_fiscal tables.
"""


def _q(ident):
    return '"' + ident.replace('"', '""') + '"'


def _one(conn, sql, params):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.rollback()
    return row


def _all(conn, sql, params):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    conn.rollback()
    return rows


def resolve_account(pool, account_ref):
    """account_ref = account_rid (P001-…/D001-…) OR r_number (ACC-…).
    Returns {account_rid, r_number, storage_type, org_schema, exists}."""
    m = pool.get("maindb")
    if account_ref.upper().startswith("ACC-") or not account_ref.upper().startswith(("P001-", "D001-")):
        row = _one(m, "SELECT rid, r_number, storage_type, parent_account_rid "
                      "FROM trd365.account WHERE r_number=%s", (account_ref,))
    else:
        row = _one(m, "SELECT rid, r_number, storage_type, parent_account_rid "
                      "FROM trd365.account WHERE rid=%s", (account_ref,))
    if not row:
        return {"exists": False, "ref": account_ref}
    rid, r_number, storage_type, parent_rid = row
    eff_r = r_number
    if storage_type == "store_in_parent" and parent_rid:
        pr = _one(m, "SELECT r_number FROM trd365.account WHERE rid=%s", (parent_rid,))
        if pr:
            eff_r = pr[0]
    org_schema = "trd365_" + (eff_r or "").replace("ACC-", "")
    return {"exists": True, "account_rid": rid, "r_number": r_number,
            "storage_type": storage_type, "org_schema": org_schema}


def _project_code_col(conn, schema):
    cols = {r[0] for r in _all(conn,
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s "
        "AND table_name='project'", (schema,))}
    for c in ("project_code", "code", "project_id", "project_number", "name"):
        if c in cols:
            return c
    return None


def resolve_project(pool, schema, project_ref):
    """project_ref = project_rid OR a project code/name. Returns project_rid or None."""
    o = pool.get("orgdb")
    if project_ref.upper().startswith(("P001-", "D001-")):
        row = _one(o, f'SELECT rid FROM {_q(schema)}.project WHERE rid=%s', (project_ref,))
        return row[0] if row else None
    code_col = _project_code_col(o, schema)
    if not code_col:
        return None
    row = _one(o, f'SELECT rid FROM {_q(schema)}.project WHERE {_q(code_col)}=%s', (project_ref,))
    return row[0] if row else None


def project_fiscals(pool, schema, project_rid):
    """Ordered list of {project_fiscal_id, fiscal_year} for a project (asc year)."""
    o = pool.get("orgdb")
    cols = {r[0] for r in _all(o,
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s "
        "AND table_name='project_fiscal'", (schema,))}
    yr = "fiscal_year" if "fiscal_year" in cols else None
    sel = f"rid, {_q(yr)}" if yr else "rid, NULL"
    rows = _all(o, f'SELECT {sel} FROM {_q(schema)}.project_fiscal WHERE project_rid=%s '
                   f'ORDER BY {("2" if yr else "1")} NULLS LAST, rid', (project_rid,))
    return [{"project_fiscal_id": r[0], "fiscal_year": r[1]} for r in rows]


def resolve_fiscal(pool, schema, project_fiscal_id):
    """Return {project_rid, fiscal_year, account_rid} for one fiscal, or None."""
    o = pool.get("orgdb")
    cols = {r[0] for r in _all(o,
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s "
        "AND table_name='project_fiscal'", (schema,))}
    yr = "fiscal_year" if "fiscal_year" in cols else "NULL"
    ar = "account_rid" if "account_rid" in cols else "NULL"
    row = _one(o, f'SELECT project_rid, {(_q(yr) if yr!="NULL" else "NULL")}, '
                  f'{(_q(ar) if ar!="NULL" else "NULL")} '
                  f'FROM {_q(schema)}.project_fiscal WHERE rid=%s', (project_fiscal_id,))
    if not row:
        return None
    return {"project_rid": row[0], "fiscal_year": row[1], "account_rid": row[2]}


def build_fiscal_rows(account, project_rid, fiscals):
    """Build the per-fiscal input rows (as the vendor runner expects), marking the
    FINAL fiscal as is_last_fiscal=TRUE (its deletion triggers the project-level
    cascade + account recompute). Deleting a whole project deletes ALL its fiscals,
    so the last one processed is genuinely the last remaining."""
    rows = []
    n = len(fiscals)
    for i, f in enumerate(fiscals):
        rows.append({
            "schema_name": account["org_schema"],
            "account_rid": account["account_rid"],
            "project_rid": project_rid,
            "project_fiscal_id": f["project_fiscal_id"],
            "fiscal_year": f["fiscal_year"] if f["fiscal_year"] is not None else "",
            "is_last_fiscal": (i == n - 1),
        })
    return rows
