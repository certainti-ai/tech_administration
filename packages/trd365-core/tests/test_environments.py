"""Environment resolution, and the refusal to connect with placeholders."""

import pytest

from trd365_core import environments as envs
from trd365_core.environments import Environment
from trd365_core.errors import ConfigError, PlaceholderCredentialError

PROD_ENV = {
    "MAINDB_HOST": "main.example.internal",
    "MAINDB_PORT": "5432",
    "MAINDB_DBNAME": "thinkrd365_pvt_main",
    "MAINDB_USER": "adminUser",
    "MAINDB_PASSWORD": "prod-main-pw",
    "MAINDB_SSLMODE": "require",
    "MAINDB_SSH_HOST": "10.0.0.1",
    "MAINDB_SSH_PORT": "22",
    "MAINDB_SSH_USER": "devops",
    "MAINDB_SSH_PASSWORD": "bastion-pw",
}


class TestEnvironmentParsing:
    def test_parses_the_four_environments(self):
        assert Environment.parse("prod") is Environment.PROD
        assert Environment.parse(" DEV ") is Environment.DEV

    def test_only_prod_is_production(self):
        assert Environment.PROD.is_production
        assert not Environment.STAGE.is_production

    def test_unknown_environment_lists_the_valid_ones(self):
        with pytest.raises(ConfigError, match="dev, qa, stage, prod"):
            Environment.parse("production")


class TestProdResolution:
    def test_reads_the_legacy_unscoped_variables(self):
        settings = envs.describe(Environment.PROD, "maindb", PROD_ENV)
        assert settings.host == "main.example.internal"
        assert settings.password == "prod-main-pw"
        assert settings.ssh_tunnel is not None
        assert settings.ssh_tunnel.ssh_user == "devops"

    def test_scoped_names_take_precedence_over_legacy(self):
        environ = dict(PROD_ENV, TRD365_PROD_MAINDB_HOST="scoped.example.internal")
        assert envs.describe(Environment.PROD, "maindb", environ).host == "scoped.example.internal"

    def test_known_topology_supplies_non_secret_defaults(self):
        # Host/dbname/user are known for prod, so only the password is needed.
        settings = envs.describe(Environment.PROD, "trd365ai", {"TRD365AI_PASSWORD": "pw"})
        assert settings.dbname == "trd365ai"
        assert settings.user == "aiadmin"
        assert settings.sslmode == "prefer"
        assert settings.ssh_tunnel is None  # trd365ai is reached directly

    def test_connection_settings_succeed_when_fully_configured(self):
        settings = envs.connection_settings(Environment.PROD, "maindb", PROD_ENV)
        assert settings.password == "prod-main-pw"


class TestPlaceholderEnvironments:
    @pytest.mark.parametrize("env", [Environment.DEV, Environment.QA, Environment.STAGE])
    def test_unconfigured_environments_describe_as_placeholders(self, env):
        settings = envs.describe(env, "maindb", {})
        assert settings.is_placeholder
        assert envs.PLACEHOLDER in settings.host

    @pytest.mark.parametrize("env", [Environment.DEV, Environment.QA, Environment.STAGE])
    def test_connecting_to_an_unconfigured_environment_is_refused(self, env):
        with pytest.raises(PlaceholderCredentialError) as excinfo:
            envs.connection_settings(env, "maindb", {})
        # The error has to say exactly which variables would fix it.
        message = str(excinfo.value)
        assert f"TRD365_{env.value.upper()}_MAINDB_HOST" in message
        assert "PASSWORD" in message

    def test_a_missing_password_alone_still_counts_as_placeholder(self):
        environ = {
            "TRD365_DEV_MAINDB_HOST": "dev.example.internal",
            "TRD365_DEV_MAINDB_DBNAME": "dev_main",
            "TRD365_DEV_MAINDB_USER": "dev",
            "TRD365_DEV_MAINDB_SSH_HOST": "10.1.0.1",
            "TRD365_DEV_MAINDB_SSH_USER": "devops",
            "TRD365_DEV_MAINDB_SSH_PASSWORD": "pw",
        }
        with pytest.raises(PlaceholderCredentialError):
            envs.connection_settings(Environment.DEV, "maindb", environ)

    def test_a_placeholder_tunnel_makes_the_whole_setting_placeholder(self):
        environ = {
            "TRD365_QA_MAINDB_HOST": "qa.example.internal",
            "TRD365_QA_MAINDB_DBNAME": "qa_main",
            "TRD365_QA_MAINDB_USER": "qa",
            "TRD365_QA_MAINDB_PASSWORD": "pw",
            # tunnel host/user/password left unset
        }
        assert envs.describe(Environment.QA, "maindb", environ).is_placeholder

    def test_fully_supplying_dev_makes_it_connectable(self):
        environ = {
            f"TRD365_DEV_MAINDB_{field}": value
            for field, value in {
                "HOST": "dev.example.internal",
                "DBNAME": "dev_main",
                "USER": "dev",
                "PASSWORD": "dev-pw",
                "SSH_HOST": "10.1.0.1",
                "SSH_USER": "devops",
                "SSH_PASSWORD": "bastion",
            }.items()
        }
        settings = envs.connection_settings(Environment.DEV, "maindb", environ)
        assert settings.host == "dev.example.internal"

    def test_legacy_names_do_not_leak_into_non_production(self):
        # MAINDB_HOST describes prod; it must not silently configure dev.
        assert envs.describe(Environment.DEV, "maindb", PROD_ENV).is_placeholder


class TestStatus:
    def test_reports_readiness_per_environment_and_database(self):
        status = envs.configuration_status({})
        assert set(status) == set(Environment)
        assert status[Environment.DEV] == {"maindb": False, "orgdb": False, "trd365ai": False}

    def test_prod_is_ready_when_all_three_are_supplied(self):
        environ = dict(PROD_ENV)
        environ.update(
            {
                "ORGDB_PASSWORD": "org-pw",
                "ORGDB_SSH_PASSWORD": "bastion-pw",
                "TRD365AI_PASSWORD": "ai-pw",
            }
        )
        assert envs.is_configured(Environment.PROD, environ)

    def test_unknown_database_key_is_rejected(self):
        with pytest.raises(ConfigError, match="maindb, orgdb, trd365ai"):
            envs.describe(Environment.PROD, "warehouse", {})


class TestRedaction:
    def test_redacted_hides_passwords_but_keeps_shape(self):
        redacted = envs.describe(Environment.PROD, "maindb", PROD_ENV).redacted()
        assert redacted.password == "***"
        assert redacted.ssh_tunnel is not None
        assert redacted.ssh_tunnel.ssh_password == "***"
        assert redacted.host == "main.example.internal"
        assert redacted.ssh_tunnel.ssh_user == "devops"


class TestPlatformWorkspace:
    """
    The platform's Terraform does not spell environments the way we do, and a
    resource name built from the wrong spelling points at the wrong estate.
    """

    def test_stage_is_preprod_on_the_platform(self):
        # Confirmed by the owner, 2026-08-20. This is the one that surprises.
        assert Environment.STAGE.platform_workspace == "preprod"

    def test_dev_is_development(self):
        assert Environment.DEV.platform_workspace == "development"

    @pytest.mark.parametrize("env", [Environment.QA, Environment.PROD])
    def test_the_others_are_spelled_the_same(self, env):
        assert env.platform_workspace == env.value

    def test_every_environment_has_a_workspace(self):
        # A new environment must not silently have no platform name.
        assert all(e.platform_workspace for e in Environment)
