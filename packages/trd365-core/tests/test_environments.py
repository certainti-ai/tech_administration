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


class TestTheNonProdTopology:
    """
    Dev, QA and Stage have known servers and unknown credentials.

    The split matters: a host in code is reviewable and moves through review when
    it changes, while a password in code is a password in git. So these assert
    that exactly the right half is known.
    """

    @pytest.mark.parametrize("env", [Environment.DEV, Environment.QA])
    @pytest.mark.parametrize("db_key", ["maindb", "orgdb"])
    def test_the_server_is_known_and_only_the_password_is_not(self, env, db_key):
        settings = envs.describe(env, db_key, {})
        assert envs.PLACEHOLDER not in settings.host
        assert settings.host.endswith(".postgres.database.azure.com")
        assert settings.user == "adminUser"
        assert envs.PLACEHOLDER not in settings.dbname
        # Which leaves exactly one thing outstanding, and it is the one thing
        # that must not be in a repository.
        assert settings.password == envs.PLACEHOLDER
        assert settings.is_placeholder

    @pytest.mark.parametrize("env", list(Environment))
    @pytest.mark.parametrize("db_key", ["maindb", "orgdb"])
    def test_the_database_name_tracks_the_server_name(self, env, db_key):
        # `-pvt-` in the server means `pvt` in the database. Read off Dev and QA
        # directly (`SELECT datname FROM pg_database` returned `thinkrd365_main`,
        # not `thinkrd365_pvt_main`) after a login that succeeded and a database
        # that did not exist — Postgres authenticates before it resolves the
        # database, so a wrong name here passes every credential check first.
        settings = envs.describe(env, db_key, {})
        private = "-pvt-" in settings.host
        stem = "main" if db_key == "maindb" else "org"
        assert settings.dbname == f"thinkrd365_{'pvt_' if private else ''}{stem}"

    @pytest.mark.parametrize("env", [Environment.DEV, Environment.QA])
    def test_dev_and_qa_are_reached_directly(self, env):
        for db_key in ("maindb", "orgdb"):
            settings = envs.describe(env, db_key, {})
            assert settings.ssh_tunnel is None
            assert "-pvt-" not in settings.host

    @pytest.mark.parametrize("env", [Environment.STAGE, Environment.PROD])
    def test_the_private_endpoint_environments_have_a_bastion(self, env):
        for db_key in ("maindb", "orgdb"):
            settings = envs.describe(env, db_key, {})
            assert settings.ssh_tunnel is not None
            # The private-endpoint servers are exactly the ones behind a bastion.
            # A tunnel where none is needed times out; a missing one fails to
            # resolve. Neither message mentions bastions, so the pairing is
            # pinned here instead of being inferred at run time.
            assert "-pvt-" in settings.host

    def test_stage_and_prod_do_not_share_a_bastion(self):
        # They did in this file until Stage was actually tried. Every environment
        # has its own private DNS zone, all four named
        # `privatelink.postgres.database.azure.com`, and a virtual network links
        # to only one zone of a given name — so the production bastion resolves
        # production's private endpoint and nothing for preprod. Two hosts, not
        # one, and the test says so because the comment alone did not stop it.
        stage = envs.describe(Environment.STAGE, "maindb", {}).ssh_tunnel
        prod = envs.describe(Environment.PROD, "maindb", {}).ssh_tunnel
        assert stage.ssh_host != prod.ssh_host

    def test_prod_uses_the_bastion_known_to_work(self):
        tunnel = envs.describe(Environment.PROD, "maindb", {}).ssh_tunnel
        assert tunnel.ssh_host == "172.203.151.166"
        assert tunnel.ssh_user == "thinkrd_DevOps"

    def test_stage_is_unreachable_until_its_bastion_account_is_supplied(self):
        # Its host is known; the account is not, so Stage must refuse rather than
        # try the production credentials against a host that rejects them.
        settings = envs.describe(Environment.STAGE, "maindb", {})
        assert settings.ssh_tunnel.ssh_host == "40.71.82.6"
        assert settings.ssh_tunnel.ssh_user == envs.PLACEHOLDER
        assert settings.is_placeholder

    @pytest.mark.parametrize("env", [Environment.DEV, Environment.QA, Environment.STAGE])
    def test_trd365ai_is_unknown_outside_prod(self, env):
        # Whether one exists per environment is HANDOFF open question 1. Until
        # it is answered, placeholders mean a utility that touches it refuses to
        # run and says why.
        settings = envs.describe(env, "trd365ai", {})
        assert settings.host == envs.PLACEHOLDER
        assert settings.is_placeholder


class TestPlaceholderEnvironments:

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
        # Stage, because it is the non-prod environment that has a bastion. The
        # database credentials are complete here and the connection is still
        # refused, which is the point: everything needed to reach the server has
        # to be present, not just everything needed to log in to it.
        environ = {
            "TRD365_STAGE_MAINDB_DBNAME": "stage_main",
            "TRD365_STAGE_MAINDB_PASSWORD": "pw",
            # ssh_password left unset
        }
        assert envs.describe(Environment.STAGE, "maindb", environ).is_placeholder

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
