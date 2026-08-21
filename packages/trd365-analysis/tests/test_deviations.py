"""
Classifying why a foreign-key column did not resolve.

The case these tests exist for is the one the legacy tree needed a whole second
script to fix: a shared entity that appears in only one or two tables *per
schema* looks like a typo to a per-schema classifier, and is obviously a shared
entity once you look at all forty schemas at once.
"""

from __future__ import annotations

import pytest
from trd365_core.datamodel import Reference, SchemaCatalog
from trd365_core.model_snapshot import ModelSnapshot, SchemaModel

from trd365_analysis import deviations as dev


def catalog(schema: str, tables: dict[str, list[str]]) -> SchemaCatalog:
    rows = [(name, column) for name, columns in tables.items() for column in columns]
    return SchemaCatalog.from_columns("orgdb", schema, rows)


def snapshot(schemas: dict[str, dict[str, list[str]]], deviations=None) -> ModelSnapshot:
    return ModelSnapshot(
        environment="dev",
        generated_at="2026-08-20T00:00:00+00:00",
        generated_by="test",
        schemas={
            name: SchemaModel(
                schema=name,
                catalog=catalog(name, tables),
                deviations=dict((deviations or {}).get(name, {})),
            )
            for name, tables in schemas.items()
        },
    )


# --------------------------------------------------------------- footprint


def test_footprint_counts_the_schema_table_pairs_a_prefix_appears_in():
    model = snapshot(
        {
            "trd365_1": {"a": ["rid", "widget_rid"], "b": ["rid", "widget_rid"]},
            "trd365_2": {"a": ["rid", "widget_rid"]},
        }
    )
    assert dev.footprint(model)["widget"] == {
        ("trd365_1", "a"),
        ("trd365_1", "b"),
        ("trd365_2", "a"),
    }


def test_a_prefix_that_resolves_is_not_a_deviation_at_all():
    model = snapshot({"trd365_1": {"widget": ["rid"], "a": ["rid", "widget_rid"]}})
    assert "widget" not in dev.footprint(model)


def test_known_table_names_pool_every_schema():
    # A tenant that happens not to have a table must not make every reference to
    # it look like a misspelling.
    model = snapshot(
        {"trd365_1": {"project": ["rid"]}, "trd365_2": {"resources": ["rid"]}}
    )
    assert dev.known_table_names(model) == {"project", "resources"}


# ---------------------------------------------------------------- classify


def test_a_polymorphic_column_is_explained_not_flagged():
    assert dev.classify("entity", set(), set()) == dev.POLYMORPHIC
    assert dev.classify("attach_to", set(), set()) == dev.POLYMORPHIC


def test_a_prefix_seen_across_enough_tables_is_a_shared_entity():
    tables = {("s1", "a"), ("s1", "b"), ("s1", "c")}
    assert dev.classify("widget", tables, set()) == dev.GLOBAL_LOOKUP


def test_a_rare_prefix_resembling_a_real_table_is_a_typo():
    assert dev.classify("projekt", {("s1", "a")}, {"project"}) == dev.TYPO


def test_a_rare_prefix_resembling_nothing_needs_a_person():
    assert dev.classify("zzqqxx", {("s1", "a")}, {"project"}) == dev.UNKNOWN


def test_the_same_table_name_in_many_schemas_is_one_piece_of_evidence():
    # Forty tenants carrying the same table is the model repeated forty times,
    # not forty independent tables naming the prefix. Counting rows here would
    # make every rare prefix look global as soon as the estate grew.
    forty_schemas = {(f"trd365_{i}", "a") for i in range(40)}
    assert dev.classify("projekt", forty_schemas, {"project"}) == dev.TYPO


# ----------------------------------------------------------------- apply_to


def test_the_headline_case_a_shared_entity_mislabelled_as_a_typo():
    # 'projec' appears in one table per schema, so a per-schema classifier sees
    # a single rare occurrence that closely resembles 'project' and calls it a
    # typo. Across five schemas it is plainly a shared reference.
    schemas = {
        f"trd365_{i}": {"project": ["rid"], f"table_{i}": ["rid", "projec_rid"]}
        for i in range(5)
    }
    model = snapshot(schemas, deviations={name: {"projec": dev.TYPO} for name in schemas})

    changes = dev.apply_to(model)

    assert all(m.deviations["projec"] == dev.GLOBAL_LOOKUP for m in model.schemas.values())
    assert len(changes) == 5
    assert all(change.is_downgrade for change in changes)


