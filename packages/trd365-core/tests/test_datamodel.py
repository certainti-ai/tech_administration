"""The data model conventions every utility relies on."""

import pytest

from trd365_core import datamodel as dm
from trd365_core.errors import DataModelError


class TestConventions:
    def test_the_four_primary_entities_are_defined(self):
        assert {e.name for e in dm.PRIMARY_ENTITIES} == {"account", "resource", "project", "case"}

    def test_account_lives_in_main_and_is_cross_database(self):
        account = dm.entity("account")
        assert account.db_key == "maindb"
        assert account.tenant_scoped is False
        assert account.is_cross_db is True

    def test_org_entities_are_tenant_scoped(self):
        for name in ("project", "resource", "case"):
            assert dm.entity(name).db_key == "orgdb"
            assert dm.entity(name).tenant_scoped is True

    def test_pluralised_table_names_are_recorded(self):
        # The irregularity that trips people up: the entity is singular, the
        # table is plural, and the foreign key uses the singular.
        assert dm.entity("resource").table == "resources"
        assert dm.entity("case").table == "cases"
        assert dm.entity("resource").fk_column == "resource_rid"
        assert dm.entity("case").fk_column == "case_rid"

    def test_project_is_not_pluralised(self):
        assert dm.entity("project").table == "project"

    def test_unknown_entity_names_itself_and_the_alternatives(self):
        with pytest.raises(DataModelError, match="account"):
            dm.entity("accounts")


class TestForeignKeyColumns:
    def test_recognises_rid_columns(self):
        assert dm.is_fk_column("project_rid")
        assert not dm.is_fk_column("rid")
        assert not dm.is_fk_column("name")

    def test_prefix_strips_the_suffix(self):
        assert dm.fk_prefix("project_fiscal_rid") == "project_fiscal"

    def test_prefix_rejects_non_foreign_keys(self):
        with pytest.raises(DataModelError):
            dm.fk_prefix("name")


class TestPolymorphic:
    @pytest.mark.parametrize(
        "column",
        ["entity_rid", "attach_to", "related_to_rid", "reference_rid", "parent_rid", "source_rid"],
    )
    def test_known_polymorphic_columns(self, column):
        assert dm.is_polymorphic(column)

    def test_ordinary_foreign_keys_are_not_polymorphic(self):
        assert not dm.is_polymorphic("project_rid")
        assert not dm.is_polymorphic("account_rid")

    def test_non_foreign_key_columns_are_not_polymorphic(self):
        assert not dm.is_polymorphic("created_at")


class TestBackupTables:
    @pytest.mark.parametrize(
        "name", ["backup_project", "bak_project", "project_backup_2024", "project_bak_01"]
    )
    def test_detects_backup_tables(self, name):
        assert dm.is_backup_table(name)

    def test_leaves_real_tables_alone(self):
        assert not dm.is_backup_table("project")
        assert not dm.is_backup_table("resources")


class TestParentResolution:
    def test_exact_match_wins(self):
        table, note = dm.resolve_parent_table("project_rid", {"project", "projects"})
        assert table == "project"
        assert note == ""

    def test_falls_back_to_the_plural_and_says_so(self):
        table, note = dm.resolve_parent_table("resource_rid", {"resources"})
        assert table == "resources"
        assert note == "plural:resource->resources"

    def test_handles_the_es_plural(self):
        table, _ = dm.resolve_parent_table("case_rid", {"cases"})
        assert table == "cases"

    def test_handles_the_y_to_ies_plural(self):
        table, note = dm.resolve_parent_table("company_rid", {"companies"})
        assert table == "companies"
        assert "companies" in note

    def test_returns_none_when_nothing_matches(self):
        table, note = dm.resolve_parent_table("widget_rid", {"project"})
        assert table is None
        assert note == ""


def catalog_from(rows, schema="trd365_00042", db_key="orgdb"):
    return dm.SchemaCatalog.from_columns(db_key, schema, rows)


