"""
Credentials from Key Vault.

The behaviour that matters is not "can it read a secret" — it is what happens
when it cannot. A vault that is unreachable must be indistinguishable from a
vault with nothing in it, because both mean "not available here", and the caller
already fails loudly on a placeholder. Anything else turns one network blip into
a utility connecting somewhere unintended.
"""

from __future__ import annotations

import pytest

from trd365_core.environments import (
    Environment,
    configuration_status,
    connection_settings,
    describe,
)
from trd365_core.errors import ConfigError, PlaceholderCredentialError
from trd365_core.vault import (
    KeyVaultSecrets,
    MappingVault,
    NoVault,
    default_secret_source,
    is_valid_secret_name,
    to_secret_name,
)


class TestNaming:
    """
    The Node tooling writes these names and this reads them. If the two
    transforms drift, the vault is silently read for names nothing ever wrote.
    """

    @pytest.mark.parametrize(
        ("env_name", "expected"),
        [
            ("MAINDB_PASSWORD", "maindb-password"),
            ("ORGDB_SSH_HOST", "orgdb-ssh-host"),
            ("TRD365AI_SSLMODE", "trd365ai-sslmode"),
            ("TRD365_DEV_ORGDB_PASSWORD", "trd365-dev-orgdb-password"),
        ],
    )
    def test_matches_the_node_transform(self, env_name, expected):
        assert to_secret_name(env_name) == expected

    def test_the_result_is_always_a_legal_secret_name(self):
        assert is_valid_secret_name(to_secret_name("TRD365_STAGE_MAINDB_SSH_PASSWORD"))

    @pytest.mark.parametrize("bad", ["", "has space", "1LEADING_DIGIT", "has-hyphen"])
    def test_rejects_anything_that_is_not_an_environment_variable_name(self, bad):
        with pytest.raises(ConfigError):
            to_secret_name(bad)

    @pytest.mark.parametrize("bad", ["", "under_score", "a" * 128, "has space"])
    def test_illegal_secret_names_are_recognised(self, bad):
        assert is_valid_secret_name(bad) is False


class TestSources:
    def test_no_vault_is_always_absent(self):
        assert NoVault().get("maindb-password") is None

    def test_without_a_configured_vault_the_source_reads_nothing(self):
        assert isinstance(default_secret_source({}), NoVault)
        assert isinstance(default_secret_source({"AZURE_KEY_VAULT_NAME": "  "}), NoVault)

    def test_a_configured_vault_name_produces_a_real_client(self):
        source = default_secret_source(
            {"AZURE_KEY_VAULT_NAME": "trd365-maint-kv", "AZURE_CLIENT_ID": "abc"}
        )
        assert isinstance(source, KeyVaultSecrets)
        assert source.url == "https://trd365-maint-kv.vault.azure.net"
        assert source.client_id == "abc"


class FakeClient:
    """Stands in for azure.keyvault.secrets.SecretClient."""

    def __init__(self, secrets, error=None):
        self.secrets = secrets
        self.error = error
        self.calls: list[str] = []

    def get_secret(self, name):
        self.calls.append(name)
        if self.error is not None:
            raise self.error
        if name not in self.secrets:
            raise KeyError(name)
        return type("Secret", (), {"value": self.secrets[name]})()


class TestKeyVaultSecrets:
    def test_reads_a_secret(self):
        vault = KeyVaultSecrets("kv", client=FakeClient({"maindb-password": "s3cret"}))
        assert vault.get("maindb-password") == "s3cret"

    def test_an_unreachable_vault_reads_as_absent_rather_than_raising(self):
        # This runs in a loop over every credential field. One outage must not
        # produce forty stack traces, and must not stop the caller reporting the
        # environment as unconfigured — which is the truthful answer.
        vault = KeyVaultSecrets("kv", client=FakeClient({}, error=RuntimeError("no route")))
        assert vault.get("maindb-password") is None

    def test_a_missing_secret_reads_as_absent(self):
        vault = KeyVaultSecrets("kv", client=FakeClient({"other": "x"}))
        assert vault.get("maindb-password") is None

    def test_each_name_is_fetched_once_including_a_miss(self):
        client = FakeClient({"maindb-password": "s3cret"})
        vault = KeyVaultSecrets("kv", client=client)
        for _ in range(3):
            vault.get("maindb-password")
            vault.get("absent")
        assert client.calls == ["maindb-password", "absent"]

    def test_an_illegal_name_never_reaches_the_vault(self):
        client = FakeClient({})
        vault = KeyVaultSecrets("kv", client=client)
        assert vault.get("under_score") is None
        assert client.calls == []

    def test_a_vault_name_is_required(self):
        with pytest.raises(ConfigError):
            KeyVaultSecrets("")