def test_a_real_typo_survives_the_cross_schema_pass():
    schemas = {
        "trd365_1": {"project": ["rid"], "a": ["rid", "projekt_rid"]},
        "trd365_2": {"project": ["rid"]},
    }
    model = snapshot(schemas)
    dev.apply_to(model)
    assert model.schemas["trd365_1"].deviations["projekt"] == dev.TYPO


def test_apply_to_reports_only_what_actually_changed():
    schemas = {"trd365_1": {"project": ["rid"], "a": ["rid", "projekt_rid"]}}
    model = snapshot(schemas, deviations={"trd365_1": {"projekt": dev.TYPO}})
    assert dev.apply_to(model) == []


def test_apply_to_fills_in_a_snapshot_that_had_no_classifications():
    model = snapshot({"trd365_1": {"project": ["rid"], "a": ["rid", "projekt_rid"]}})
    changes = dev.apply_to(model)

    assert model.schemas["trd365_1"].deviations == {"projekt": dev.TYPO}
    # Nothing "changed" — there was no previous answer to contradict.
    assert changes == []


@pytest.mark.parametrize("min_tables", [2, 5])
def test_the_global_lookup_threshold_is_adjustable(min_tables):
    schemas = {
        "trd365_1": {"project": ["rid"], "a": ["rid", "projec_rid"], "b": ["rid", "projec_rid"]}
    }
    model = snapshot(schemas)
    dev.apply_to(model, min_tables=min_tables)

    expected = dev.GLOBAL_LOOKUP if min_tables == 2 else dev.TYPO
    assert model.schemas["trd365_1"].deviations["projec"] == expected


# -------------------------------------------------------------- occurrences


def test_occurrences_names_every_affected_column():
    schemas = {
        "trd365_1": {"project": ["rid"], "a": ["rid", "projekt_rid"]},
        "trd365_2": {"project": ["rid"], "b": ["rid", "projekt_rid"]},
    }
    model = snapshot(schemas)
    dev.apply_to(model)

    assert dev.occurrences(model, dev.TYPO) == [
        ("trd365_1", "a", "projekt_rid"),
        ("trd365_2", "b", "projekt_rid"),
    ]


def test_only_typos_are_treated_as_actionable():
    # The other three classifications explain a name; they are not defects, and
    # presenting them as such is how a report gets ignored.
    assert dev.ACTIONABLE == (dev.TYPO,)


class TestSharedLookupsAreNotDeviations:
    """
    The report must not present correct cross-database references as problems.

    Against production this pass reported 1,650 deviations, 1,165 of them
    "unknown", while the snapshot itself had already resolved those columns into
    the main schema. status appeared 691 times, country 461, currency 323 — all
    real tables in maindb.trd365. A health signal that is mostly correct
    references is not a health signal, and the genuine problems were invisible
    underneath them.
    """

    @staticmethod
    def with_shared_lookup():
        """A snapshot whose only unresolved-looking column resolves into main."""
        model = snapshot({"trd365_1": {"project": ["rid", "status_rid", "projekt_rid"]}})
        schema = model.schemas["trd365_1"]
        schema.references = [
            Reference(
                from_table="project",
                column="status_rid",
                to_entity=None,
                to_db="maindb",
                to_schema=model.main_schema,
                to_table="status",
                cross_db=True,
                note="cross-DB shared lookup",
            )
        ]
        return model

    def test_the_main_tables_come_from_the_snapshots_own_edges(self):
        model = self.with_shared_lookup()
        assert dev.main_schema_tables(model) == {"status"}

    def test_a_shared_lookup_is_not_classified_at_all(self):
        model = self.with_shared_lookup()
        classified = dev.classify_all(model)["trd365_1"]

        assert "status" not in classified, (
            "status resolves into the main schema; reporting it as a deviation "
            "is what buried the real findings"
        )
        assert "projekt" in classified, "a genuine typo must still be reported"

    def test_the_footprint_excludes_shared_lookups(self):
        assert "status" not in dev.footprint(self.with_shared_lookup())

    def test_a_snapshot_with_no_cross_db_edges_behaves_as_before(self):
        # An older snapshot, or one built without a main catalog.
        model = snapshot({"trd365_1": {"project": ["rid", "status_rid"]}})
        assert dev.main_schema_tables(model) == set()
        assert "status" in dev.classify_all(model)["trd365_1"]
