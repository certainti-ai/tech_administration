"""
Credentials from Azure Key Vault.

Why this exists
---------------
:mod:`trd365_core.environments` resolves credentials from the process
environment. On a laptop that environment is populated by `scripts/secrets/`;
on the maintenance VM nothing populated it, because that tooling is Node and the
VM has no Node runtime. So the VM could read the vault with its managed identity
and the utilities still saw nothing — the credentials were one API call away and
invisible. This closes that gap in Python.

Three properties matter more than convenience here:

**Absent, never wrong.** A miss returns ``None`` so the caller falls back to a
placeholder and fails loudly. A vault that is unreachable must never look like a
vault that answered.

**Injectable.** No session can reach a real vault, so the resolver is a Protocol
and every test drives a dictionary. The Azure SDK import is lazy for the same
reason: importing this module must not require the SDK to be installed.

**Cached per process.** A purge resolves the same credentials repeatedly and a
vault call is a network round trip; and the audit trail should show one read, not
forty.
"""

from __future__ import annotations

import os
import re
from typing import Protocol, runtime_checkable

from .errors import ConfigError

#: Key Vault's own constraint on secret names.
SECRET_NAME_PATTERN = re.compile(r"^[0-9a-zA-Z-]{1,127}$")

_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Names the vault client is read from, matching what cloud-init writes.
VAULT_NAME_ENV = "AZURE_KEY_VAULT_NAME"
CLIENT_ID_ENV = "AZURE_CLIENT_ID"


def to_secret_name(env_name: str) -> str:
    """
    The vault secret name for an environment variable.

    Deliberately identical to ``toVaultName`` in ``scripts/secrets/naming.mjs``:
    the Node tooling writes these names and this reads them, so the two
    transforms drifting apart would mean silently reading nothing.

    Not reversible, and not used in reverse — ``TF_VAR_repo_pat`` would come back
    as ``TF_VAR_REPO_PAT``, which Terraform matches case-sensitively and would
    ignore. The manifest carries the exact environment name for that reason.
    """
    if not _ENV_NAME_PATTERN.match(env_name or ""):
        raise ConfigError(f'Not a valid environment variable name: "{env_name}"')
    return env_name.lower().replace("_", "-")


def is_valid_secret_name(name: str) -> bool:
    return bool(SECRET_NAME_PATTERN.match(name or ""))


@runtime_checkable
class SecretSource(Protocol):
    """Anything that can produce a secret by name. ``None`` means absent."""

    def get(self, name: str) -> str | None: ...


class NoVault:
    """The null source, used when no vault is configured. Always absent."""

    def get(self, name: str) -> str | None:  # noqa: ARG002 - deliberate no-op
        return None


class MappingVault:
    """A source backed by a dict. For tests, and for previewing a resolution."""

    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self.secrets = dict(secrets or {})
        #: Every name asked for, in order. Lets a test assert on the caching.
        self.requested: list[str] = []

    def get(self, name: str) -> str | None:
        self.requested.append(name)
        return self.secrets.get(name)


class KeyVaultSecrets:
    """
    Reads Azure Key Vault, caching each answer — including a miss.

    The Azure SDK is imported on first use rather than at module import, so that
    ``import trd365_core`` works in an environment without it. That is not
    hypothetical: CI and every Claude Code session are exactly that environment.
    """

    def __init__(
        self,
        vault_name: str,
        *,
        client_id: str | None = None,
        client=None,
    ) -> None:
        if not vault_name:
            raise ConfigError("A Key Vault name is required.")
        self.vault_name = vault_name
        self.client_id = client_id
        self._client = client
        self._cache: dict[str, str | None] = {}
        self._listed: set[str] | None = None
        self._listing_failed = False

    @property
    def url(self) -> str:
        return f"https://{self.vault_name}.vault.azure.net"

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient
        except ImportError as exc:  # pragma: no cover - depends on the host
            raise ConfigError(
                "Reading credentials from Key Vault needs the Azure SDK.\n"
                "Install it with:  pip install 'trd365-core[azure]'"
            ) from exc

        # managed_identity_client_id names the *user-assigned* identity. Without
        # it, a VM with more than one identity attached gets an arbitrary one.
        credential = DefaultAzureCredential(
            managed_identity_client_id=self.client_id or None
        )
        self._client = SecretClient(vault_url=self.url, credential=credential)
        return self._client

    def _names(self) -> set[str] | None:
        """
        Every secret name in the vault, listed once.

        This exists for the misses, not the hits. Resolving readiness for four
        environments across three databases asks for well over a hundred names,
        and for an environment whose credentials have never been supplied every
        one is absent. Fetched individually that is a hundred sequential round
        trips to discover nothing — enough to make the health endpoint time out,
        which is exactly what it did the first time it was called through the
        public site. One list call answers all of them.

        ``None`` means the listing itself failed, in which case fall back to
        asking per name rather than concluding the vault is empty.
        """
        if self._listed is None:
            try:
                client = self._ensure_client()
                self._listed = {
                    prop.name for prop in client.list_properties_of_secrets() if prop.name
                }
            except ConfigError:
                raise
            except Exception:  # noqa: BLE001 — fall back to per-name lookups
                self._listed = set()
                self._listing_failed = True
        return None if self._listing_failed else self._listed

    def get(self, name: str) -> str | None:
        if name in self._cache:
            return self._cache[name]
        if not is_valid_secret_name(name):
            self._cache[name] = None
            return None

        known = self._names()
        if known is not None and name not in known:
            # Absent, established without a request for it.
            self._cache[name] = None
            return None

        try:
            secret = self._ensure_client().get_secret(name)
            value = secret.value
        except ConfigError:
            raise
        except Exception:  # noqa: BLE001
            # A miss and an outage both mean "not available from here", and the
            # caller's job is to fail loudly on a placeholder either way.
            # Swallowing the detail is deliberate: this runs in a loop over every
            # credential field, and one unreachable vault must not produce forty
            # stack traces in an operator's terminal.
            value = None

        self._cache[name] = value
        return value


def default_secret_source(environ: dict[str, str] | None = None) -> SecretSource:
    """
    A vault source from the ambient environment, or :class:`NoVault`.

    ``AZURE_KEY_VAULT_NAME`` is what cloud-init writes to
    ``/etc/trd365/environment``, so on the VM this is configured and everywhere
    else it is not — which is the behaviour wanted in both places.
    """
    environ = os.environ if environ is None else environ
    vault_name = environ.get(VAULT_NAME_ENV, "").strip()
    if not vault_name:
        return NoVault()
    return KeyVaultSecrets(vault_name, client_id=environ.get(CLIENT_ID_ENV) or None)