class TestResolution:
    """How the vault composes with the process environment."""

    def test_the_vault_supplies_what_the_environment_does_not(self):
        vault = MappingVault(
            {
                "trd365-dev-maindb-host": "db.internal",
                "trd365-dev-maindb-dbname": "trd365_dev",
                "trd365-dev-maindb-user": "svc",
                "trd365-dev-maindb-password": "from-the-vault",
                "trd365-dev-maindb-ssh-host": "bastion",
                "trd365-dev-maindb-ssh-user": "ops",
                "trd365-dev-maindb-ssh-password": "tunnel",
            }
        )
        settings = describe(Environment.DEV, "maindb", environ={}, secrets=vault)
        assert settings.password == "from-the-vault"
        assert settings.host == "db.internal"
        assert settings.is_placeholder is False

    def test_the_environment_beats_the_vault(self):
        # An operator overriding one value for one command has to win, or there
        # is no way to test a credential change without editing the vault.
        vault = MappingVault({"trd365-dev-maindb-password": "from-the-vault"})
        settings = describe(
            Environment.DEV,
            "maindb",
            environ={"TRD365_DEV_MAINDB_PASSWORD": "from-the-environment"},
            secrets=vault,
        )
        assert settings.password == "from-the-environment"

    def test_the_unscoped_name_is_read_from_the_vault_for_production_only(self):
        vault = MappingVault({"maindb-password": "prod-secret"})
        assert (
            describe(Environment.PROD, "maindb", environ={}, secrets=vault).password
            == "prod-secret"
        )
        # Dev must not pick up an unscoped production credential.
        assert (
            describe(Environment.DEV, "maindb", environ={}, secrets=vault).password
            != "prod-secret"
        )

    def test_the_scoped_name_is_preferred_over_the_unscoped_one(self):
        vault = MappingVault(
            {"maindb-password": "legacy", "trd365-prod-maindb-password": "scoped"}
        )
        settings = describe(Environment.PROD, "maindb", environ={}, secrets=vault)
        assert settings.password == "scoped"

    def test_an_empty_vault_value_is_treated_as_absent(self):
        vault = MappingVault({"trd365-dev-maindb-password": ""})
        settings = describe(Environment.DEV, "maindb", environ={}, secrets=vault)
        assert settings.is_placeholder

    def test_connecting_still_refuses_when_the_vault_has_nothing(self):
        with pytest.raises(PlaceholderCredentialError):
            connection_settings(Environment.QA, "orgdb", environ={}, secrets=NoVault())

    def test_configuration_status_shares_one_source_across_every_check(self):
        # Sixteen checks per dashboard refresh, each reading several fields.
        # Built per check that is sixteen times the round trips against a cache
        # that is never warm, so the one source has to be threaded through.
        vault = MappingVault({})
        status = configuration_status(environ={}, secrets=vault)

        assert set(status) == set(Environment)
        assert vault.requested, "the vault was never consulted"
        # Every environment and database appears, through the one shared source.
        for env in Environment:
            assert any(env.value in name for name in vault.requested)
        for db_key in ("maindb", "orgdb", "trd365ai"):
            assert any(db_key in name for name in vault.requested)

    def test_no_vault_configured_leaves_behaviour_exactly_as_before(self):
        # The regression that matters: adding a vault must not change what a
        # laptop or a CI run sees.
        assert describe(Environment.DEV, "maindb", environ={}).is_placeholder


class TestMissesCostNothing:
    """
    Absent secrets must not each cost a round trip.

    Readiness across four environments and three databases asks for well over a
    hundred names, and for an environment whose credentials were never supplied
    every one is absent. Fetched individually that is a hundred sequential
    requests to learn nothing, which is what made the health endpoint time out
    the first time it was called through the public site.
    """

    class Client:
        def __init__(self, secrets, list_error=None):
            self.secrets = secrets
            self.list_error = list_error
            self.gets: list[str] = []
            self.lists = 0

        def list_properties_of_secrets(self):
            self.lists += 1
            if self.list_error is not None:
                raise self.list_error
            return [type("P", (), {"name": name})() for name in self.secrets]

        def get_secret(self, name):
            self.gets.append(name)
            if name not in self.secrets:
                raise KeyError(name)
            return type("S", (), {"value": self.secrets[name]})()

    def test_the_vault_is_listed_once_and_misses_never_reach_it(self):
        client = self.Client({"maindb-password": "s3cret"})
        vault = KeyVaultSecrets("kv", client=client)

        assert vault.get("maindb-password") == "s3cret"
        for name in ("trd365-dev-maindb-password", "trd365-qa-orgdb-host", "nope"):
            assert vault.get(name) is None

        assert client.lists == 1, "the listing must happen once, not per lookup"
        assert client.gets == ["maindb-password"], "a miss must not be requested"

    def test_a_failed_listing_falls_back_to_asking_per_name(self):
        # An identity that can read a secret but not list them must still work,
        # and a listing outage must not make a full vault look empty.
        client = self.Client({"maindb-password": "s3cret"}, list_error=RuntimeError("denied"))
        vault = KeyVaultSecrets("kv", client=client)

        assert vault.get("maindb-password") == "s3cret"
        assert client.gets == ["maindb-password"]

    def test_listing_is_not_attempted_when_every_answer_is_cached(self):
        client = self.Client({"maindb-password": "s3cret"})
        vault = KeyVaultSecrets("kv", client=client)
        vault.get("maindb-password")
        before = client.lists
        for _ in range(5):
            vault.get("maindb-password")
        assert client.lists == before
