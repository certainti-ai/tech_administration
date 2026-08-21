"""
Running the vendor's SECTION 1-8 SQL, safely.

A project or project-fiscal purge is not a subtree delete. It executes eight
hand-written PL/pgSQL ``DO`` blocks that delete rows **and recompute the financial
aggregates** that survive them — account fiscal totals, project rollups, QRE
dollars. That arithmetic is the reason the SQL is used verbatim rather than
reimplemented: a re-derived recompute that is subtly wrong produces financial
figures that look plausible and are not.

Each section carries a ``FILL IN`` block of variable declarations at the top,
which a human used to edit by hand before running it in a SQL client. This module
does that edit in memory, in the right order, on the right database, carrying
SECTION 1's announced backup-schema name into the later sections.

**The one thing this module exists to prevent.** The vendor SQL ships with real
production identifiers in those declarations — a live tenant schema, a live
account rid, a live project rid. They are not placeholders like ``<schema>``; they
are values that resolve. So a substitution that silently fails to match does not
produce an error or a no-op: it runs a deletion against tenant ``trd365_01379``
and the account whose rid is baked into the file. The legacy runner checked that
every value it was *given* got used; it did not check that every value in the
*file* got replaced, which is the direction the danger runs in.

:func:`prepare` therefore refuses to hand back SQL in which any identifier-shaped
literal it did not put there survives. That check is the point of this module —
everything else is bookkeeping.

Transactions are driven from here because a ``DO`` block cannot commit itself:

* apply    -> commit after each section that succeeds;
* dry run  -> never commit, and the caller rolls back every connection it used.

Note what a dry run means here, because it is not what it means elsewhere in this
package. The row-level engine counts rows without touching them. A dry run of
these sections **executes the deletes and the recompute**, inside a transaction
that is then discarded. It takes the same locks and does the same work; it just
does not keep the result. That is the only way to dry-run SQL that recomputes,
and it is why a dry run here is not free.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from trd365_core.errors import Trd365Error


class SectionError(Trd365Error):
    """A section could not be prepared or executed."""


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

#: The token in a section's filename naming the database it runs against.
DB_TOKENS: dict[str, str] = {
    "ORGDB": "orgdb",
    "MAINDB": "maindb",
    "TRD365AI": "trd365ai",
}

_SECTION_NUMBER = re.compile(r"SECTION\s*_?(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class Section:
    """One vendor SQL file: which section it is, and where it runs."""

    number: int
    name: str
    path: Path
    db_key: str

    def read(self) -> str:
        return self.path.read_text()


def discover(base_sql: Path) -> list[Section]:
    """
    The section files in execution order, with the database each runs against.

    Order and routing are read from the filenames rather than configured, because
    the filenames are what the vendor controls: ``02_delete_project_ORGDB_
    SECTION2.sql`` is section 2 and runs on the org database. A file that does not
    say which database it belongs to is an error, not a guess — running SECTION 3
    against the org database would find none of the tables it expects and report
    that everything was already gone.
    """
    files = sorted(Path(base_sql).glob("*.sql"))
    if not files:
        raise SectionError(f"no .sql files in {base_sql}")

    sections: list[Section] = []
    for path in files:
        upper = path.name.upper()
        token = next((t for t in DB_TOKENS if t in upper), None)
        if token is None:
            raise SectionError(
                f"{path.name}: cannot tell which database this runs on. The filename "
                f"must contain one of {', '.join(DB_TOKENS)}."
            )
        match = _SECTION_NUMBER.search(path.name)
        if match is None:
            raise SectionError(
                f"{path.name}: cannot tell which section this is. The filename must "
                f"contain SECTION<n>."
            )
        sections.append(
            Section(
                number=int(match.group(1)),
                name=path.name,
                path=path,
                db_key=DB_TOKENS[token],
            )
        )

    sections.sort(key=lambda s: (s.number, s.name))
    return sections


# ---------------------------------------------------------------------------
# substitution
# ---------------------------------------------------------------------------

#: Declaration name -> the field of the run's parameters that fills it. Several
#: differently-named variables carry the same project-fiscal identifier; that is
#: the vendor's naming, reproduced rather than tidied.
TEXT_VARIABLES: dict[str, str] = {
    "v_schema_name": "schema_name",
    "v_account_rid": "account_rid",
    "v_project_rid": "project_rid",
    "v_project_fiscal_id": "project_fiscal_id",
    "v_project_fiscal_rid": "project_fiscal_id",
    "v_lookup_project_fiscal_id": "project_fiscal_id",
    "v_lookup_project_fiscal_rid": "project_fiscal_id",
}
INTEGER_VARIABLES: dict[str, str] = {"v_fiscal_year": "fiscal_year"}
BOOLEAN_VARIABLES: dict[str, str] = {"v_is_last_fiscal": "is_last_fiscal"}

#: SECTION 1 announces the backup schema it created on this line. Every later
#: section needs the same value, which a human used to copy across by hand.
_ANNOUNCED_BACKUP_SCHEMA = re.compile(r"backup schema for this run\s*=\s*([^\s=]+)")

#: What an identifier-shaped literal looks like: a rid (``D001-…``, ``P001-…``) or
#: a tenant schema (``trd365_01379``). Any of these still present after
#: substitution is a value this module did not put there, which means a
#: declaration went unmatched and the section would run against whatever the
#: vendor last tested with.
_IDENTIFIER_LITERAL = re.compile(r"'([A-Z]\d{3}-[0-9a-fA-F][0-9a-fA-F-]{7,}|trd365_\d+)'")

_TRUTHY = {"1", "true", "t", "yes", "y"}


def as_bool(value: object) -> bool:
    return str(value).strip().lower() in _TRUTHY


def _sql_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _declaration(name: str, kind: str) -> re.Pattern[str]:
    if kind == "TEXT":
        return re.compile(rf"(\b{re.escape(name)}\s+TEXT\s*:=\s*)'(?:[^']|'')*'")
    if kind == "INT":
        return re.compile(rf"(\b{re.escape(name)}\s+INT\s*:=\s*)-?\d+")
    if kind == "BOOLEAN":
        return re.compile(rf"(\b{re.escape(name)}\s+BOOLEAN\s*:=\s*)(?:TRUE|FALSE)", re.IGNORECASE)
    raise ValueError(kind)


def force_backup_schema(sql: str, schema: str) -> tuple[str, int]:
    """
    Point every section at one backup schema.

    Two forms have to be handled: sections 2-8 declare it as a literal that used
    to be pasted in by hand, and SECTION 1 *computes* a timestamped name. Both are
    overridden, so one run has one backup schema across all three databases rather
    than a different one per section.
    """
    literal = _sql_literal(schema)
    sql, declared = re.subn(
        r"(\bv_backup_schema\s+TEXT\s*:=\s*)'(?:[^']|'')*'",
        lambda m: m.group(1) + literal,
        sql,
    )
    sql, computed = re.subn(
        r"(\bv_backup_schema\s*:=\s*)'backup_release[^;]*;",
        lambda m: m.group(1) + literal + ";",
        sql,
    )
    return sql, declared + computed


@dataclass
class Prepared:
    """One section's SQL with this run's values in it."""

    section: Section
    sql: str
    applied: dict[str, object] = field(default_factory=dict)


def prepare(section: Section, params: Mapping[str, object], backup_schema: str) -> Prepared:
    """
    Substitute this run's values into one section, and refuse to return SQL that
    still contains any of the vendor's.

    Raises :class:`SectionError` if a declaration the file contains has no value
    supplied, or — the check that matters — if any identifier-shaped literal
    survives that was not one of the values supplied.
    """
    sql = section.read()
    applied: dict[str, object] = {}
    missing: list[str] = []
    supplied: set[str] = set()

    def substitute(name: str, kind: str, field_name: str, value: object, *, record=None) -> None:
        """Replace one declaration's right-hand side, or note that it has no value."""
        nonlocal sql
        if value is None or str(value).strip() == "":
            # Only a problem if the file actually declares it.
            if _declaration(name, kind).search(sql):
                missing.append(f"{field_name} (needed by {name})")
            return
        if kind == "TEXT":
            rhs = _sql_literal(value)
        elif kind == "BOOLEAN":
            rhs = "TRUE" if as_bool(value) else "FALSE"
        else:
            rhs = str(value).strip()
        # rhs is bound here, not read from the enclosing loop when the lambda runs.
        sql, count = _declaration(name, kind).subn(lambda m, rhs=rhs: m.group(1) + rhs, sql)
        if count:
            applied[name] = record if record is not None else value

    for name, field_name in TEXT_VARIABLES.items():
        value = params.get(field_name)
        substitute(name, "TEXT", field_name, value)
        if value is not None and str(value).strip() != "":
            supplied.add(str(value))

    for name, field_name in INTEGER_VARIABLES.items():
        substitute(name, "INT", field_name, params.get(field_name))

    for name, field_name in BOOLEAN_VARIABLES.items():
        value = params.get(field_name)
        # Recorded as a real bool, not as whatever spelling arrived: this flag
        # decides whether the project row itself is deleted, and "False" as a
        # non-empty string is truthy in the wrong hands.
        substitute(
            name,
            "BOOLEAN",
            field_name,
            value,
            record=as_bool(value) if value is not None else None,
        )

    if backup_schema:
        sql, count = force_backup_schema(sql, backup_schema)
        if count:
            applied["v_backup_schema"] = backup_schema
        supplied.add(backup_schema)

    if missing:
        raise SectionError(f"{section.name}: no value supplied for " + "; ".join(missing))

    survivors = sorted(
        {found for found in _IDENTIFIER_LITERAL.findall(sql) if found not in supplied}
    )
    if survivors:
        raise SectionError(
            f"{section.name}: refusing to run — {len(survivors)} identifier(s) from the "
            f"vendor's own test data are still in this SQL after substitution: "
            f"{', '.join(survivors)}. Something the file declares was not replaced, and "
            f"running it would operate on whoever those identifiers belong to. Check "
            f"whether a declaration was renamed."
        )

    return Prepared(section=section, sql=sql, applied=applied)


