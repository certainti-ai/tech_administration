"""
The checkpoint is what makes a half-finished purge recoverable.

Its hardest requirement is not durability but *ordering*: the id-sets are read
before anything is deleted, and once the deletion starts they cannot be read
again. A checkpoint that loses them leaves a run that can never be finished.
"""

from __future__ import annotations

import json

import pytest

from trd365_data_purge.checkpoint import Checkpoint, CheckpointStore, default_state_dir


@pytest.fixture
def store(tmp_path):
    return CheckpointStore(tmp_path)


def sample(**overrides) -> Checkpoint:
    values = {
        "entity": "account",
        "entity_rid": "ACCT-1",
        "environment": "dev",
        "run_id": "run-1",
    }
    values.update(overrides)
    return Checkpoint(**values)


def test_default_state_dir_honours_the_environment_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("TRD365_STATE_DIR", str(tmp_path / "state"))
    assert default_state_dir() == tmp_path / "state"


def test_default_state_dir_falls_back_to_the_home_directory(monkeypatch):
    monkeypatch.delenv("TRD365_STATE_DIR", raising=False)
    assert default_state_dir().parts[-2:] == (".trd365", "state")


def test_a_saved_checkpoint_comes_back_intact(store):
    checkpoint = sample(
        id_sets={"project_fiscal": ["f1", "f2"]},
        completed={"org_delete": ["cases"]},
        metrics={"org_delete": {"cases": {"deleted": 3}}},
    )
    store.save(checkpoint)

    loaded = store.load("dev", "account", "ACCT-1")
    assert loaded is not None
    assert loaded.id_sets == {"project_fiscal": ["f1", "f2"]}
    assert loaded.completed == {"org_delete": ["cases"]}
    assert loaded.metrics["org_delete"]["cases"]["deleted"] == 3


def test_checkpoints_are_separated_by_environment(store):
    store.save(sample(environment="dev"))
    assert store.load("prod", "account", "ACCT-1") is None


def test_nothing_saved_means_nothing_to_resume(store):
    assert store.load("dev", "account", "never-run") is None


def test_a_rid_cannot_escape_the_state_directory(store, tmp_path):
    path = store.path_for("dev", "account", "../../etc/passwd")
    assert tmp_path in path.parents
    assert ".." not in path.parts


def test_a_corrupt_checkpoint_is_ignored_rather_than_fatal(store):
    path = store.path_for("dev", "account", "ACCT-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    # Starting over is safe: the purge is idempotent per table, and refusing to
    # run would leave an operator with a half-purged account and no way forward.
    assert store.load("dev", "account", "ACCT-1") is None


def test_an_unknown_field_from_a_newer_version_is_dropped_not_fatal(store):
    path = store.path_for("dev", "account", "ACCT-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "entity": "account",
                "entity_rid": "ACCT-1",
                "environment": "dev",
                "run_id": "run-1",
                "invented_later": True,
            }
        ),
        encoding="utf-8",
    )
    loaded = store.load("dev", "account", "ACCT-1")
    assert loaded is not None and loaded.run_id == "run-1"


def test_saving_leaves_no_temporary_files_behind(store):
    store.save(sample())
    store.save(sample())
    leftovers = [p for p in store.root.rglob("*") if p.suffix == ".tmp"]
    assert leftovers == []


def test_clearing_removes_the_checkpoint_and_is_safe_to_repeat(store):
    store.save(sample())
    store.clear("dev", "account", "ACCT-1")
    store.clear("dev", "account", "ACCT-1")
    assert store.load("dev", "account", "ACCT-1") is None


def test_tables_completed_counts_across_every_step():
    checkpoint = sample(completed={"org_delete": ["a", "b"], "main_delete": ["c"]})
    assert checkpoint.tables_completed == 3
