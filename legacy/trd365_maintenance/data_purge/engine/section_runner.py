"""Fiscal-year deletion runner core.

Each base_sql/NN_..._SECTIONn.sql is a self-contained PL/pgSQL DO block with a
small block of "FILL IN" variable declarations at the top. This module:

  1. discovers the section files and infers which logical DB each runs on
     (from the ORGDB / MAINDB / TRD365AI token in the filename),
  2. rewrites the fill-in variable literals with a project's values,
  3. executes each DO block in section order, and
  4. captures the backup-schema name SECTION 1 announces (via RAISE NOTICE) so it
     can be injected into every later section — the manual "copy this exact value
     into v_backup_schema in SECTION 2/3/4…" step, automated.

Transactions are controlled by Python (the DO blocks cannot COMMIT themselves):
  * live  -> commit after each section succeeds,
  * dry-run-> never commit; the caller rolls back all connections at project end,
             so within-DB sections still see the earlier (uncommitted) backup
             schema while nothing is ever persisted.
"""

import re
import threading
import time
from pathlib import Path

# ── Section filename token -> logical DB key in db_config.json ────────────────
DB_TOKEN_TO_KEY = {
    "ORGDB": "orgdb",
    "MAINDB": "maindb",
    "TRD365AI": "trd365ai",
}

# ── SQL variable -> input CSV column. TEXT vars are injected as quoted literals.
# Several differently-named variables carry the same project_fiscal id/rid value.
TEXT_VARS = {
    "v_schema_name":               "schema_name",
    "v_account_rid":               "account_rid",
    "v_project_rid":               "project_rid",
    "v_project_fiscal_id":         "project_fiscal_id",
    "v_project_fiscal_rid":        "project_fiscal_id",
    "v_lookup_project_fiscal_id":  "project_fiscal_id",
    "v_lookup_project_fiscal_rid": "project_fiscal_id",
}
INT_VARS = {
    "v_fiscal_year": "fiscal_year",
}
BOOL_VARS = {
    "v_is_last_fiscal": "is_last_fiscal",
}

# SECTION 1 announces the run's backup schema on this line; every later section
# needs the same value pasted into its v_backup_schema declaration.
BACKUP_SCHEMA_RE = re.compile(r"backup schema for this run\s*=\s*([^\s=]+)")


class RunnerError(Exception):
    """A section could not be prepared or executed."""


def to_bool(v):
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y"}


def discover_sections(base_sql_dir):
    """Return the section files ordered by their NN_ prefix, with DB routing."""
    base = Path(base_sql_dir)
    files = sorted(base.glob("*.sql"))
    if not files:
        raise RunnerError(f"No .sql files found in {base}")
    sections = []
    for f in files:
        m = re.search(r"SECTION\s*_?(\d+)", f.name, re.I)
        num = int(m.group(1)) if m else 0
        token = next((t for t in DB_TOKEN_TO_KEY if t in f.name.upper()), None)
        if token is None:
            raise RunnerError(
                f"{f.name}: cannot tell which DB to run on — expected one of "
                f"{', '.join(DB_TOKEN_TO_KEY)} in the filename.")
        sections.append({
            "num": num,
            "file": f,
            "name": f.name,
            "db_key": DB_TOKEN_TO_KEY[token],
        })
    sections.sort(key=lambda s: (s["num"], s["name"]))
    return sections


def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _force_backup_schema(sql, name):
    """Force v_backup_schema to `name` in ANY section, so a whole execution shares
    one backup schema. Handles both forms:
      * declaration (sections 2-8):  v_backup_schema TEXT := '<literal>';
      * SECTION 1's computed assignment:  v_backup_schema := 'backup_release…' || … ;
    Returns (new_sql, count)."""
    lit = _quote(name)
    sql, n1 = re.subn(r"(\bv_backup_schema\s+TEXT\s*:=\s*)'(?:[^']|'')*'",
                      lambda m: m.group(1) + lit, sql)
    sql, n2 = re.subn(r"(\bv_backup_schema\s*:=\s*)'backup_release[^;]*;",
                      lambda m: m.group(1) + lit + ";", sql)
    return sql, n1 + n2


