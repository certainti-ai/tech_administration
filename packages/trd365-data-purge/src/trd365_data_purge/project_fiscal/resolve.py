"""
Turning what an operator types into the parameters the SECTION SQL needs.

Every section wants the same six values: the tenant schema, the account rid, the
project rid, the project-fiscal rid, the fiscal year, and whether this is the
project's last remaining fiscal. An operator has at most an account number and a
fiscal rid, so the rest is looked up here.

Ported from ``legacy/trd365_maintenance/data_purge/project_fiscal/resolve.py``.
Two things changed:

* the column probes go through the run-scoped
  :class:`~trd365_data_purge.engine.SchemaCache`, so a schema's columns are read
  once per run rather than once per question;
* ``is_last_fiscal`` is a named type rather than a bare bool, because how it was
  arrived at — counted, or forced by the operator — has to reach the report. It
  decides whether the project row itself is deleted, and "the tool decided" and
  "a human insisted" are different things to read afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from trd365_core.datamodel import PK_COLUMN

from ..account.scoping import ResolvedAccount, resolve_account_reference
from ..engine import SchemaCache, quote

ORG_DB = "orgdb"

#: The tables this module reads.
PROJECT = "project"
PROJECT_FISCAL = "project_fiscal"


def _rows(conn, sql: str, params: tuple) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    conn.rollback()
    return rows


def _row(conn, sql: str, params: tuple) -> tuple | None:
    rows = _rows(conn, sql, params)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# fiscals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fiscal:
    """One fiscal year of a project."""

    rid: str
    year: int | None


def fiscals_of(conn, cache: SchemaCache, schema: str, project_rid: str) -> list[Fiscal]:
    """
    Every fiscal of a project, oldest first.

    Ordered by year because the *last* one is the one whose deletion also removes
    the project row and recomputes the account totals, so which one that is must
    not depend on how the database happened to return the rows. A fiscal with no
    year sorts last: it cannot be placed among the others, and making it the final
    one at least makes its effect visible in the report.
    """
    columns = cache.columns(conn, ORG_DB, schema, PROJECT_FISCAL)
    has_year = "fiscal_year" in columns

    selected = f"{PK_COLUMN}, fiscal_year" if has_year else f"{PK_COLUMN}, NULL"
    order = "fiscal_year NULLS LAST" if has_year else PK_COLUMN
    rows = _rows(
        conn,
        f"SELECT {selected} FROM {quote(schema)}.{quote(PROJECT_FISCAL)} "
        f"WHERE project_rid=%s ORDER BY {order}, {PK_COLUMN}",
        (project_rid,),
    )
    return [Fiscal(rid=row[0], year=row[1]) for row in rows]


# ---------------------------------------------------------------------------
# one fiscal, fully resolved
# ---------------------------------------------------------------------------


@dataclass
class ResolvedFiscal:
    """A project fiscal, and everything the sections need in order to delete it."""

    rid: str
    exists: bool
    account: ResolvedAccount
    org_schema: str = ""
    project_rid: str = ""
    year: int | None = None
    #: How many fiscals the project has, this one included.
    siblings: int = 0
    #: Whether deleting this one also removes the project row and recomputes the
    #: account-level totals.
    is_last: bool = False
    #: ``counted`` or ``forced``: whether ``is_last`` was worked out or overridden.
    decided_by: str = "counted"
    notes: list[str] = field(default_factory=list)

    @property
    def params(self) -> dict[str, Any]:
        """The values :func:`trd365_data_purge.sections.prepare` substitutes."""
        return {
            "schema_name": self.org_schema,
            "account_rid": self.account.rid,
            "project_rid": self.project_rid,
            "project_fiscal_id": self.rid,
            # "" rather than None: the sections declare v_fiscal_year INT only
            # where they use it, and an absent value must read as absent so that
            # prepare() reports it rather than substituting a blank.
            "fiscal_year": "" if self.year is None else self.year,
            "is_last_fiscal": self.is_last,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "rid": self.rid,
            "exists": self.exists,
            "org_schema": self.org_schema,
            "account_rid": self.account.rid,
            "r_number": self.account.r_number,
            "project_rid": self.project_rid,
            "fiscal_year": self.year,
            "siblings": self.siblings,
            "is_last_fiscal": self.is_last,
            "is_last_decided_by": self.decided_by,
        }


def resolve_fiscal(
    pool,
    cache: SchemaCache,
    *,
    account_ref: str,
    fiscal_rid: str,
    force_last: bool | None = None,
) -> ResolvedFiscal:
    """
    Resolve one project fiscal inside the account it was said to belong to.

    ``force_last`` overrides the computed ``is_last_fiscal``. It exists because the
    count can be wrong in one direction that matters: if a sibling fiscal was
    already deleted by a run that failed partway, the project now looks
    single-fiscal and this deletion would take the project row with it. An
    operator who knows better says so, and the report records that they did.
    """
    account = resolve_account_reference(pool, account_ref)
    if not account.exists:
        return ResolvedFiscal(rid=fiscal_rid, exists=False, account=account)

    schema = account.org_schema
    conn = pool.get(ORG_DB)

    if not cache.table_exists(conn, ORG_DB, schema, PROJECT_FISCAL):
        return ResolvedFiscal(
            rid=fiscal_rid, exists=False, account=account, org_schema=schema
        )

    columns = cache.columns(conn, ORG_DB, schema, PROJECT_FISCAL)
    year_column = "fiscal_year" if "fiscal_year" in columns else "NULL"
    row = _row(
        conn,
        f"SELECT project_rid, {year_column} "
        f"FROM {quote(schema)}.{quote(PROJECT_FISCAL)} WHERE {PK_COLUMN}=%s",
        (fiscal_rid,),
    )
    if row is None:
        return ResolvedFiscal(
            rid=fiscal_rid, exists=False, account=account, org_schema=schema
        )

    project_rid, year = row
    siblings = fiscals_of(conn, cache, schema, project_rid)
    counted_last = len(siblings) <= 1

    notes: list[str] = []
    if force_last is not None and force_last != counted_last:
        notes.append(
            f"is_last_fiscal was forced to {force_last}; the project has "
            f"{len(siblings)} fiscal(s), which would have given {counted_last}"
        )

    return ResolvedFiscal(
        rid=fiscal_rid,
        exists=True,
        account=account,
        org_schema=schema,
        project_rid=project_rid,
        year=year,
        siblings=len(siblings),
        is_last=counted_last if force_last is None else force_last,
        decided_by="counted" if force_last is None else "forced",
        notes=notes,
    )


# ---------------------------------------------------------------------------
# a whole project: every fiscal, in order
# ---------------------------------------------------------------------------


def resolve_project(
    pool, cache: SchemaCache, *, account_ref: str, project_ref: str
) -> tuple[ResolvedAccount, str | None, list[Fiscal]]:
    """
    Resolve a project by rid or by code, and list its fiscals oldest first.

    Returns ``(account, project_rid, fiscals)``; ``project_rid`` is ``None`` when
    the project is not in this account's schema.
    """
    account = resolve_account_reference(pool, account_ref)
    if not account.exists:
        return account, None, []

    schema = account.org_schema
    conn = pool.get(ORG_DB)
    if not cache.table_exists(conn, ORG_DB, schema, PROJECT):
        return account, None, []

    row = _row(
        conn,
        f"SELECT {PK_COLUMN} FROM {quote(schema)}.{quote(PROJECT)} WHERE {PK_COLUMN}=%s",
        (project_ref,),
    )
    if row is None:
        code_column = _code_column(conn, cache, schema)
        if code_column is None:
            return account, None, []
        row = _row(
            conn,
            f"SELECT {PK_COLUMN} FROM {quote(schema)}.{quote(PROJECT)} "
            f"WHERE {quote(code_column)}=%s",
            (project_ref,),
        )
        if row is None:
            return account, None, []

    project_rid = row[0]
    return account, project_rid, fiscals_of(conn, cache, schema, project_rid)


#: The columns a project's human-facing code might be stored in, in preference
#: order. ``name`` is last because it is the least likely to be unique, and
#: resolving a project by a non-unique column would purge whichever row came back
#: first.
CODE_COLUMNS: tuple[str, ...] = ("project_code", "code", "project_id", "project_number", "name")


def _code_column(conn, cache: SchemaCache, schema: str) -> str | None:
    columns = cache.columns(conn, ORG_DB, schema, PROJECT)
    return next((name for name in CODE_COLUMNS if name in columns), None)


def plan_project_fiscals(
    account: ResolvedAccount, project_rid: str, fiscals: list[Fiscal]
) -> list[dict[str, Any]]:
    """
    The per-fiscal parameter sets for deleting a whole project, in order.

    Only the final entry carries ``is_last_fiscal``, and that is what removes the
    project row and recomputes the account totals. Deleting a project deletes all
    of its fiscals, so the last one processed genuinely is the last remaining —
    which is why this is safe to decide up front here, and is *not* safe to decide
    that way for a single-fiscal purge.
    """
    total = len(fiscals)
    return [
        {
            "schema_name": account.org_schema,
            "account_rid": account.rid,
            "project_rid": project_rid,
            "project_fiscal_id": fiscal.rid,
            "fiscal_year": "" if fiscal.year is None else fiscal.year,
            "is_last_fiscal": index == total - 1,
        }
        for index, fiscal in enumerate(fiscals)
    ]