def announced_backup_schema(notices: Iterable[object]) -> str | None:
    """The backup schema SECTION 1 says it created, from its NOTICE output."""
    for line in notices:
        match = _ANNOUNCED_BACKUP_SCHEMA.search(str(line))
        if match:
            return match.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------

Progress = Callable[[int, str | None], None]


def execute(
    pool,
    prepared: Prepared,
    *,
    dry_run: bool,
    on_progress: Progress | None = None,
    interval: int = 15,
) -> list[str]:
    """
    Run one prepared section and return the NOTICE lines it emitted.

    Commits on success when applying; in a dry run the transaction is left open
    for the caller to roll back — deliberately, so that a later section on the
    same database can still see the backup schema an earlier one created without
    any of it being kept.

    The section is a single ``DO`` block, so ``execute()`` blocks with no output
    until the whole thing finishes, which for a large tenant is minutes. It
    therefore runs on a worker thread while this one reports elapsed time and the
    most recent NOTICE, so an operator can tell a slow run from a hung one.
    """
    conn = pool.get(prepared.section.db_key)
    conn.notices.clear()
    cursor = conn.cursor()
    failure: dict[str, BaseException] = {}

    def work() -> None:
        try:
            cursor.execute(prepared.sql)
        except BaseException as exc:  # re-raised on this thread below
            failure["exc"] = exc

    worker = threading.Thread(target=work, daemon=True)
    started = time.time()
    worker.start()

    reporting = on_progress is not None and interval > 0
    while True:
        worker.join(timeout=interval if reporting else None)
        if not worker.is_alive():
            break
        try:
            last = conn.notices.last
        except Exception:
            last = None
        on_progress(int(time.time() - started), last)

    cursor.close()
    if "exc" in failure:
        raise failure["exc"]

    notices = [str(line).rstrip() for line in conn.notices.snapshot()]
    if not dry_run:
        conn.commit()
    return notices
