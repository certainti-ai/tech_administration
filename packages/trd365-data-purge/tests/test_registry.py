"""
The registry entry is how the API and the UI learn this utility exists, and
how the orchestrator builds its command line. If it is wrong, the utility is
either invisible or invoked with arguments it does not accept.
"""

from __future__ import annotations

import pytest
from trd365_core.environments import Environment
from trd365_core.registry import Impact, Registry

from trd365_data_purge.account import __main__ as entry_point
from trd365_data_purge.registry import PURGE_ACCOUNT, register


@pytest.fixture
def registry() -> Registry:
    return register(Registry())


def test_purge_account_is_registered(registry):
    assert registry.get("purge-account") is PURGE_ACCOUNT


def test_it_declares_itself_destructive():
    assert PURGE_ACCOUNT.impact is Impact.DESTRUCTIVE
    assert PURGE_ACCOUNT.is_destructive


def test_it_names_every_database_it_touches():
    # The health dashboard uses this to decide which connections must be up
    # before the utility can be offered at all.
    assert set(PURGE_ACCOUNT.databases) == {"maindb", "orgdb", "trd365ai"}


def test_writing_to_production_needs_a_second_person():
    assert PURGE_ACCOUNT.requires_approval_in_prod


def test_the_module_it_names_is_actually_runnable():
    # The orchestrator runs `python -m <module>`; a typo here is only found in
    # production otherwise.
    assert PURGE_ACCOUNT.module == "trd365_data_purge.account"
    assert callable(entry_point.main)


def test_the_account_rid_is_required():
    account_rid = next(p for p in PURGE_ACCOUNT.parameters if p.name == "account_rid")
    assert account_rid.required


def test_every_declared_parameter_is_a_flag_the_command_accepts():
    # build_argv turns parameter names into --flags. A parameter the parser
    # does not know is a run that dies on argparse rather than doing its job.
    from trd365_data_purge import cli

    parser = cli.build_parser("test")
    cli.add_common_arguments(parser)
    entry_point.configure(parser)
    known = {action.option_strings[0] for action in parser._actions if action.option_strings}

    for parameter in PURGE_ACCOUNT.parameters:
        assert parameter.cli_flag in known, f"{parameter.name} is declared but not accepted"


def test_it_can_run_in_every_environment_gated_by_approval():
    assert set(PURGE_ACCOUNT.environments) == set(Environment)


def test_it_records_which_legacy_tool_it_replaces():
    assert PURGE_ACCOUNT.supersedes == "account_deletion"


def test_the_descriptor_serialises_for_the_api(registry):
    payload = registry.to_dict()[0]
    assert payload["id"] == "purge-account"
    assert payload["impact"] == "destructive"
    assert {p["flag"] for p in payload["parameters"]} >= {"--account-rid", "--chunk-size"}
