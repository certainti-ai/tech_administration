"""
Rows pointing at parents that no longer exist.

An orphan is a child row whose ``{entity}_rid`` names a ``rid`` that is not in
the parent table. The estate has no foreign-key constraints on most of these
relationships — and cannot have one on ``account_rid``, which crosses databases
— so nothing prevents them and only a scan finds them.

This module consumes the model snapshot rather than introspecting: the edges it
walks are the references the data-model analysis already resolved. Everything
here is read-only. Removing orphans is a separate, destructive utility.

Two false positives are avoided deliberately, because a wrong orphan count sends
someone deleting rows that are fine:

* **Global-lookup entities.** Some parent tables are empty in a tenant schema
  because the real rows live in a master table in the main schema —
  ``interaction_type`` is the example the original calls out. Every child row
  then looks orphaned. A parent that is empty here *and* exists in the main
  schema is excluded from the scan and reported as excluded.
* **Backup tables.** Already excluded upstream by ``SchemaCatalog.real_tables``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from trd365_core.datamodel import (
    DEFAULT_MAIN_SCHEMA,
    PK_COLUMN,
    PRIMARY_ENTITIES,
    Reference,
    entity,
)
from trd365_core.model_snapshot import ModelSnapshot, SchemaModel

Log = Callable[[str], None]

PRIMARY_ENTITY_NAMES = frozenset(e.name for e in PRIMARY_ENTITIES)
ACCOUNT = entity("account")

#: How many example rids to keep per orphaned edge, unless overridden.
DEFAULT_SAMPLE = 3


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@dataclass
class Orphan:
    """One edge with rows whose parent is missing."""

    schema: str
    child_table: str
    column: str
    entity: str | None
    parent_table: str
    rows: int
    samples: list[str] = field(default_factory=list)
    #: Set when the edge could not be checked. ``rows`` is 0 and means nothing.
    error: str | None = None

    @property
    def checked(self) -> bool:
        return self.error is None

    def to_row(self) -> dict[str, Any]:
        data = asdict(self)
        data["samples"] = "; ".join(str(s) for s in self.samples)
        return data


@dataclass
class SchemaScan:
    """The result of scanning one tenant schema."""

    schema: str
    orphans: list[Orphan] = field(default_factory=list)
    edges_checked: int = 0
    excluded_parents: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def total_rows(self) -> int:
        return sum(o.rows for o in self.orphans if o.checked)

    @property
    def failed_edges(self) -> list[Orphan]:
        return [o for o in self.orphans if not o.checked]


# --------------------------------------------------------------------------
# preloading
# --------------------------------------------------------------------------


def account_rids(fetch, main_schema: str = DEFAULT_MAIN_SCHEMA) -> set[str]:
    """
    Every valid account rid, read once.

    ``account_rid`` crosses databases, so it cannot be checked with a join. The
    parent set is small enough to hold in memory and every tenant schema needs
    it, so it is read once for the whole run rather than per schema.
    """
    rows = fetch(
        "maindb",
        f"SELECT {PK_COLUMN} FROM {quote(main_schema)}.{quote(ACCOUNT.table)}",
    )
    return {row[0] for row in rows}


def account_table_exists(fetch, main_schema: str = DEFAULT_MAIN_SCHEMA) -> bool:
    return bool(
        fetch(
            "maindb",
            "SELECT 1 FROM information_schema.columns WHERE table_schema=%s "
            "AND table_name=%s AND column_name=%s",
            [main_schema, ACCOUNT.table, PK_COLUMN],
        )
    )


def global_lookup_parents(
    fetch, model: SchemaModel, main_schema: str = DEFAULT_MAIN_SCHEMA
) -> set[str]:
    """
    Parent tables that are empty here because the real rows live in main.

    Checking a child against an empty local parent would report every row as an
    orphan. The original tool found this the hard way; the exclusion is carried
    over unchanged.
    """
    parents = {
        ref.to_table
        for ref in model.references
        if not ref.cross_db and ref.to_schema == model.schema
    }

    excluded: set[str] = set()
    for parent in sorted(parents):
        rows = fetch(
            "orgdb", f"SELECT count(*) FROM {quote(model.schema)}.{quote(parent)}"
        )
        if rows and rows[0][0] == 0 and _exists_in_main(fetch, main_schema, parent):
            excluded.add(parent)
    return excluded


def _exists_in_main(fetch, main_schema: str, table: str) -> bool:
    return bool(
        fetch(
            "maindb",
            "SELECT 1 FROM information_schema.columns WHERE table_schema=%s "
            "AND table_name=%s AND column_name=%s",
            [main_schema, table, PK_COLUMN],
        )
    )


# --------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------


def _same_db_orphans(fetch, schema: str, ref: Reference, sample: int) -> tuple[int, list[str]]:
    child = f"{quote(schema)}.{quote(ref.from_table)}"
    parent = f"{quote(schema)}.{quote(ref.to_table)}"
    column = quote(ref.column)
    missing = (
        f"c.{column} IS NOT NULL AND NOT EXISTS "
        f"(SELECT 1 FROM {parent} p WHERE p.{PK_COLUMN} = c.{column})"
    )

    count = fetch("orgdb", f"SELECT count(*) FROM {child} c WHERE {missing}")[0][0]
    if not count or not sample:
        return count, []

    rows = fetch(
        "orgdb",
        f"SELECT DISTINCT c.{column} FROM {child} c WHERE {missing} LIMIT %s",
        [sample],
    )
    return count, [row[0] for row in rows]


def _account_orphans(
    fetch, schema: str, ref: Reference, valid: set[str], sample: int
) -> tuple[int, list[str]]:
    # No join is possible across databases, so the distinct values are grouped
    # here and compared against the preloaded parent set.
    column = quote(ref.column)
    rows = fetch(
        "orgdb",
        f"SELECT {column}, count(*) FROM {quote(schema)}.{quote(ref.from_table)} "
        f"WHERE {column} IS NOT NULL GROUP BY {column}",
    )
    bad = [(value, count) for value, count in rows if value not in valid]
    return sum(count for _value, count in bad), [value for value, _count in bad][:sample]


def scan_schema(
    fetch,
    model: SchemaModel,
    *,
    valid_accounts: set[str],
    check_account: bool = True,
    all_entities: bool = False,
    sample: int = DEFAULT_SAMPLE,
    main_schema: str = DEFAULT_MAIN_SCHEMA,
    log: Log = print,
) -> SchemaScan:
    """
    Scan one tenant schema for orphan rows.

    ``all_entities`` widens the scan from the four primary entities to every
    resolved reference. The narrow default is not laziness: the primary entities
    are the ones a purge and a remediation act on, and the wide scan is where
    the global-lookup false positives live.
    """
    scan = SchemaScan(schema=model.schema)

    try:
        excluded = global_lookup_parents(fetch, model, main_schema)
    except Exception as exc:  # noqa: BLE001 — recorded, and the scan continues
        scan.error = f"could not determine global-lookup parents: {str(exc).strip()[:120]}"
        return scan

    scan.excluded_parents = sorted(excluded)
    if excluded:
        log(f"    excluding global-lookup parents: {', '.join(scan.excluded_parents)}")

    for ref in sorted(model.references, key=lambda r: (r.from_table, r.column)):
        if not all_entities and ref.to_entity not in PRIMARY_ENTITY_NAMES:
            continue
        if ref.cross_db and not check_account:
            continue
        if not ref.cross_db and ref.to_table in excluded:
            continue

        scan.edges_checked += 1
        try:
            if ref.cross_db:
                count, samples = _account_orphans(
                    fetch, model.schema, ref, valid_accounts, sample
                )
            else:
                count, samples = _same_db_orphans(fetch, model.schema, ref, sample)
        except Exception as exc:  # noqa: BLE001 — one bad edge must not end the sweep
            scan.orphans.append(
                Orphan(
                    schema=model.schema,
                    child_table=ref.from_table,
                    column=ref.column,
                    entity=ref.to_entity,
                    parent_table=ref.to_table,
                    rows=0,
                    error=f"{type(exc).__name__}: {str(exc).strip()[:120]}",
                )
            )
            continue

        if count:
            scan.orphans.append(
                Orphan(
                    schema=model.schema,
                    child_table=ref.from_table,
                    column=ref.column,
                    entity=ref.to_entity,
                    parent_table=ref.to_table,
                    rows=count,
                    samples=[str(s) for s in samples],
                )
            )

    return scan


def scan(
    fetch,
    snapshot: ModelSnapshot,
    *,
    schemas: list[str] | None = None,
    all_entities: bool = False,
    sample: int = DEFAULT_SAMPLE,
    log: Log = print,
) -> list[SchemaScan]:
    """Scan every schema in the snapshot, or the named subset."""
    targets = snapshot.tenant_schemas if schemas is None else schemas
    main_schema = snapshot.main_schema

    check_account = account_table_exists(fetch, main_schema)
    valid = account_rids(fetch, main_schema) if check_account else set()
    if check_account:
        log(f"  {len(valid)} account rid(s) loaded from {main_schema}.{ACCOUNT.table}")
    else:
        log(f"  {main_schema}.{ACCOUNT.table} not found — account_rid will not be checked")

    results: list[SchemaScan] = []
    for index, name in enumerate(targets, start=1):
        log(f"\n  [{index}/{len(targets)}] {name}")
        try:
            model = snapshot.schema(name)
        except Exception as exc:  # noqa: BLE001 — named but not modelled
            results.append(SchemaScan(schema=name, error=str(exc).strip()[:160]))
            log(f"    skipped: {str(exc).strip()[:120]}")
            continue

        result = scan_schema(
            fetch,
            model,
            valid_accounts=valid,
            check_account=check_account,
            all_entities=all_entities,
            sample=sample,
            main_schema=main_schema,
            log=log,
        )
        results.append(result)

        if result.error:
            log(f"    ERROR: {result.error}")
        else:
            log(
                f"    {result.total_rows} orphan row(s) across "
                f"{len([o for o in result.orphans if o.checked])} of "
                f"{result.edges_checked} edge(s)"
                + (f", {len(result.failed_edges)} edge(s) failed" if result.failed_edges else "")
            )

    return results


def totals(scans: list[SchemaScan]) -> dict[str, int]:
    """Headline numbers, which are also the dashboard's health metrics."""
    return {
        "schemas_scanned": len([s for s in scans if s.error is None]),
        "schemas_failed": len([s for s in scans if s.error is not None]),
        "edges_checked": sum(s.edges_checked for s in scans),
        "edges_failed": sum(len(s.failed_edges) for s in scans),
        "orphan_edges": sum(len([o for o in s.orphans if o.checked]) for s in scans),
        "orphan_rows": sum(s.total_rows for s in scans),
    }