class TestSchemaCatalog:
    def test_builds_tables_and_marks_primary_keys(self):
        catalog = catalog_from(
            [("project", "rid"), ("project", "name"), ("task", "rid"), ("task", "project_rid")]
        )
        assert catalog.tables["project"].has_pk
        assert catalog.tables["task"].fk_columns == ["project_rid"]
        assert catalog.tables_with_pk == frozenset({"project", "task"})

    def test_a_table_without_rid_is_not_a_parent_candidate(self):
        catalog = catalog_from([("audit_log", "message")])
        assert catalog.tables_with_pk == frozenset()

    def test_real_tables_excludes_backups(self):
        catalog = catalog_from([("project", "rid"), ("backup_project", "rid")])
        assert set(catalog.real_tables()) == {"project"}


class TestReferences:
    def test_resolves_within_the_schema(self):
        catalog = catalog_from([("project", "rid"), ("task", "rid"), ("task", "project_rid")])
        refs = dm.references(catalog)
        assert len(refs) == 1
        assert refs[0].from_table == "task"
        assert refs[0].to_table == "project"
        assert refs[0].to_entity == "project"
        assert refs[0].cross_db is False

    def test_account_rid_becomes_a_cross_database_edge(self):
        catalog = catalog_from([("project", "rid"), ("project", "account_rid")])
        refs = dm.references(catalog, main_schema="trd365")
        assert len(refs) == 1
        ref = refs[0]
        assert ref.cross_db is True
        assert ref.to_db == "maindb"
        assert ref.to_schema == "trd365"
        assert ref.to_table == "account"

    def test_account_edge_is_emitted_even_with_no_local_parent(self):
        # account lives in another database, so it will never be in this catalog.
        catalog = catalog_from([("task", "rid"), ("task", "account_rid")])
        assert len(dm.references(catalog)) == 1

    def test_polymorphic_columns_are_skipped(self):
        catalog = catalog_from([("note", "rid"), ("note", "entity_rid"), ("note", "parent_rid")])
        assert dm.references(catalog) == []

    def test_backup_tables_contribute_no_references(self):
        catalog = catalog_from(
            [("project", "rid"), ("backup_task", "rid"), ("backup_task", "project_rid")]
        )
        assert dm.references(catalog) == []

    def test_pluralised_resolution_is_reported_in_the_note(self):
        catalog = catalog_from([("resources", "rid"), ("task", "rid"), ("task", "resource_rid")])
        ref = dm.references(catalog)[0]
        assert ref.to_table == "resources"
        assert ref.to_entity == "resource"
        assert ref.note == "plural:resource->resources"


class TestUnresolved:
    def test_groups_unresolved_columns_by_prefix(self):
        catalog = catalog_from(
            [("a", "rid"), ("a", "widget_rid"), ("b", "rid"), ("b", "widget_rid")]
        )
        assert dm.unresolved_columns(catalog) == {"widget": ["a", "b"]}

    def test_resolved_and_polymorphic_columns_are_not_reported(self):
        catalog = catalog_from(
            [("project", "rid"), ("t", "rid"), ("t", "project_rid"), ("t", "entity_rid")]
        )
        assert dm.unresolved_columns(catalog) == {}


class TestDeviationClassification:
    def test_widely_used_prefix_is_a_global_lookup(self):
        assert dm.classify_deviation("country", ["a", "b", "c"], {"project"}) == "global-lookup"

    def test_near_miss_of_a_real_table_is_a_typo(self):
        assert dm.classify_deviation("porject", ["a"], {"project"}) == "typo"

    def test_otherwise_unknown(self):
        assert dm.classify_deviation("zzzz", ["a"], {"project"}) == "unknown"


class TestIntrospection:
    def test_load_catalog_uses_the_information_schema_query(self):
        seen = {}

        def fetch(db_key, query, params=None):
            seen["db_key"] = db_key
            seen["params"] = params
            return [("project", "rid")]

        catalog = dm.load_catalog(fetch, "orgdb", "trd365_00042")
        assert seen["db_key"] == "orgdb"
        assert seen["params"] == ["trd365_00042"]
        assert catalog.schema == "trd365_00042"
        assert catalog.tables["project"].has_pk

    def test_tenant_schemas_excludes_backups_via_the_query(self):
        def fetch(db_key, query, params=None):
            assert db_key == "orgdb"
            assert "NOT LIKE" in query
            assert params == [dm.TENANT_SCHEMA_LIKE]
            return [("trd365_00042",), ("trd365_00099",)]

        assert dm.tenant_schemas(fetch) == ["trd365_00042", "trd365_00099"]
