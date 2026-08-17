"""
Discovered data model, captured once and shared by every utility.

``datamodel`` holds the *conventions* — primary keys are ``rid``, foreign keys
are ``{prefix}_rid``, these columns are polymorphic. Those are rules and they do
not change when a database does.

What *does* change is the discovered model: which tenant schemas exist, which
tables are in them, which references actually resolve, and which columns deviate.
That is produced by the data-model analysis utility and consumed by everything
else, so re-running the analysis propagates a new model to every other script
without any of them re-introspecting or being edited.

The contract is a **snapshot**:

    analysis  →  build_snapshot()  →  store.save()      (producer, one utility)
    others    →  store.require()   →  ModelSnapshot     (consumers, everything)

Snapshots are per environment, immutable once written, and versioned. A consumer
that finds no snapshot, or one older than it is willing to trust, gets a
:class:`StaleModelError` telling it to re-run the analysis — never a silently
wrong model, which for a purge tool would mean deleting against a stale
understanding of the schema.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from .datamodel import (
    DEFAULT_MAIN_SCHEMA,
    Reference,
    SchemaCatalog,
    TableInfo,
    classify_deviation,
    load_catalog,
    references,
    tenant_schemas,
    unresolved_columns,
)
from .environments import Environment
from .errors import Trd365Error

#: Bumped when the snapshot file format changes incompatibly.
SNAPSHOT_FORMAT_VERSION = 1

#: Consumers default to refusing a model older than this.
DEFAULT_MAX_AGE = timedelta(days=7)


class StaleModelError(Trd365Error):
    """No usable data-model snapshot: absent, unreadable, or older than allowed."""


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------
# Serialisation of the datamodel types
# --------------------------------------------------------------------------


def _catalog_to_dict(catalog: SchemaCatalog) -> dict[str, Any]:
    return {
        "db_key": catalog.db_key,
        "schema": catalog.schema,
        "tables": {
            name: {"has_pk": info.has_pk, "fk_columns": list(info.fk_columns)}
            for name, info in sorted(catalog.tables.items())
        },
    }


def _catalog_from_dict(data: dict[str, Any]) -> SchemaCatalog:
    catalog = SchemaCatalog(db_key=data["db_key"], schema=data["schema"])
    for name, info in data.get("tables", {}).items():
        catalog.tables[name] = TableInfo(
            name=name,
            has_pk=bool(info.get("has_pk", False)),
            fk_columns=list(info.get("fk_columns", [])),
        )
    return catalog


def _reference_to_dict(ref: Reference) -> dict[str, Any]:
    return {
        "from_table": ref.from_table,
        "column": ref.column,
        "to_entity": ref.to_entity,
        "to_db": ref.to_db,
        "to_schema": ref.to_schema,
        "to_table": ref.to_table,
        "cross_db": ref.cross_db,
        "note": ref.note,
    }


def _reference_from_dict(data: dict[str, Any]) -> Reference:
    return Reference(**data)


# --------------------------------------------------------------------------
# The snapshot
# --------------------------------------------------------------------------


@dataclass
class SchemaModel:
    """The discovered model for one tenant schema."""

    schema: str
    catalog: SchemaCatalog
    references: list[Reference] = field(default_factory=list)
    #: Unresolved foreign-key prefix -> classification (typo / global-lookup / unknown).
    deviations: dict[str, str] = field(default_factory=dict)

    @property
    def table_names(self) -> set[str]:
        return set(self.catalog.real_tables())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "catalog": _catalog_to_dict(self.catalog),
            "references": [_reference_to_dict(r) for r in self.references],
            "deviations": dict(sorted(self.deviations.items())),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SchemaModel:
        return cls(
            schema=data["schema"],
            catalog=_catalog_from_dict(data["catalog"]),
            references=[_reference_from_dict(r) for r in data.get("references", [])],
            deviations=dict(data.get("deviations", {})),
        )


@dataclass
class ModelSnapshot:
    """
    One capture of the discovered data model for one environment.

    Immutable once stored. ``fingerprint`` is a content hash, so a consumer can
    tell whether the model actually changed without diffing it.
    """

    environment: str
    generated_at: str
    generated_by: str
    main_schema: str = DEFAULT_MAIN_SCHEMA
    schemas: dict[str, SchemaModel] = field(default_factory=dict)
    format_version: int = SNAPSHOT_FORMAT_VERSION
    notes: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- access

    @property
    def tenant_schemas(self) -> list[str]:
        return sorted(self.schemas)

    def schema(self, name: str) -> SchemaModel:
        try:
            return self.schemas[name]
        except KeyError:
            known = ", ".join(self.tenant_schemas) or "(none)"
            raise Trd365Error(
                f'Schema "{name}" is not in this model snapshot. Present: {known}.'
            ) from None

    def references_to(self, entity_name: str) -> list[Reference]:
        """Every reference pointing at an entity, across all schemas."""
        return [
            ref
            for model in self.schemas.values()
            for ref in model.references
            if ref.to_entity == entity_name
        ]

    def tables_referencing(self, schema: str, entity_name: str) -> list[str]:
        """
        Tables in one schema that reference an entity.

        This is what a purge needs: the set of tables to clear before the parent
        row can go, derived from the shared model rather than each tool's own
        idea of the schema.
        """
        return sorted(
            {
                ref.from_table
                for ref in self.schema(schema).references
                if ref.to_entity == entity_name
            }
        )

    @property
    def age(self) -> timedelta:
        return _now() - datetime.fromisoformat(self.generated_at)

    def is_stale(self, max_age: timedelta = DEFAULT_MAX_AGE) -> bool:
        return self.age > max_age

    # --------------------------------------------------------------- content

    @property
    def fingerprint(self) -> str:
        """Stable hash of the model content, ignoring when it was taken."""
        payload = json.dumps(
            {
                "main_schema": self.main_schema,
                "schemas": {n: m.to_dict() for n, m in sorted(self.schemas.items())},
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @property
    def version(self) -> str:
        """Sortable identity: when it was taken, plus what it contained."""
        stamp = self.generated_at.replace(":", "").replace("-", "").replace(".", "")
        return f"{stamp}-{self.fingerprint}"

    def summary(self) -> dict[str, int]:
        return {
            "schemas": len(self.schemas),
            "tables": sum(len(m.table_names) for m in self.schemas.values()),
            "references": sum(len(m.references) for m in self.schemas.values()),
            "deviations": sum(len(m.deviations) for m in self.schemas.values()),
        }

    # --------------------------------------------------------- serialisation

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "environment": self.environment,
            "generated_at": self.generated_at,
            "generated_by": self.generated_by,
            "main_schema": self.main_schema,
            "fingerprint": self.fingerprint,
            "notes": list(self.notes),
            "schemas": {n: m.to_dict() for n, m in sorted(self.schemas.items())},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelSnapshot:
        found = int(data.get("format_version", 0))
        if found != SNAPSHOT_FORMAT_VERSION:
            raise StaleModelError(
                f"Model snapshot is format version {found}, this build expects "
                f"{SNAPSHOT_FORMAT_VERSION}. Re-run the data-model analysis."
            )
        return cls(
            environment=data["environment"],
            generated_at=data["generated_at"],
            generated_by=data.get("generated_by", "unknown"),
            main_schema=data.get("main_schema", DEFAULT_MAIN_SCHEMA),
            format_version=found,
            notes=list(data.get("notes", [])),
            schemas={n: SchemaModel.from_dict(m) for n, m in data.get("schemas", {}).items()},
        )


# --------------------------------------------------------------------------
# Building one from a live database
# --------------------------------------------------------------------------


def build_snapshot(
    fetch,
    environment: Environment,
    *,
    generated_by: str,
    schemas: list[str] | None = None,
    main_schema: str = DEFAULT_MAIN_SCHEMA,
    on_schema=None,
) -> ModelSnapshot:
    """
    Introspect a live database into a snapshot.

    Called by the data-model analysis utility. ``schemas`` defaults to every
    tenant schema; pass a subset to refresh part of the model. ``on_schema`` is
    invoked with each schema name as it starts, for progress reporting.
    """
    names = tenant_schemas(fetch) if schemas is None else list(schemas)

    snapshot = ModelSnapshot(
        environment=environment.value,
        generated_at=_now().isoformat(),
        generated_by=generated_by,
        main_schema=main_schema,
    )

    for name in names:
        if on_schema is not None:
            on_schema(name)

        catalog = load_catalog(fetch, "orgdb", name)
        known = set(catalog.real_tables())
        deviations = {
            prefix: classify_deviation(prefix, tables, known)
            for prefix, tables in unresolved_columns(catalog).items()
        }
        snapshot.schemas[name] = SchemaModel(
            schema=name,
            catalog=catalog,
            references=references(catalog, main_schema=main_schema),
            deviations=deviations,
        )

    return snapshot


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


class ModelStore(Protocol):
    def save(self, snapshot: ModelSnapshot) -> str: ...
    def latest(self, environment: Environment) -> ModelSnapshot | None: ...
    def versions(self, environment: Environment) -> list[str]: ...


def default_model_dir() -> Path:
    """``$TRD365_MODEL_DIR`` if set, else ``~/.trd365/model``."""
    base = os.environ.get("TRD365_MODEL_DIR")
    return Path(base) if base else Path.home() / ".trd365" / "model"


class FileModelStore:
    """
    Snapshots as JSON files, one directory per environment.

    Writes are atomic (temp file then rename) so a consumer reading while the
    analysis is running never sees a half-written model. Old versions are kept,
    so a model change can be diffed after the fact.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_model_dir()

    def _dir(self, environment: Environment) -> Path:
        return self.root / environment.value

    def save(self, snapshot: ModelSnapshot) -> str:
        env = Environment.parse(snapshot.environment)
        directory = self._dir(env)
        directory.mkdir(parents=True, exist_ok=True)

        version = snapshot.version
        target = directory / f"{version}.json"

        handle, temp_name = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                fh.write(snapshot.to_json())
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

        # Pointer rewritten last: until it moves, consumers keep the old model.
        pointer = directory / "latest.json"
        handle, temp_name = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"version": version}, indent=2))
            os.replace(temp_name, pointer)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

        return version

    def versions(self, environment: Environment) -> list[str]:
        directory = self._dir(environment)
        if not directory.exists():
            return []
        return sorted(p.stem for p in directory.glob("*.json") if p.stem != "latest")

    def load(self, environment: Environment, version: str) -> ModelSnapshot:
        path = self._dir(environment) / f"{version}.json"
        if not path.exists():
            raise StaleModelError(f"No model snapshot {version} for {environment.value}.")
        return ModelSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def latest(self, environment: Environment) -> ModelSnapshot | None:
        directory = self._dir(environment)
        pointer = directory / "latest.json"

        if pointer.exists():
            try:
                version = json.loads(pointer.read_text(encoding="utf-8"))["version"]
                return self.load(environment, version)
            except (json.JSONDecodeError, KeyError, StaleModelError):
                pass  # fall back to the newest file on disk

        available = self.versions(environment)
        if not available:
            return None
        return self.load(environment, available[-1])


