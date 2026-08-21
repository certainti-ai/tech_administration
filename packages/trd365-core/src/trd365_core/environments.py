"""
The four deployment environments and how their connection settings are found.

Every utility names its environment explicitly — there is no default, because
the failure mode of a wrong default here is destroying the wrong database.

Credentials are read from the process environment (populated from Azure Key
Vault; see ``docs/secrets.md``). Two naming schemes are accepted:

``TRD365_<ENV>_<DBKEY>_<FIELD>``
    The scheme going forward. Explicit about which environment it belongs to.

``<DBKEY>_<FIELD>``
    The legacy unscoped names (``MAINDB_HOST``, ``ORGDB_PASSWORD``, …) that the
    original scripts used. Accepted **for prod only**, since that is the only
    environment they ever described. Keeping them working means the existing
    Key Vault inventory needs no rename to be useful today.

Dev, QA and Stage currently resolve to placeholders. They are deliberately
unusable: :func:`connection_settings` raises rather than returning them, so a
half-configured environment fails loudly instead of connecting somewhere
unintended.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from enum import StrEnum

from .errors import ConfigError, PlaceholderCredentialError
from .vault import SecretSource, default_secret_source, to_secret_name

#: Marker value for a credential that has not been supplied yet. Chosen to be
#: obviously non-functional if it ever escapes into a connection attempt.
PLACEHOLDER = "PLACEHOLDER_NOT_CONFIGURED"


class Environment(StrEnum):
    DEV = "dev"
    QA = "qa"
    STAGE = "stage"
    PROD = "prod"

    @property
    def is_production(self) -> bool:
        return self is Environment.PROD

    @classmethod
    def parse(cls, value: str) -> Environment:
        try:
            return cls(value.strip().lower())
        except ValueError:
            valid = ", ".join(e.value for e in cls)
            raise ConfigError(f'Unknown environment "{value}". Expected one of: {valid}.') from None

    @property
    def platform_workspace(self) -> str:
        """
        What the platform's own Terraform calls this environment.

        ``rdcredits_platform_iac`` names its resources
        ``<workspace>-thinkrd365-*``, and its workspaces are not spelled the way
        ours are: **Stage is ``preprod`` there** (confirmed by the owner,
        2026-08-20), and Dev is ``development``. Anything that has to name a
        platform resource — a VNet, a resource group, an AD group — has to
        translate, and this is the one place that translation lives.
        """
        return PLATFORM_WORKSPACE[self]


#: Our environment name -> the platform Terraform's workspace name.
PLATFORM_WORKSPACE: dict[Environment, str] = {
    Environment.DEV: "development",
    Environment.QA: "qa",
    Environment.STAGE: "preprod",
    Environment.PROD: "prod",
}


#: Logical database keys. Every utility refers to databases by these names.
DB_KEYS: tuple[str, ...] = ("maindb", "orgdb", "trd365ai")


@dataclass(frozen=True)
class SshTunnel:
    ssh_host: str
    ssh_port: int
    ssh_user: str
    ssh_password: str

    @property
    def is_placeholder(self) -> bool:
        return PLACEHOLDER in (self.ssh_host, self.ssh_user, self.ssh_password)


@dataclass(frozen=True)
class ConnectionSettings:
    """Everything needed to open one database connection."""

    db_key: str
    host: str
    port: int
    dbname: str
    user: str
    password: str
    sslmode: str
    ssh_tunnel: SshTunnel | None = None

    @property
    def is_placeholder(self) -> bool:
        if PLACEHOLDER in (self.host, self.dbname, self.user, self.password):
            return True
        return self.ssh_tunnel is not None and self.ssh_tunnel.is_placeholder

    def redacted(self) -> ConnectionSettings:
        """A copy safe to log or serialise — secrets replaced, shape preserved."""
        tunnel = (
            replace(self.ssh_tunnel, ssh_password="***") if self.ssh_tunnel is not None else None
        )
        return replace(self, password="***", ssh_tunnel=tunnel)


# --------------------------------------------------------------------------
# Known non-secret topology.
#
# Host/dbname/user are not secrets (see SANITIZATION_NOTE.md in the legacy tree)
# and live here so the shape of each environment is reviewable in code and moves
# through review when it changes. Passwords never appear here — they come from
# the Key Vault, and a topology entry can be overridden from there too if one of
# these values turns out to be wrong.
#
# Two things are deliberately visible in the shapes below.
#
# **Dev and QA are reachable directly; Stage and Prod are not.** Their servers
# carry `-pvt-` in the hostname and sit behind the same bastion. That is not a
# detail to infer at run time: a tunnel that should not be there fails with a
# connection timeout, and one that is missing fails with a DNS error, and neither
# message says "this environment has a bastion and you did not use it".
#
# **`dbname` is a placeholder everywhere but prod.** It is not a secret, it is
# simply not known here yet, so it has to come from the vault. A wrong database
# name on the same server is the one mistake in this file that would connect
# successfully and operate on the wrong data.
# --------------------------------------------------------------------------

#: Stage and Prod share one bastion host and one account.
_SHARED_BASTION = {
    "ssh_host": "172.203.151.166",
    "ssh_port": 22,
    "ssh_user": "thinkrd_DevOps",
}

_KNOWN_TOPOLOGY: dict[Environment, dict[str, dict[str, object]]] = {
    Environment.DEV: {
        "maindb": {
            "host": (
                "development-thinkrd365-psqlserver-centralus-main.postgres.database.azure.com"
            ),
            "port": 5432,
            "dbname": PLACEHOLDER,
            "user": "adminUser",
            "sslmode": "require",
            "tunnel": None,
        },
        "orgdb": {
            "host": "development-thinkrd365-psqlserver-centralus-org.postgres.database.azure.com",
            "port": 5432,
            "dbname": PLACEHOLDER,
            "user": "adminUser",
            "sslmode": "require",
            "tunnel": None,
        },
        # Whether a trd365ai instance exists for this environment at all is an
        # open question (docs/HANDOFF.md open question 1). Left as placeholders,
        # so utilities that touch it refuse to run here and say why, rather than
        # this environment quietly looking complete without it.
        "trd365ai": {
            "host": PLACEHOLDER,
            "port": 5432,
            "dbname": PLACEHOLDER,
            "user": PLACEHOLDER,
            "sslmode": "prefer",
            "tunnel": None,
        },
    },
    Environment.QA: {
        "maindb": {
            "host": "qa-thinkrd365-psqlserver-centralus-main.postgres.database.azure.com",
            "port": 5432,
            "dbname": PLACEHOLDER,
            "user": "adminUser",
            "sslmode": "require",
            "tunnel": None,
        },
        "orgdb": {
            "host": "qa-thinkrd365-psqlserver-centralus-org.postgres.database.azure.com",
            "port": 5432,
            "dbname": PLACEHOLDER,
            "user": "adminUser",
            "sslmode": "require",
            "tunnel": None,
        },
        # Whether a trd365ai instance exists for this environment at all is an
        # open question (docs/HANDOFF.md open question 1). Left as placeholders,
        # so utilities that touch it refuse to run here and say why, rather than
        # this environment quietly looking complete without it.
        "trd365ai": {
            "host": PLACEHOLDER,
            "port": 5432,
            "dbname": PLACEHOLDER,
            "user": PLACEHOLDER,
            "sslmode": "prefer",
            "tunnel": None,
        },
    },
    Environment.STAGE: {
        "maindb": {
            "host": (
                "preprod-thinkrd365-psqlserver-centralus-pvt-main.postgres.database.azure.com"
            ),
            "port": 5432,
            "dbname": PLACEHOLDER,
            "user": "adminUser",
            "sslmode": "require",
            "tunnel": _SHARED_BASTION,
        },
        "orgdb": {
            "host": "preprod-thinkrd365-psqlserver-centralus-pvt-org.postgres.database.azure.com",
            "port": 5432,
            "dbname": PLACEHOLDER,
            "user": "adminUser",
            "sslmode": "require",
            "tunnel": _SHARED_BASTION,
        },
        # Whether a trd365ai instance exists for this environment at all is an
        # open question (docs/HANDOFF.md open question 1). Left as placeholders,
        # so utilities that touch it refuse to run here and say why, rather than
        # this environment quietly looking complete without it.
        "trd365ai": {
            "host": PLACEHOLDER,
            "port": 5432,
            "dbname": PLACEHOLDER,
            "user": PLACEHOLDER,
            "sslmode": "prefer",
            "tunnel": None,
        },
    },
    Environment.PROD: {
        "maindb": {
            "host": "prod-thinkrd365-psqlserver-centralus-pvt-main.postgres.database.azure.com",
            "port": 5432,
            "dbname": "thinkrd365_pvt_main",
            "user": "adminUser",
            "sslmode": "require",
            "tunnel": _SHARED_BASTION,
        },
        "orgdb": {
            "host": "prod-thinkrd365-psqlserver-centralus-pvt-org.postgres.database.azure.com",
            "port": 5432,
            "dbname": "thinkrd365_pvt_org",
            "user": "adminUser",
            "sslmode": "require",
            "tunnel": _SHARED_BASTION,
        },
        "trd365ai": {
            "host": "4.246.251.140",
            "port": 5432,
            "dbname": "trd365ai",
            "user": "aiadmin",
            "sslmode": "prefer",
            "tunnel": None,
        },
    },
}

#: The fallback for a database in an environment this file says nothing about.
#: Every environment is now described above, so this is reached only if one is
#: added to :class:`Environment` without a topology entry — in which case
#: placeholders are the right answer, since the alternative is inventing a host.
_PLACEHOLDER_TOPOLOGY: dict[str, dict[str, object]] = {
    "maindb": {
        "host": PLACEHOLDER,
        "port": 5432,
        "dbname": PLACEHOLDER,
        "user": PLACEHOLDER,
        "sslmode": "require",
        "tunnel": {"ssh_host": PLACEHOLDER, "ssh_port": 22, "ssh_user": PLACEHOLDER},
    },
    "orgdb": {
        "host": PLACEHOLDER,
        "port": 5432,
        "dbname": PLACEHOLDER,
        "user": PLACEHOLDER,
        "sslmode": "require",
        "tunnel": {"ssh_host": PLACEHOLDER, "ssh_port": 22, "ssh_user": PLACEHOLDER},
    },
    "trd365ai": {
        "host": PLACEHOLDER,
        "port": 5432,
        "dbname": PLACEHOLDER,
        "user": PLACEHOLDER,
        "sslmode": "prefer",
        "tunnel": None,
    },
}


def _candidate_names(env: Environment, db_key: str, field: str) -> list[str]:
    """
    The environment variable names that can carry one credential field, in order.

    The scoped name wins. The unscoped one is honoured for production only,
    because that is the shape the original scripts used and the only environment
    they ever described — extending it to the others would let a stray
    ``ORGDB_PASSWORD`` silently serve Dev.
    """
    names = [f"TRD365_{env.value.upper()}_{db_key.upper()}_{field.upper()}"]
    if env.is_production:
        names.append(f"{db_key.upper()}_{field.upper()}")
    return names


def _lookup(
    env: Environment,
    db_key: str,
    field: str,
    environ: dict[str, str],
    secrets: SecretSource | None = None,
) -> str | None:
    """
    One credential field: the process environment first, then Key Vault.

    Order matters. The environment is what an operator sets deliberately for one
    command, so it has to beat the vault — otherwise overriding a single value to
    test something would be impossible. The vault is the durable source underneath
    (PRD FR-2.x), and on the maintenance VM it is the *only* source: nothing there
    populates the environment, so without this the credentials sit in a vault the
    host can read and no utility can see.
    """
    for name in _candidate_names(env, db_key, field):
        if environ.get(name):
            return environ[name]

    if secrets is None:
        return None

    for name in _candidate_names(env, db_key, field):
        value = secrets.get(to_secret_name(name))
        if value:
            return value
    return None


def describe(
    env: Environment,
    db_key: str,
    environ: dict[str, str] | None = None,
    secrets: SecretSource | None = None,
) -> ConnectionSettings:
    """
    Build settings for one database, without judging whether they are usable.

    Placeholders are returned as-is. Use :func:`connection_settings` when you
    intend to connect — it refuses placeholders.

    ``secrets`` defaults to a Key Vault source built from the ambient
    environment, which resolves to :class:`~trd365_core.vault.NoVault` unless
    ``AZURE_KEY_VAULT_NAME`` is set. Pass one explicitly in tests.
    """
    if db_key not in DB_KEYS:
        raise ConfigError(
            f'Unknown database key "{db_key}". Expected one of: {", ".join(DB_KEYS)}.'
        )

    environ = os.environ if environ is None else environ
    if secrets is None:
        secrets = default_secret_source(environ)
    known = _KNOWN_TOPOLOGY.get(env, _PLACEHOLDER_TOPOLOGY)[db_key]

    def field(name: str, fallback: object) -> str:
        found = _lookup(env, db_key, name, environ, secrets)
        return found if found is not None else str(fallback)

    tunnel_defaults = known.get("tunnel")
    tunnel: SshTunnel | None = None
    if tunnel_defaults is not None:
        assert isinstance(tunnel_defaults, dict)
        tunnel = SshTunnel(
            ssh_host=field("ssh_host", tunnel_defaults["ssh_host"]),
            ssh_port=int(field("ssh_port", tunnel_defaults["ssh_port"])),
            ssh_user=field("ssh_user", tunnel_defaults["ssh_user"]),
            ssh_password=field("ssh_password", PLACEHOLDER),
        )

    return ConnectionSettings(
        db_key=db_key,
        host=field("host", known["host"]),
        port=int(field("port", known["port"])),
        dbname=field("dbname", known["dbname"]),
        user=field("user", known["user"]),
        password=field("password", PLACEHOLDER),
        sslmode=field("sslmode", known["sslmode"]),
        ssh_tunnel=tunnel,
    )


def connection_settings(
    env: Environment,
    db_key: str,
    environ: dict[str, str] | None = None,
    secrets: SecretSource | None = None,
) -> ConnectionSettings:
    """
    Settings for a database you intend to connect to.

    Raises :class:`PlaceholderCredentialError` if the environment has not been
    configured, naming the variables that would supply it.
    """
    settings = describe(env, db_key, environ, secrets)
    if settings.is_placeholder:
        prefix = f"TRD365_{env.value.upper()}_{db_key.upper()}_"
        raise PlaceholderCredentialError(
            f"{env.value} / {db_key} has no credentials configured yet.\n"
            f"Supply them as {prefix}HOST, {prefix}DBNAME, {prefix}USER, {prefix}PASSWORD"
            + (
                f", {prefix}SSH_HOST, {prefix}SSH_USER, {prefix}SSH_PASSWORD"
                if settings.ssh_tunnel
                else ""
            )
            + "\n(via Azure Key Vault — see docs/secrets.md)."
        )
    return settings


def is_configured(
    env: Environment,
    environ: dict[str, str] | None = None,
    secrets: SecretSource | None = None,
) -> bool:
    """Whether every database in an environment has real credentials."""
    if secrets is None:
        secrets = default_secret_source(os.environ if environ is None else environ)
    return all(not describe(env, key, environ, secrets).is_placeholder for key in DB_KEYS)


def configuration_status(
    environ: dict[str, str] | None = None,
    secrets: SecretSource | None = None,
) -> dict[Environment, dict[str, bool]]:
    """
    Per-environment, per-database readiness — what the health dashboard shows.

    The secret source is built once and shared across all sixteen checks. Built
    per call it would be sixteen times the vault round trips for one dashboard
    refresh, and the cache would never be warm.
    """
    if secrets is None:
        secrets = default_secret_source(os.environ if environ is None else environ)
    return {
        env: {key: not describe(env, key, environ, secrets).is_placeholder for key in DB_KEYS}
        for env in Environment
    }
