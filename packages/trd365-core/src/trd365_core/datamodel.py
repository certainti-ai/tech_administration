"""
The trd365 application data model.

Every maintenance utility needs the same handful of facts: what the primary
entities are, where their tables live, how a foreign key is spelled, which
columns cannot be resolved to a single parent, and which tables are backups to
be ignored. Those facts were previously rediscovered — and re-encoded slightly
differently — in each script. They live here once.

The conventions below were established by the data-model analysis tool
(``legacy/trd365_maintenance/data_model_analysis/model_analysis.py``); this
module is that knowledge lifted into shared, tested code.

Conventions
-----------
* A table's primary key is ``rid``.
* A reference to it is ``{prefix}_rid`` — ``project.rid`` is referenced as
  ``project_rid``.
* The parent table name is usually the prefix, but several are pluralised:
  ``resource_rid`` → ``resources``, ``case_rid`` → ``cases``.
* ``account`` lives in the **main** database while nearly everything that
  references it lives in **org**, so ``account_rid`` is a cross-database
  reference that no foreign key enforces.
* Org is multi-tenant by schema: one ``trd365_*`` schema per tenant.
* Some columns reference different entity types depending on a companion type
  column. Those are polymorphic by design, not broken.

The pure functions here take catalogs rather than connections, so the whole
resolution model is testable without a database — which matters, because no
Claude Code session can reach these databases (see docs/knowledge-base.md §5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from .errors import DataModelError

#: Primary-key column name, by convention, on every table that participates.
PK_COLUMN = "rid"

#: Suffix marking a foreign-key column.
FK_SUFFIX = "_rid"

#: Default schema in the main database holding cross-tenant entities.
DEFAULT_MAIN_SCHEMA = "trd365"

#: Tenant schemas in the org database match this SQL LIKE pattern.
TENANT_SCHEMA_LIKE = r"trd365\_%"

#: Backup / staging tables are excluded from analysis and from purges.
BACKUP_TABLE_RE = re.compile(r"^(backup|bak)_|_backup_|_bak_|backup_[0-9]", re.I)

#: Columns that reference different entity types via a companion type column.
#: Resolving them to one parent is not possible and not a defect.
POLYMORPHIC_COLUMNS: frozenset[str] = frozenset(
    {
        "entity_rid",
        "attach_to",
        "related_to_rid",
        "reference_rid",
        "parent_rid",
        "source_rid",
        "target_rid",
        "attached_to_rid",
    }
)

#: Prefixes whose ``_rid`` columns are polymorphic regardless of exact spelling.
POLYMORPHIC_PREFIXES: frozenset[str] = frozenset(
    {"entity", "related_to", "reference", "parent", "source", "target"}
)

#: An unresolved prefix appearing in at least this many tables is treated as a
#: shared/global lookup entity rather than a typo.
GLOBAL_LOOKUP_MIN_TABLES = 3

#: Fuzzy-similarity threshold above which an unresolved prefix is reported as a
#: likely human-error typo of a real table name.
TYPO_SIMILARITY_CUTOFF = 0.84

#: Seconds before a read is abandoned. psycopg2 has no read timeout, so a
#: dropped SSH tunnel leaves a socket that never returns; see db.fetch.
DEFAULT_QUERY_TIMEOUT = 90


@dataclass(frozen=True)
class Entity:
    """A primary entity and where its table physically lives."""

    name: str
    db_key: str
    table: str
    #: True when the table sits in a per-tenant org schema rather than a fixed one.
    tenant_scoped: bool
    #: The ``{prefix}_rid`` spelling that refers to this entity.
    fk_column: str

    @property
    def is_cross_db(self) -> bool:
        """Referenced from org but stored in main — no FK can enforce it."""
        return self.db_key != "orgdb"


#: The four primary entities, in the order analysis and purges consider them.
PRIMARY_ENTITIES: tuple[Entity, ...] = (
    Entity("account", "maindb", "account", tenant_scoped=False, fk_column="account_rid"),
    Entity("resource", "orgdb", "resources", tenant_scoped=True, fk_column="resource_rid"),
    Entity("project", "orgdb", "project", tenant_scoped=True, fk_column="project_rid"),
    Entity("case", "orgdb", "cases", tenant_scoped=True, fk_column="case_rid"),
)

ENTITIES_BY_NAME: dict[str, Entity] = {e.name: e for e in PRIMARY_ENTITIES}
ENTITIES_BY_FK: dict[str, Entity] = {e.fk_column: e for e in PRIMARY_ENTITIES}

#: Parent table name back to entity name, for the pluralised cases.
TABLE_TO_ENTITY: dict[str, str] = {e.table: e.name for e in PRIMARY_ENTITIES}


def entity(name: str) -> Entity:
    try:
        return ENTITIES_BY_NAME[name]
    except KeyError:
        known = ", ".join(ENTITIES_BY_NAME)
        raise DataModelError(f'Unknown entity "{name}". Known entities: {known}.') from None


def is_backup_table(table_name: str) -> bool:
    return bool(BACKUP_TABLE_RE.search(table_name))


def is_fk_column(column_name: str) -> bool:
    return column_name.endswith(FK_SUFFIX)


def fk_prefix(column_name: str) -> str:
    """``project_rid`` → ``project``."""
    if not is_fk_column(column_name):
        raise DataModelError(f'"{column_name}" is not a {FK_SUFFIX} column.')
    return column_name[: -len(FK_SUFFIX)]


def is_polymorphic(column_name: str) -> bool:
    """Whether a column intentionally references more than one entity type."""
    if column_name in POLYMORPHIC_COLUMNS:
        return True
    if not is_fk_column(column_name):
        return False
    return fk_prefix(column_name) in POLYMORPHIC_PREFIXES


def parent_candidates(prefix: str) -> list[str]:
    """
    Table names a ``{prefix}_rid`` column might point at, most likely first.

    Pluralisation is the only irregularity in practice: ``resource`` →
    ``resources``, ``case`` → ``cases``, and the ``y`` → ``ies`` form for
    completeness.
    """
    candidates = [prefix, f"{prefix}s", f"{prefix}es"]
    if prefix.endswith("y"):
        candidates.append(f"{prefix[:-1]}ies")
    return candidates


def resolve_parent_table(
    column_name: str,
    tables_with_pk: set[str] | frozenset[str],
) -> tuple[str | None, str]:
    """
    Resolve a foreign-key column to its parent table within one schema.

    Returns ``(table, note)``; ``(None, "")`` when nothing matches. ``note``
    records the pluralisation actually used, so reports can show why a column
    resolved to a differently-spelled table.
    """
    prefix = fk_prefix(column_name)
    for candidate in parent_candidates(prefix):
        if candidate in tables_with_pk:
            note = "" if candidate == prefix else f"plural:{prefix}->{candidate}"
            return candidate, note
    return None, ""


@dataclass(frozen=True)
class Reference:
    """A resolved foreign-key relationship."""

    from_table: str
    column: str
    to_entity: str | None
    to_db: str
    to_schema: str
    to_table: str
    cross_db: bool = False
    note: str = ""


@dataclass
class TableInfo:
    name: str
    has_pk: bool = False
    fk_columns: list[str] = field(default_factory=list)


@dataclass
class SchemaCatalog:
    """The tables and ``_rid`` columns of one schema."""

    db_key: str
    schema: str
    tables: dict[str, TableInfo] = field(default_factory=dict)

    @property
    def tables_with_pk(self) -> frozenset[str]:
        return frozenset(name for name, info in self.tables.items() if info.has_pk)

    def real_tables(self) -> dict[str, TableInfo]:
        """Everything except backup/staging tables."""
        return {n: i for n, i in self.tables.items() if not is_backup_table(n)}

    @classmethod
    def from_columns(cls, db_key: str, schema: str, rows) -> SchemaCatalog:
        """Build from ``(table_name, column_name)`` rows of information_schema."""
        catalog = cls(db_key=db_key, schema=schema)
        for table_name, column_name in rows:
            info = catalog.tables.setdefault(table_name, TableInfo(name=table_name))
            if column_name == PK_COLUMN:
                info.has_pk = True
            if is_fk_column(column_name):
                info.fk_columns.append(column_name)
        return catalog


def references(catalog: SchemaCatalog, main_schema: str = DEFAULT_MAIN_SCHEMA) -> list[Reference]:
    """
    Every resolvable foreign-key relationship in a tenant schema.

    Backup tables are skipped, polymorphic columns are omitted (they have no
    single parent), and ``account_rid`` is emitted as a cross-database edge
    into the main schema.
    """
    resolved: list[Reference] = []
    with_pk = catalog.tables_with_pk

    for table_name, info in sorted(catalog.real_tables().items()):
        for column in info.fk_columns:
            if column == "account_rid":
                account = ENTITIES_BY_NAME["account"]
                resolved.append(
                    Reference(
                        from_table=table_name,
                        column=column,
                        to_entity="account",
                        to_db=account.db_key,
                        to_schema=main_schema,
                        to_table=account.table,
                        cross_db=True,
                        note="cross-DB",
                    )
                )
                continue

            if is_polymorphic(column):
                continue

            parent, note = resolve_parent_table(column, with_pk)
            if parent is None:
                continue

            resolved.append(
                Reference(
                    from_table=table_name,
                    column=column,
                    to_entity=TABLE_TO_ENTITY.get(parent),
                    to_db=catalog.db_key,
                    to_schema=catalog.schema,
                    to_table=parent,
                    note=note,
                )
            )

    return resolved


def unresolved_columns(catalog: SchemaCatalog) -> dict[str, list[str]]:
    """
    Foreign-key columns with no parent table, grouped by prefix.

    These are the input to deviation classification: a prefix seen in many
    tables is probably a shared lookup entity living elsewhere, while one seen
    once and closely resembling a real table is probably a typo.
    """
    with_pk = catalog.tables_with_pk
    grouped: dict[str, list[str]] = {}

    for table_name, info in catalog.real_tables().items():
        for column in info.fk_columns:
            if column == "account_rid" or is_polymorphic(column):
                continue
            parent, _ = resolve_parent_table(column, with_pk)
            if parent is None:
                grouped.setdefault(fk_prefix(column), []).append(table_name)

    return grouped


def classify_deviation(
    prefix: str,
    tables: list[str],
    known_tables: set[str] | frozenset[str],
) -> str:
    """
    Explain why a foreign-key column did not resolve.

    ``global-lookup``  seen across enough tables to be a shared entity
    ``typo``           closely resembles a real table name in this schema
    ``unknown``        neither — needs a human
    """
    import difflib

    if len(set(tables)) >= GLOBAL_LOOKUP_MIN_TABLES:
        return "global-lookup"

    for candidate in parent_candidates(prefix):
        matches = difflib.get_close_matches(
            candidate, list(known_tables), n=1, cutoff=TYPO_SIMILARITY_CUTOFF
        )
        if matches:
            return "typo"

    return "unknown"


class Fetcher(Protocol):
    """Minimal read interface, so this module never imports a driver."""

    def __call__(self, db_key: str, query: str, params: list | None = ...) -> list[tuple]: ...


CATALOG_QUERY = (
    "SELECT table_name, column_name FROM information_schema.columns "
    "WHERE table_schema = %s ORDER BY table_name, ordinal_position"
)

TENANT_SCHEMA_QUERY = (
    "SELECT nspname FROM pg_namespace "
    "WHERE nspname LIKE %s ESCAPE '\\' AND nspname NOT LIKE '%%backup%%' ORDER BY 1"
)


def load_catalog(fetch: Fetcher, db_key: str, schema: str) -> SchemaCatalog:
    """Introspect one schema into a :class:`SchemaCatalog`."""
    return SchemaCatalog.from_columns(db_key, schema, fetch(db_key, CATALOG_QUERY, [schema]))


def tenant_schemas(fetch: Fetcher) -> list[str]:
    """Every org tenant schema, backups excluded."""
    return [row[0] for row in fetch("orgdb", TENANT_SCHEMA_QUERY, [TENANT_SCHEMA_LIKE])]
