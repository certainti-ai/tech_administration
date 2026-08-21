"""
Why a foreign-key column did not resolve to a parent table.

The legacy classifier ran per schema, and the legacy tree carried a separate
post-processor (`reclassify_deviations.py`) whose docstring explains why:

    The per-schema classifier in model_analysis.py can mislabel a global-lookup
    reference as a typo when that reference happens to appear in only 1-2 tables
    in a single schema.

That is right, and it is not really a post-processing problem — it is a scope
problem. Tenant schemas are near-identical copies of one model, so the evidence
for "this prefix is a shared entity" is spread across all of them. A snapshot
already holds every schema, so the classification is done here across the whole
snapshot and written back into it. Consumers then read the good answer, and
nobody has to remember to run a second script over a pair of CSVs.

Four classifications, unchanged from the original:

``polymorphic``    the column names its parent's *type* in a companion column,
                   so there is no single parent. By design, not a fault.
``global-lookup``  the prefix appears across enough tables to be a shared
                   entity whose parent table lives in another schema.
``typo``           a rare prefix that closely resembles a real table name.
                   This is the one a human should act on.
``unknown``        rare, and resembles nothing. Needs a person to look.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from trd365_core.datamodel import (
    GLOBAL_LOOKUP_MIN_TABLES,
    TYPO_SIMILARITY_CUTOFF,
    fk_prefix,
    is_polymorphic,
    parent_candidates,
    unresolved_columns,
)
from trd365_core.model_snapshot import ModelSnapshot

GLOBAL_LOOKUP = "global-lookup"
TYPO = "typo"
POLYMORPHIC = "polymorphic"
UNKNOWN = "unknown"

#: Only this one is a defect. The others are explanations.
ACTIONABLE = (TYPO,)


@dataclass(frozen=True)
class Reclassification:
    """One prefix whose classification changed once every schema was considered."""

    schema: str
    prefix: str
    was: str
    now: str

    @property
    def is_downgrade(self) -> bool:
        """A false alarm withdrawn — the common and valuable direction."""
        return self.was in ACTIONABLE and self.now not in ACTIONABLE


def main_schema_tables(snapshot: ModelSnapshot) -> set[str]:
    """
    The main-schema tables this snapshot actually references.

    Derived from the snapshot's own cross-database edges rather than plumbed in,
    so no extra argument has to reach every caller and an older snapshot without
    those edges simply yields an empty set and the previous behaviour.
    """
    return {
        ref.to_table
        for model in snapshot.schemas.values()
        for ref in model.references
        if ref.cross_db and ref.to_schema == snapshot.main_schema
    }


def unresolved_in(model, main_tables: set[str] | frozenset[str] = frozenset()):
    """
    A schema's unresolved prefixes and the tables they appear in.

    ``main_tables`` is what keeps this honest. The catalog knows only its own
    schema, so on its own it reports every reference to a shared lookup — status,
    country, currency and dozens more, which live in the main schema — as a
    prefix with no parent. Against production that was 1,165 prefixes presented
    as model problems when each one is a correct cross-database reference.
    """
    return unresolved_columns(model.catalog, main_tables)


def footprint(snapshot: ModelSnapshot) -> dict[str, set[tuple[str, str]]]:
    """
    Unresolved prefix -> the ``(schema, table)`` pairs it appears in.

    Counting distinct pairs rather than tables matters: the same table name in
    forty tenant schemas is one piece of evidence about the model repeated forty
    times, but forty *different* tables naming the same prefix is strong
    evidence that the prefix is a real shared entity.
    """
    seen: dict[str, set[tuple[str, str]]] = defaultdict(set)
    main_tables = main_schema_tables(snapshot)
    for schema_name, model in snapshot.schemas.items():
        for prefix, tables in unresolved_in(model, main_tables).items():
            for table in tables:
                seen[prefix].add((schema_name, table))
    return dict(seen)


def known_table_names(snapshot: ModelSnapshot) -> set[str]:
    """
    Every table with a primary key, across every schema in the snapshot.

    The vocabulary a typo is judged against. Union rather than per-schema,
    because a tenant that happens not to have a table would otherwise make every
    reference to it look like a misspelling.
    """
    return {name for model in snapshot.schemas.values() for name in model.catalog.tables_with_pk}


def classify(
    prefix: str,
    tables: set[tuple[str, str]],
    known: set[str],
    *,
    min_tables: int = GLOBAL_LOOKUP_MIN_TABLES,
) -> str:
    """Classify one unresolved prefix against the whole-snapshot evidence."""
    import difflib

    if is_polymorphic(prefix) or is_polymorphic(prefix + "_rid"):
        return POLYMORPHIC

    if len({table for _schema, table in tables}) >= min_tables:
        return GLOBAL_LOOKUP

    for candidate in parent_candidates(prefix):
        if difflib.get_close_matches(
            candidate, list(known), n=1, cutoff=TYPO_SIMILARITY_CUTOFF
        ):
            return TYPO

    return UNKNOWN


def classify_all(
    snapshot: ModelSnapshot, *, min_tables: int = GLOBAL_LOOKUP_MIN_TABLES
) -> dict[str, dict[str, str]]:
    """``{schema: {prefix: classification}}`` using cross-schema evidence."""
    counts = footprint(snapshot)
    known = known_table_names(snapshot)
    main_tables = main_schema_tables(snapshot)

    result: dict[str, dict[str, str]] = {}
    for schema_name, model in snapshot.schemas.items():
        result[schema_name] = {
            prefix: classify(prefix, counts.get(prefix, set()), known, min_tables=min_tables)
            for prefix in unresolved_in(model, main_tables)
        }
    return result


def apply_to(
    snapshot: ModelSnapshot, *, min_tables: int = GLOBAL_LOOKUP_MIN_TABLES
) -> list[Reclassification]:
    """
    Rewrite the snapshot's deviations in place; return everything that changed.

    Called before the snapshot is saved, so the stored model carries the
    cross-schema answer and every consumer of it gets that for free.
    """
    updated = classify_all(snapshot, min_tables=min_tables)
    changes: list[Reclassification] = []

    for schema_name, model in snapshot.schemas.items():
        fresh = updated[schema_name]
        for prefix, classification in sorted(fresh.items()):
            previous = model.deviations.get(prefix)
            if previous is not None and previous != classification:
                changes.append(
                    Reclassification(
                        schema=schema_name, prefix=prefix, was=previous, now=classification
                    )
                )
        model.deviations = fresh

    return changes


def occurrences(snapshot: ModelSnapshot, classification: str) -> list[tuple[str, str, str]]:
    """``(schema, table, column)`` for every column with this classification."""
    found: list[tuple[str, str, str]] = []
    for schema_name, model in snapshot.schemas.items():
        for table, info in model.catalog.real_tables().items():
            for column in info.fk_columns:
                prefix = fk_prefix(column)
                if model.deviations.get(prefix) == classification:
                    found.append((schema_name, table, column))
    return sorted(found)