def _sub_literal(sql, var, kind, new_rhs):
    """Replace the RHS of a single-line `var <TYPE> := <literal>;` declaration.

    Returns (new_sql, count).
    """
    if kind == "TEXT":
        pat = re.compile(r"(\b" + re.escape(var) + r"\s+TEXT\s*:=\s*)'(?:[^']|'')*'")
    elif kind == "INT":
        pat = re.compile(r"(\b" + re.escape(var) + r"\s+INT\s*:=\s*)-?\d+")
    elif kind == "BOOLEAN":
        pat = re.compile(r"(\b" + re.escape(var) + r"\s+BOOLEAN\s*:=\s*)(?:TRUE|FALSE)", re.I)
    else:
        raise ValueError(kind)
    return pat.subn(lambda m: m.group(1) + new_rhs, sql)


def prepare_sql(section, params, backup_schema):
    """Substitute a project's values into one section's SQL.

    `params` is the input row (already normalized). `backup_schema` is the single
    execution-wide backup schema name, forced into every section (including
    SECTION 1, overriding its per-project computed name). Returns the ready-to-run
    SQL. Raises RunnerError if a variable present in the file has no value supplied.
    """
    sql = section["file"].read_text()
    applied = {}
    missing = []

    def apply(var, kind, field, value):
        new_rhs = value if kind != "TEXT" else _quote(value)
        new_sql, n = _sub_literal(sql, var, kind, new_rhs)
        if n:
            if field is not None and (value is None or str(value).strip() == ""):
                missing.append(f"{field} (needed by {var})")
                return sql
            applied[var] = value
        return new_sql

    for var, field in TEXT_VARS.items():
        sql = apply(var, "TEXT", field, params.get(field))
    for var, field in INT_VARS.items():
        val = params.get(field)
        sql = apply(var, "INT", field, str(val).strip() if val not in (None, "") else "")
    for var, field in BOOL_VARS.items():
        sql = apply(var, "BOOLEAN", field, "TRUE" if to_bool(params.get(field)) else "FALSE")

    # One backup schema for the whole execution: force it into every section,
    # overriding SECTION 1's per-project computed name and the pasted literal in
    # sections 2-8, so all projects back up into the same schema.
    if backup_schema:
        sql, n = _force_backup_schema(sql, backup_schema)
        if n:
            applied["v_backup_schema"] = backup_schema

    if missing:
        raise RunnerError(
            f"{section['name']}: missing input value(s): " + "; ".join(missing))
    return sql, applied


def parse_backup_schema(notices):
    for line in notices:
        m = BACKUP_SCHEMA_RE.search(str(line))
        if m:
            return m.group(1).strip()
    return None


def run_section(pool, section, sql, dry_run, heartbeat=None, interval=15):
    """Execute one prepared section. Commit on success in live mode; leave the
    transaction open in dry-run (caller rolls back). Returns the notice lines.

    The section is one long DO block, so `cur.execute()` blocks with no output
    until it finishes. To give live commentary, the execute runs on a worker
    thread while this thread calls `heartbeat(elapsed_seconds, last_notice)` every
    `interval` seconds — `last_notice` is the most recent NOTICE the server has
    sent so far (None if psycopg2 hasn't surfaced any yet)."""
    conn = pool.get(section["db_key"])
    conn.notices.clear()
    cur = conn.cursor()
    box = {}

    def work():
        try:
            cur.execute(sql)
        except BaseException as exc:  # re-raised on the main thread below
            box["exc"] = exc

    t = threading.Thread(target=work, daemon=True)
    start = time.time()
    t.start()
    while True:
        t.join(timeout=interval if (heartbeat and interval > 0) else None)
        if not t.is_alive():
            break
        if heartbeat:
            try:
                last = conn.notices.last
            except Exception:
                last = None
            heartbeat(int(time.time() - start), last)

    cur.close()
    if "exc" in box:
        raise box["exc"]
    notices = conn.notices.snapshot()
    if not dry_run:
        conn.commit()
    return notices
