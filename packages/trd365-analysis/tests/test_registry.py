"""The catalogue entry — how the API and the UI learn this utility exists."""

from __future__ import annotations

import pytest
from trd365_core.registry import Impact, Registry

from trd365_analysis import cli
from trd365_analysis.registry import DATA_MODEL_ANALYSIS, register


@pytest.fixture
def registry() -> Registry:
    return register(Registry())


def test_it_is_registered(registry):
    assert registry.get("data-model-analysis") is DATA_MODEL_ANALYSIS


def test_it_is_not_destructive():
    assert DATA_MODEL_ANALYSIS.impact is not Impact.DESTRUCTIVE


def test_publishing_the_model_still_needs_a_second_person_in_production():
    # It touches no database rows, but replacing the model every other utility
    # trusts is consequential enough to gate the same way.
    assert DATA_MODEL_ANALYSIS.requires_approval_in_prod


def test_it_declares_the_databases_it_reads():
    assert set(DATA_MODEL_ANALYSIS.databases) == {"maindb", "orgdb"}


def test_the_module_it_names_is_runnable():
    import importlib

    assert DATA_MODEL_ANALYSIS.module == "trd365_analysis"
    assert importlib.import_module("trd365_analysis.__main__")


def test_every_declared_parameter_is_a_flag_the_command_accepts():
    parser = cli.build_argument_parser()
    known = {a.option_strings[0] for a in parser._actions if a.option_strings}

    for parameter in DATA_MODEL_ANALYSIS.parameters:
        assert parameter.cli_flag in known, f"{parameter.name} is declared but not accepted"


def test_it_records_which_legacy_tool_it_replaces():
    assert DATA_MODEL_ANALYSIS.supersedes == "data_model_analysis"


def test_it_serialises_for_the_api(registry):
    payload = registry.to_dict()[0]
    assert payload["id"] == "data-model-analysis"
    assert {p["flag"] for p in payload["parameters"]} >= {"--schemas", "--no-orphans"}
