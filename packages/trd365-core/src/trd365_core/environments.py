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
            raise ConfigError(
                f'Unknown environment "{value}". Expected one of: {valid}.'
            ) from None


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
            replace(self.ssh_tunnel, ssh_password="***")
            if self.ssh_tunnel is not None
            else None
        )
        return replace(self, password="***", ssh_tunnel=tunnel)


# --------------------------------------------------------------------------
# Known non-secret topology.
#
# Only prod is known today. Host/dbname/user are not secrets (see
# SANITIZATION_NOTE.md in the legacy tree) and live here so the shape of each
# environment is reviewable in code. Passwords never appear here.
# --------------------------------------------------------------------------

_PROD_BASTION = {
    "ssh_host": "172.203.151.166",
    "ssh_port": 22,
    "ssh_user": "thinkrd_DevOps",
}

_KNOWN_TOPOLOGY: dict[Environment, dict[str, dict[str, object]]] = {
    Environment.PROD: {
        "maindb": {
            "host": "prod-thinkrd365-psqlserver-centralus-pvt-main.postgres.database.azure.com",
            "port": 5432,
            "dbname": "thinkrd365_pvt_main",
            "user": "adminUser",
            "sslmode": "require",
            "tunnel": _PROD_BASTION,
        },
        "orgdb": {
            "host": "prod-thinkrd365-psqlserver-centralus-pvt-org.postgres.database.azure.com",
            "port": 5432,
            "dbname": "thinkrd365_pvt_org",
            "user": "adminUser",
            "sslmode": "require",
            "tunnel": _PROD_BASTION,
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

#: Dev/QA/Stage are unknown. Each gets the prod *shape* with placeholder values,
#: so tooling, the registry and the UI can enumerate them before real
#: credentials arrive. See docs/HANDOFF.md open question 1.
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


def _lookup(env: Environment, db_key: str, field: str, environ: dict[str, str]) -> str | None:
    """Environment-scoped name first, then the legacy unscoped name for prod."""
    scoped = f"TRD365_{env.value.upper()}_{db_key.upper()}_{field.upper()}"
    if scoped in environ and environ[scoped] != "":
        return environ[scoped]
    if env.is_production:
        legacy = f"{db_key.upper()}_{field.upper()}"
        if legacy in environ and environ[legacy] != "":
            return environ[legacy]
    return None


def describe(
    env: Environment,
    db_key: str,
    environ: dict[str, str] | None = None,
) -> ConnectionSettings:
    """
    Build settings for one database, without judging whether they are usable.

    Placeholders are returned as-is. Use :func:`connection_settings` when you
    intend to connect — it refuses placeholders.
    """
    if db_key not in DB_KEYS:
        raise ConfigError(
            f'Unknown database key "{db_key}". Expected one of: {", ".join(DB_KEYS)}.'
        )

    environ = os.environ if environ is None else environ
    known = _KNOWN_TOPOLOGY.get(env, _PLACEHOLDER_TOPOLOGY)[db_key]

    def field(name: str, fallback: object) -> str:
        found = _lookup(env, db_key, name, environ)
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
) -> ConnectionSettings:
    """
    Settings for a database you intend to connect to.

    Raises :class:`PlaceholderCredentialError` if the environment has not been
    configured, naming the variables that would supply it.
    """
    settings = describe(env, db_key, environ)
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


def is_configured(env: Environment, environ: dict[str, str] | None = None) -> bool:
    """Whether every database in an environment has real credentials."""
    return all(not describe(env, key, environ).is_placeholder for key in DB_KEYS)


def configuration_status(
    environ: dict[str, str] | None = None,
) -> dict[Environment, dict[str, bool]]:
    """Per-environment, per-database readiness — what the health dashboard shows."""
    return {
        env: {key: not describe(env, key, environ).is_placeholder for key in DB_KEYS}
        for env in Environment
    }
