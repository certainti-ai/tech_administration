"""
The producer/consumer contract for the discovered data model.

Re-running the analysis must propagate a new model to every other utility,
and a consumer must never silently run against a stale one.
"""

from datetime import UTC, datetime, timedelta

import pytest

from trd365_core.environments import Environment
from trd365_core.errors import Trd365Error
from trd365_core.model_snapshot import (
    SNAPSHOT_FORMAT_VERSION,
    FileModelStore,
    ModelSnapshot,
    StaleModelError,
    build_snapshot,
    diff_snapshots,
    require_model,
)

# A small tenant schema: project is a parent, task references it and the account
# in the main database, and widget_rid resolves to nothing.
COLUMNS = {
    "trd365_00042": [
        ("project", "rid"),
        ("project", "name"),
        ("task", "rid"),
        ("task", "project_rid"),
        ("task", "account_rid"),
        ("task", "widget_rid"),
    ]
}


def fetcher(columns=None, schemas=None):
    """
    A catalog reader over a ``{schema: [(table, column), …]}`` mapping.

    ``schemas`` defaults to the tenant schemas in ``columns``, so the main schema
    can be supplied without being analysed as a tenant.
    """
    columns = COLUMNS if columns is None else columns
    schemas = list(columns) if schemas is None else schemas

    def fetch(db_key, query, params=None):
        if "pg_namespace" in query:
            return [(name,) for name in schemas]
        # A schema with nothing in it returns no rows, which is what Postgres
        # does; raising here would make "no main schema" look like a bug.
        return list(columns.get(params[0], []))

    return fetch


def build(columns=None, env=Environment.PROD, **kwargs):
    return build_snapshot(fetcher(columns), env, generated_by="test", **kwargs)


class TestBuilding:
    def test_captures_every_tenant_schema(self):
        snapshot = build()
        assert snapshot.tenant_schemas == ["trd365_00042"]
        assert snapshot.environment == "prod"
        assert snapshot.generated_by == "test"

    def test_captures_tables_and_references(self):
        model = build().schema("trd365_00042")
        assert "project" in model.table_names
        keys = {(r.from_table, r.column, r.to_table) for r in model.references}
        assert ("task", "project_rid", "project") in keys
        assert ("task", "account_rid", "account") in keys

    def test_records_the_cross_database_account_edge(self):
        refs = build().references_to("account")
        assert len(refs) == 1
        assert refs[0].cross_db is True
        assert refs[0].to_db == "maindb"

    def test_classifies_unresolved_columns_as_deviations(self):
        assert "widget" in build().schema("trd365_00042").deviations

    def test_can_refresh_a_subset_of_schemas(self):
        columns = dict(COLUMNS, trd365_00099=[("project", "rid")])
        snapshot = build(columns, schemas=["trd365_00099"])
        assert snapshot.tenant_schemas == ["trd365_00099"]

    def test_reports_progress_per_schema(self):
        seen = []
        build_snapshot(fetcher(), Environment.DEV, generated_by="t", on_schema=seen.append)
        assert seen == ["trd365_00042"]

    def test_summary_counts_the_model(self):
        summary = build().summary()
        assert summary["schemas"] == 1
        assert summary["references"] == 2
        assert summary["deviations"] == 1


class TestConsumerQueries:
    def test_tables_referencing_an_entity(self):
        # What a purge needs: which tables to clear before the parent can go.
        snapshot = build()
        assert snapshot.tables_referencing("trd365_00042", "project") == ["task"]

    def test_unknown_schema_names_the_ones_present(self):
        with pytest.raises(Trd365Error, match="trd365_00042"):
            build().schema("trd365_99999")


class TestFingerprint:
    def test_same_model_produces_the_same_fingerprint(self):
        assert build().fingerprint == build().fingerprint

    def test_fingerprint_ignores_when_it_was_taken(self):
        first = build()
        second = build()
        second.generated_at = "2020-01-01T00:00:00+00:00"
        assert first.fingerprint == second.fingerprint

    def test_a_changed_model_changes_the_fingerprint(self):
        changed = dict(COLUMNS)
        changed["trd365_00042"] = COLUMNS["trd365_00042"] + [("invoice", "rid")]
        assert build().fingerprint != build(changed).fingerprint

    def test_version_sorts_chronologically(self):
        older = build()
        older.generated_at = "2026-01-01T00:00:00+00:00"
        newer = build()
        newer.generated_at = "2026-06-01T00:00:00+00:00"
        assert older.version < newer.version


class TestSerialisation:
    def test_round_trips(self):
        original = build()
        restored = ModelSnapshot.from_dict(original.to_dict())

        assert restored.tenant_schemas == original.tenant_schemas
        assert restored.fingerprint == original.fingerprint
        model = restored.schema("trd365_00042")
        assert model.catalog.tables["project"].has_pk
        assert {r.to_table for r in model.references} == {"project", "account"}
        assert model.deviations == original.schema("trd365_00042").deviations

    def test_an_incompatible_format_version_is_refused(self):
        data = build().to_dict()
        data["format_version"] = SNAPSHOT_FORMAT_VERSION + 1
        with pytest.raises(StaleModelError, match="Re-run the data-model analysis"):
            ModelSnapshot.from_dict(data)