def require_model(
    store: ModelStore,
    environment: Environment,
    *,
    max_age: timedelta | None = DEFAULT_MAX_AGE,
    utility: str = "this utility",
) -> ModelSnapshot:
    """
    The current model for an environment, or a refusal explaining what to do.

    Consumers call this instead of introspecting. A missing or stale model is an
    error rather than a fallback: a purge running against an out-of-date
    understanding of the schema is exactly the failure this design exists to
    prevent.
    """
    snapshot = store.latest(environment)
    if snapshot is None:
        raise StaleModelError(
            f"{utility} needs a data-model snapshot for {environment.value}, and none exists.\n"
            f"Run the data-model analysis against {environment.value} first."
        )

    if max_age is not None and snapshot.is_stale(max_age):
        days = snapshot.age.days
        raise StaleModelError(
            f"{utility} found a data-model snapshot for {environment.value} that is "
            f"{days} day(s) old (limit {max_age.days}).\n"
            f"Re-run the data-model analysis, or pass a longer max_age if that is deliberate."
        )

    return snapshot


# --------------------------------------------------------------------------
# Change detection
# --------------------------------------------------------------------------


@dataclass
class SchemaDiff:
    schema: str
    added_tables: list[str] = field(default_factory=list)
    removed_tables: list[str] = field(default_factory=list)
    added_references: list[str] = field(default_factory=list)
    removed_references: list[str] = field(default_factory=list)
    added_deviations: list[str] = field(default_factory=list)
    resolved_deviations: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(
            [
                self.added_tables,
                self.removed_tables,
                self.added_references,
                self.removed_references,
                self.added_deviations,
                self.resolved_deviations,
            ]
        )


