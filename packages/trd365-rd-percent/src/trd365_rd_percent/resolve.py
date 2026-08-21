"""
Turning what an operator types into the row to correct.

An operator has the Account ID from the product UI (``ACC-00459``), a project
code, and a fiscal year. None of those is a primary key. This resolves them, in
the same order and by the same keys the legacy tool used.

The one rule worth stating: the project-code lookup is **scoped by account_rid**
and must match exactly one row. Project codes are not unique across tenants, and
in principle not unique within one either, so an unscoped or ambiguous lookup
would correct whichever row came back first — with money.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trd365_core.datamodel import DEFAULT_MAIN_SCHEMA, TENANT_SCHEMA_LIKE
from trd365_core.errors import Trd365Error

from .writes import quote

TENANT_PREFIX = TENANT_SCHEMA_LIKE.replace("\\", "").removesuffix("%")
R_NUMBER_PREFIX = "ACC-"


class NotFound(Trd365Error):
    """The account, schema or project fiscal named does not resolve to one row."""


@dataclass(frozen=True)
class Target:
    """The project fiscal to correct, and the context its writes need."""

    account_rid: str
    r_number: str
    schema: str
    project_fiscal_rid: str
    project_rid: str
    project_code: str
    fiscal_year: int
    country_rid: str | None
    fiscal_start: str | None
    fiscal_end: str | None
    row: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_rid": self.account_rid,
            "r_number": self.r_number,
            "schema": self.schema,
            "project_fiscal_rid": self.project_fiscal_rid,
            "project_rid": self.project_rid,
            "project_code": self.project_code,
            "fiscal_year": self.fiscal_year,
            "country_rid": self.country_rid,
        }


def _row(conn, sql: str, params: tuple) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        found = cur.fetchone()
        if found is None:
            return None
        columns = [d[0] for d in cur.description]
    return dict(zip(columns, found, strict=False))


def _rows(conn, sql: str, params: tuple) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        found = cur.fetchall()
        columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row, strict=False)) for row in found]


def resolve(
    main_conn, org_conn, *, account_id: str, project_code: str, fiscal_year: int
) -> Target:
    """Resolve the account, its tenant schema, and exactly one project fiscal."""
    account = _row(
        main_conn,
        f"SELECT rid, r_number, fiscal_start_date, fiscal_end_date "
        f"FROM {quote(DEFAULT_MAIN_SCHEMA)}.{quote('account')} WHERE r_number=%s",
        (account_id,),
    )
    if account is None:
        raise NotFound(
            f"no account with r_number {account_id!r} in {DEFAULT_MAIN_SCHEMA}.account. "
            f"This wants the Account ID from the product UI, not the internal rid."
        )

    schema = TENANT_PREFIX + str(account["r_number"] or "").replace(R_NUMBER_PREFIX, "")
    exists = _row(
        org_conn,
        "SELECT 1 AS present FROM information_schema.schemata WHERE schema_name=%s",
        (schema,),
    )
    if exists is None:
        raise NotFound(f"account {account_id} resolves to schema {schema}, which does not exist.")

    matches = _rows(
        org_conn,
        f"SELECT * FROM {quote(schema)}.{quote('project_fiscal')} "
        f"WHERE account_rid=%s AND project_code=%s AND fiscal_year=%s",
        (account["rid"], project_code, fiscal_year),
    )
    if not matches:
        raise NotFound(
            f"no project_fiscal in {schema} for project_code={project_code!r} "
            f"fiscal_year={fiscal_year} under account {account_id}."
        )
    if len(matches) > 1:
        # Refusing rather than taking the first: this is about to rewrite money.
        raise NotFound(
            f"{len(matches)} project_fiscal rows match project_code={project_code!r} "
            f"fiscal_year={fiscal_year} in {schema}. Exactly one is required — correct the "
            f"row by its rid instead, or fix the duplicate."
        )

    fiscal = matches[0]
    return Target(
        account_rid=account["rid"],
        r_number=account["r_number"],
        schema=schema,
        project_fiscal_rid=fiscal["rid"],
        project_rid=fiscal.get("project_rid") or "",
        project_code=project_code,
        fiscal_year=fiscal_year,
        country_rid=fiscal.get("country_rid"),
        fiscal_start=account.get("fiscal_start_date"),
        fiscal_end=account.get("fiscal_end_date"),
        row=fiscal,
    )


def closed_case_status(main_conn) -> str | None:
    """
    The rid of the "closed" case status, used to leave frozen financials alone.

    The application takes an arbitrary first row from an ``ILIKE '%closed%'``
    search with no ordering. Reproduced as-is, because matching the application
    matters more here than determinism — but noted, because it is not
    deterministic if a tenant ever has two.
    """
    row = _row(
        main_conn,
        f"SELECT rid FROM {quote(DEFAULT_MAIN_SCHEMA)}.{quote('case_status')} "
        f"WHERE status_name ILIKE %s LIMIT 1",
        ("%closed%",),
    )
    return row["rid"] if row else None


def ui_event_type(main_conn) -> tuple[str | None, str | None]:
    """
    The event type and display name a UI-handler change is recorded under.

    Returns ``(event_type_rid, created_by_name)``, either of which may be absent —
    the application writes null in that case rather than failing, and so does this.
    """
    row = _row(
        main_conn,
        f"SELECT rid FROM {quote(DEFAULT_MAIN_SCHEMA)}.{quote('event_types')} "
        f"WHERE event_type=%s LIMIT 1",
        ("web",),
    )
    return (row["rid"] if row else None), None