class TestFileStore:
    def test_save_then_latest_returns_it(self, tmp_path):
        store = FileModelStore(tmp_path)
        version = store.save(build())

        latest = store.latest(Environment.PROD)
        assert latest is not None
        assert latest.version == version

    def test_environments_are_kept_apart(self, tmp_path):
        store = FileModelStore(tmp_path)
        store.save(build(env=Environment.PROD))

        assert store.latest(Environment.PROD) is not None
        assert store.latest(Environment.DEV) is None

    def test_rerunning_the_analysis_propagates_the_new_model(self, tmp_path):
        """The core requirement: consumers pick up a refreshed model."""
        store = FileModelStore(tmp_path)
        store.save(build())
        assert "invoice" not in store.latest(Environment.PROD).schema("trd365_00042").table_names

        changed = dict(COLUMNS)
        changed["trd365_00042"] = COLUMNS["trd365_00042"] + [("invoice", "rid")]
        store.save(build(changed))

        # A consumer reading now sees the new model, with no code change.
        assert "invoice" in store.latest(Environment.PROD).schema("trd365_00042").table_names

    def test_previous_versions_are_kept(self, tmp_path):
        store = FileModelStore(tmp_path)
        first = build()
        first.generated_at = "2026-01-01T00:00:00+00:00"
        store.save(first)

        changed = dict(COLUMNS)
        changed["trd365_00042"] = COLUMNS["trd365_00042"] + [("invoice", "rid")]
        second = build(changed)
        second.generated_at = "2026-06-01T00:00:00+00:00"
        store.save(second)

        assert len(store.versions(Environment.PROD)) == 2

    def test_an_old_version_can_be_loaded_by_name(self, tmp_path):
        store = FileModelStore(tmp_path)
        version = store.save(build())
        assert store.load(Environment.PROD, version).fingerprint == build().fingerprint

    def test_loading_an_unknown_version_is_an_error(self, tmp_path):
        with pytest.raises(StaleModelError):
            FileModelStore(tmp_path).load(Environment.PROD, "nope")

    def test_a_corrupt_pointer_falls_back_to_the_newest_file(self, tmp_path):
        store = FileModelStore(tmp_path)
        store.save(build())
        (tmp_path / "prod" / "latest.json").write_text("{ not json")

        assert store.latest(Environment.PROD) is not None

    def test_no_temp_files_are_left_behind(self, tmp_path):
        store = FileModelStore(tmp_path)
        store.save(build())
        assert list((tmp_path / "prod").glob("*.tmp")) == []


class TestRequireModel:
    def test_returns_the_current_model(self, tmp_path):
        store = FileModelStore(tmp_path)
        store.save(build())
        assert require_model(store, Environment.PROD) is not None

    def test_a_missing_model_says_to_run_the_analysis(self, tmp_path):
        store = FileModelStore(tmp_path)
        with pytest.raises(StaleModelError) as excinfo:
            require_model(store, Environment.DEV, utility="purge-account")
        message = str(excinfo.value)
        assert "purge-account" in message
        assert "data-model analysis" in message
        assert "dev" in message

    def test_a_stale_model_is_refused(self, tmp_path):
        """
        A purge running against an out-of-date schema is the failure this
        whole design exists to prevent, so staleness is an error not a warning.
        """
        store = FileModelStore(tmp_path)
        old = build()
        old.generated_at = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        store.save(old)

        with pytest.raises(StaleModelError, match="30 day"):
            require_model(store, Environment.PROD, max_age=timedelta(days=7))

    def test_staleness_can_be_waived_deliberately(self, tmp_path):
        store = FileModelStore(tmp_path)
        old = build()
        old.generated_at = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        store.save(old)

        assert require_model(store, Environment.PROD, max_age=None) is not None

    def test_a_fresh_model_is_not_stale(self, tmp_path):
        store = FileModelStore(tmp_path)
        store.save(build())
        assert not store.latest(Environment.PROD).is_stale(timedelta(days=7))


class TestDiff:
    def test_identical_snapshots_show_no_change(self):
        diff = diff_snapshots(build(), build())
        assert not diff.changed
        assert diff.summary() == "No change."

    def test_detects_an_added_table(self):
        changed = dict(COLUMNS)
        changed["trd365_00042"] = COLUMNS["trd365_00042"] + [("invoice", "rid")]
        diff = diff_snapshots(build(), build(changed))

        assert diff.changed
        assert diff.schema_diffs[0].added_tables == ["invoice"]

    def test_detects_a_removed_table(self):
        reduced = {"trd365_00042": [("project", "rid")]}
        diff = diff_snapshots(build(), build(reduced))
        assert "task" in diff.schema_diffs[0].removed_tables

    def test_detects_added_and_removed_schemas(self):
        with_extra = dict(COLUMNS, trd365_00099=[("project", "rid")])
        added = diff_snapshots(build(), build(with_extra))
        assert added.added_schemas == ["trd365_00099"]

        removed = diff_snapshots(build(with_extra), build())
        assert removed.removed_schemas == ["trd365_00099"]

    def test_detects_a_new_reference(self):
        changed = dict(COLUMNS)
        changed["trd365_00042"] = COLUMNS["trd365_00042"] + [("note", "rid"), ("note", "task_rid")]
        diff = diff_snapshots(build(), build(changed))
        assert any("note.task_rid" in ref for ref in diff.schema_diffs[0].added_references)

    def test_detects_a_deviation_being_resolved(self):
        # Adding the missing parent table turns widget_rid from a deviation
        # into a resolved reference.
        fixed = dict(COLUMNS)
        fixed["trd365_00042"] = COLUMNS["trd365_00042"] + [("widget", "rid")]
        diff = diff_snapshots(build(), build(fixed))
        assert diff.schema_diffs[0].resolved_deviations == ["widget"]

    def test_summary_describes_the_change(self):
        changed = dict(COLUMNS)
        changed["trd365_00042"] = COLUMNS["trd365_00042"] + [("invoice", "rid")]
        assert "1 schema(s) changed" in diff_snapshots(build(), build(changed)).summary()