@dataclass
class ModelDiff:
    """What changed between two snapshots — the dashboard's schema-drift signal."""

    added_schemas: list[str] = field(default_factory=list)
    removed_schemas: list[str] = field(default_factory=list)
    schema_diffs: list[SchemaDiff] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added_schemas or self.removed_schemas or self.schema_diffs)

    def summary(self) -> str:
        if not self.changed:
            return "No change."
        parts = []
        if self.added_schemas:
            parts.append(f"{len(self.added_schemas)} schema(s) added")
        if self.removed_schemas:
            parts.append(f"{len(self.removed_schemas)} schema(s) removed")
        if self.schema_diffs:
            parts.append(f"{len(self.schema_diffs)} schema(s) changed")
        return "; ".join(parts) + "."


def _ref_key(ref: Reference) -> str:
    return f"{ref.from_table}.{ref.column}->{ref.to_schema}.{ref.to_table}"


def diff_snapshots(old: ModelSnapshot, new: ModelSnapshot) -> ModelDiff:
    """Compare two snapshots of the same environment."""
    old_names, new_names = set(old.schemas), set(new.schemas)

    diff = ModelDiff(
        added_schemas=sorted(new_names - old_names),
        removed_schemas=sorted(old_names - new_names),
    )

    for name in sorted(old_names & new_names):
        before, after = old.schemas[name], new.schemas[name]

        before_refs = {_ref_key(r) for r in before.references}
        after_refs = {_ref_key(r) for r in after.references}
        before_dev, after_dev = set(before.deviations), set(after.deviations)

        schema_diff = SchemaDiff(
            schema=name,
            added_tables=sorted(after.table_names - before.table_names),
            removed_tables=sorted(before.table_names - after.table_names),
            added_references=sorted(after_refs - before_refs),
            removed_references=sorted(before_refs - after_refs),
            added_deviations=sorted(after_dev - before_dev),
            resolved_deviations=sorted(before_dev - after_dev),
        )
        if schema_diff.changed:
            diff.schema_diffs.append(schema_diff)

    return diff
