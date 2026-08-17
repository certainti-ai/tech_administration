"""The utility catalogue, and the safety invariant it makes testable."""

import pytest

from trd365_core.environments import Environment
from trd365_core.errors import Trd365Error
from trd365_core.registry import Impact, Parameter, ParameterType, Registry, Utility


def utility(utility_id="purge-account", impact=Impact.DESTRUCTIVE, **kwargs):
    defaults = {
        "title": "Purge account",
        "description": "Remove an account and everything beneath it.",
        "module": "trd365_data_purge.account",
        "impact": impact,
        "databases": ("maindb", "orgdb"),
    }
    defaults.update(kwargs)
    return Utility(id=utility_id, **defaults)


class TestRegistration:
    def test_registers_and_retrieves(self):
        registry = Registry([utility()])
        assert len(registry) == 1
        assert registry.get("purge-account").title == "Purge account"
        assert "purge-account" in registry

    def test_duplicate_ids_are_rejected(self):
        registry = Registry([utility()])
        with pytest.raises(Trd365Error, match="already registered"):
            registry.register(utility())

    def test_unknown_database_keys_are_rejected(self):
        # Catches a typo in a utility descriptor at import time rather than
        # when someone runs it against production.
        with pytest.raises(Trd365Error, match="warehouse"):
            Registry([utility(databases=("maindb", "warehouse"))])

    def test_missing_utility_names_itself(self):
        with pytest.raises(Trd365Error, match="no-such"):
            Registry().get("no-such")


class TestImpact:
    def test_read_only_utilities_need_no_apply(self):
        assert Impact.READ_ONLY.needs_apply is False
        assert utility(impact=Impact.READ_ONLY).requires_approval_in_prod is False

    def test_anything_that_writes_needs_approval_in_production(self):
        for impact in (Impact.WRITES, Impact.DESTRUCTIVE):
            assert utility(impact=impact).requires_approval_in_prod is True

    def test_only_destructive_is_flagged_destructive(self):
        assert utility(impact=Impact.DESTRUCTIVE).is_destructive
        assert not utility(impact=Impact.WRITES).is_destructive


class TestSafetyInvariant:
    """
    The regression guard for the estate's headline bug: some legacy tools wrote
    by default. Nothing registered may reintroduce that.
    """

    def test_every_writing_utility_requires_approval_in_production(self):
        registry = Registry(
            [
                utility("a", impact=Impact.DESTRUCTIVE),
                utility("b", impact=Impact.WRITES),
                utility("c", impact=Impact.READ_ONLY),
            ]
        )
        for entry in registry.all():
            if entry.impact.needs_apply:
                assert entry.requires_approval_in_prod, f"{entry.id} writes without approval"

    def test_destructive_utilities_declare_the_databases_they_touch(self):
        registry = Registry([utility("a"), utility("b", impact=Impact.WRITES)])
        for entry in registry.destructive():
            assert entry.databases, f"{entry.id} does not declare its databases"


class TestFiltering:
    def test_filters_by_environment(self):
        registry = Registry(
            [
                utility("everywhere"),
                utility("lower-only", environments=(Environment.DEV, Environment.QA)),
            ]
        )
        prod = {u.id for u in registry.for_environment(Environment.PROD)}
        dev = {u.id for u in registry.for_environment(Environment.DEV)}
        assert prod == {"everywhere"}
        assert dev == {"everywhere", "lower-only"}

    def test_lists_destructive_utilities(self):
        registry = Registry([utility("a"), utility("b", impact=Impact.READ_ONLY)])
        assert [u.id for u in registry.destructive()] == ["a"]


class TestSerialisation:
    def test_produces_the_payload_the_ui_renders_from(self):
        entry = utility(
            parameters=(
                Parameter("account_id", ParameterType.STRING, "Account r_number", required=True),
                Parameter("chunk_size", ParameterType.INTEGER, "Batch size", default=1000),
            ),
            supersedes="account-deletion-legacy",
            notes="Kept alongside the legacy tool pending a decision.",
        )
        payload = entry.to_dict()

        assert payload["id"] == "purge-account"
        assert payload["impact"] == "destructive"
        assert payload["requires_approval_in_prod"] is True
        assert payload["databases"] == ["maindb", "orgdb"]
        assert payload["environments"] == ["dev", "qa", "stage", "prod"]
        assert payload["supersedes"] == "account-deletion-legacy"

        first = payload["parameters"][0]
        assert first["name"] == "account_id"
        assert first["flag"] == "--account-id"
        assert first["required"] is True
        assert payload["parameters"][1]["default"] == 1000

    def test_parameter_flags_convert_underscores(self):
        assert Parameter("project_fiscal_rid", ParameterType.STRING, "x").cli_flag == (
            "--project-fiscal-rid"
        )

    def test_registry_serialises_as_a_list(self):
        payload = Registry([utility("a"), utility("b")]).to_dict()
        assert [entry["id"] for entry in payload] == ["a", "b"]
