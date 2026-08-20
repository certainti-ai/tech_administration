"""Command construction — the registry descriptor is the whitelist."""

import pytest
from helpers import PURGE, REPORT
from trd365_core.environments import Environment

from trd365_orchestrator.commands import InvalidArguments, build_argv


def argv(utility=PURGE, env=Environment.DEV, args=None, apply=False):
    # `args or {...}` would treat an empty dict as "not supplied" and hide the
    # very case this helper is used to test.
    supplied = {"account_rid": "r-1"} if args is None else args
    return build_argv(utility, env, supplied, apply=apply, python="python")


class TestConstruction:
    def test_always_passes_the_environment(self):
        assert argv()[:5] == ["python", "-m", PURGE.module, "--env", "dev"]

    def test_apply_is_only_added_when_asked(self):
        assert "--apply" not in argv()
        assert "--apply" in argv(apply=True)

    def test_flags_use_hyphens(self):
        result = argv(args={"account_rid": "r-1", "chunk_size": 500})
        assert "--account-rid" in result and "--chunk-size" in result

    def test_boolean_parameters_are_bare_flags(self):
        result = argv(args={"account_rid": "r-1", "verbose": True})
        assert "--verbose" in result
        assert result[result.index("--verbose") - 1] != "--verbose"

    def test_false_booleans_are_omitted(self):
        assert "--verbose" not in argv(args={"account_rid": "r-1", "verbose": False})

    def test_empty_values_are_omitted(self):
        assert "--chunk-size" not in argv(args={"account_rid": "r-1", "chunk_size": None})


class TestRejection:
    def test_undeclared_arguments_are_refused(self):
        """
        Without this the API would let a caller append arbitrary flags to a
        command that deletes production data.
        """
        with pytest.raises(InvalidArguments, match="does not accept"):
            argv(args={"account_rid": "r-1", "--rm-rf": "/"})

    def test_required_arguments_are_enforced(self):
        with pytest.raises(InvalidArguments, match="requires"):
            argv(args={})

    def test_non_integers_are_refused_for_integer_parameters(self):
        with pytest.raises(InvalidArguments, match="must be an integer"):
            argv(args={"account_rid": "r-1", "chunk_size": "lots"})

    def test_newlines_and_nulls_are_refused(self):
        with pytest.raises(InvalidArguments, match="newlines"):
            argv(args={"account_rid": "r-1\nDROP TABLE"})

    def test_read_only_utilities_cannot_be_applied(self):
        with pytest.raises(InvalidArguments, match="read-only"):
            build_argv(REPORT, Environment.DEV, {}, apply=True)


class TestProductionConfirmation:
    """
    The utility asks for a typed confirmation before writing to production,
    which a subprocess has no stdin to answer. The service has already required
    a second approver (FR-4.3), so it answers on the command line rather than
    leaving the job hung with nothing to say why.
    """

    def test_a_production_apply_answers_it_up_front(self):
        assert "--yes" in argv(env=Environment.PROD, apply=True)

    def test_a_production_dry_run_does_not_need_it(self):
        assert "--yes" not in argv(env=Environment.PROD, apply=False)

    def test_a_non_production_apply_does_not_need_it(self):
        assert "--yes" not in argv(env=Environment.DEV, apply=True)
