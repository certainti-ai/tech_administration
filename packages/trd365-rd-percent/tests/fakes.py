"""
A fake pair of databases, just deep enough for this utility.

It does not evaluate SQL. It records every statement with its parameters and
answers the handful of reads the utility makes from a table of canned responses.
That is the right depth here: what matters is *which* statements run, in what
order, with what numbers — not that a reimplemented Postgres agrees with itself.
"""

from __future__ import annotations

import re


class Cursor:
    def __init__(self, conn):
        self.conn = conn
        self._result: list[tuple] = []
        self.description: list[tuple] | None = None
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def close(self):
        pass

    def execute(self, sql, params=None):
        squashed = " ".join(sql.split())
        self.conn.statements.append((squashed, list(params or [])))
        self._result = []
        self.description = None
        self.rowcount = self.conn.rowcount_for(squashed)

        for pattern, response in self.conn.answers:
            if re.search(pattern, squashed, re.IGNORECASE):
                columns, rows = response
                self.description = [(name,) for name in columns]
                self._result = rows
                return

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)


class Connection:
    """
    One database. ``answers`` maps a regex over the statement to (columns, rows).

    Later entries win over earlier ones only by being more specific patterns; the
    first match is used, so order them narrowest first.
    """

    def __init__(self, answers=(), rowcounts=None, fail_on: str | None = None):
        self.answers = list(answers)
        self.rowcounts = dict(rowcounts or {})
        self.statements: list[tuple[str, list]] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_on = fail_on

    def cursor(self):
        return _FailingCursor(self) if self.fail_on else Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def rowcount_for(self, sql: str) -> int:
        for fragment, count in self.rowcounts.items():
            if fragment in sql:
                return count
        return 1

    # ------------------------------------------------------------- assertions

    def ran(self, fragment: str) -> list[tuple[str, list]]:
        return [(s, p) for s, p in self.statements if fragment in s]

    def did_not_run(self, fragment: str) -> bool:
        return not self.ran(fragment)

    def order_of(self, *fragments: str) -> list[int]:
        found = []
        for fragment in fragments:
            matches = [i for i, (s, _) in enumerate(self.statements) if fragment in s]
            found.append(matches[0] if matches else -1)
        return found


class _FailingCursor(Cursor):
    def execute(self, sql, params=None):
        super().execute(sql, params)
        if self.conn.fail_on and self.conn.fail_on in " ".join(sql.split()):
            raise RuntimeError("column does not exist")


class Pool:
    def __init__(self, main: Connection, org: Connection):
        self._connections = {"maindb": main, "orgdb": org}

    def get(self, db_key: str) -> Connection:
        return self._connections[db_key]

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


# ---------------------------------------------------------------------------
# canned reads
# ---------------------------------------------------------------------------

ACCOUNT_RID = "P001-account-1"
R_NUMBER = "ACC-00042"
SCHEMA = "trd365_00042"
FISCAL_RID = "P001-fiscal-1"
PROJECT_RID = "P001-project-1"
COUNTRY_RID = "P001-country-usa"
CLOSED_STATUS_RID = "P001-status-closed"

PROJECT_FISCAL_COLUMNS = [
    "rid",
    "project_rid",
    "account_rid",
    "project_code",
    "fiscal_year",
    "country_rid",
    "rd_percent_potential_ai",
    "total_cost_fte_prj",
    "total_cost_subcon_prj",
    "total_cost_nonlabor_prj",
    "total_cost_prj",
]


def project_fiscal_row(fte=100_000.0, subcon=50_000.0, nonlabor=20_000.0, country=COUNTRY_RID):
    return (
        FISCAL_RID,
        PROJECT_RID,
        ACCOUNT_RID,
        "FY25 Project 1",
        2025,
        country,
        55.0,
        fte,
        subcon,
        nonlabor,
        fte + subcon + nonlabor,
    )


def main_connection(*, closed_status=CLOSED_STATUS_RID, sub_con_percent=65.0, **kwargs):
    answers: list[tuple[str, tuple[list[str], list[tuple]]]] = [
        (
            r"FROM \"trd365\"\.\"account\" WHERE r_number",
            (["rid", "r_number", "fiscal_start_date", "fiscal_end_date"],
             [(ACCOUNT_RID, R_NUMBER, "04/01", "03/31")]),
        ),
        (
            r"rd_credit_config_group",
            (["country_code", "config_json", "effective_start_date", "effective_end_date"],
             [("USA", {"rrc_sub_con_percent": sub_con_percent}, "2020-01-01", "2030-12-31")]),
        ),
        (
            r"case_status",
            (["rid"], [(closed_status,)] if closed_status else []),
        ),
        (
            r"event_types",
            (["rid"], [("P001-event-web",)]),
        ),
    ]
    return Connection(answers=answers, **kwargs)


def org_connection(
    *,
    fiscal_rows=None,
    schema_exists=True,
    has_cases=True,
    has_case_resource_fiscal=True,
    mapped_to_closed=False,
    **kwargs,
):
    if fiscal_rows is None:
        fiscal_rows = [project_fiscal_row()]
    present: list[tuple[str, tuple[list[str], list[tuple]]]] = [
        (
            r"information_schema\.schemata",
            (["present"], [(1,)] if schema_exists else []),
        ),
        (
            r"table_name=%s|table_schema=%s AND table_name",
            (["present"], []),  # replaced below per table
        ),
        (
            r"FROM \"trd365_00042\"\.\"project_fiscal\" WHERE account_rid",
            (PROJECT_FISCAL_COLUMNS, fiscal_rows),
        ),
        (
            r"LEFT JOIN \"trd365_00042\"\.\"case_projects\"",
            (["present"], [(1,)] if mapped_to_closed else []),
        ),
    ]
    conn = Connection(answers=present, **kwargs)
    conn.tables = {
        "cases": has_cases,
        "case_project_resource_fiscal": has_case_resource_fiscal,
    }

    # table_exists is asked by name, so answer it from the map rather than a regex.
    original = conn.cursor

    def cursor():
        cur = original()
        base = cur.execute

        def execute(sql, params=None):
            squashed = " ".join(sql.split())
            if "information_schema.tables" in squashed:
                conn.statements.append((squashed, list(params or [])))
                name = list(params or [None, None])[1]
                cur._result = [(1,)] if conn.tables.get(name) else []
                cur.description = [("present",)]
                cur.rowcount = 1
                return
            base(sql, params)

        cur.execute = execute
        return cur

    conn.cursor = cursor
    return conn
