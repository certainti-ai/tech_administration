"""
That the loader script writes the names the resolver reads.

``scripts/secrets/set-environment.sh`` derives 26 Key Vault secret names per
environment; :mod:`trd365_core.environments` looks a subset of those names up.
The two agreeing is not decorative. A name that is close but wrong does not
error anywhere: :func:`describe` falls back to the placeholder for that field,
:func:`connection_settings` then refuses to connect, and the message names a
credential whoever ran the script is certain they supplied. That is a bad hour.

So the field lists are compared directly, in both directions:

* a field the script writes and the resolver never reads is a secret sitting in
  a vault for no reason;
* a field the resolver reads and the script does not write is an environment
  that looks configured and is not.

The resolver's side is read out of its own source rather than restated here,
because a list restated in a test is a list that agrees with the test and not
with the code.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from trd365_core import environments
from trd365_core.environments import DB_KEYS, Environment
from trd365_core.vault import to_secret_name

REPO_ROOT = Path(__file__).resolve().parents[3]
LOADER = REPO_ROOT / "scripts" / "secrets" / "set-environment.sh"
TEMPLATE = REPO_ROOT / "scripts" / "secrets" / "environment.env.example"

# The tunnel fields are only read for databases that have one, so they are
# tracked separately rather than as part of one flat set.
_TUNNEL_FIELDS = frozenset({"ssh_host", "ssh_port", "ssh_user", "ssh_password"})


def fields_the_resolver_reads() -> set[str]:
    """Every field name passed to the local ``field()`` helper in ``describe``."""
    source = inspect.getsource(environments.describe)
    found = set(re.findall(r'\bfield\(\s*"([a-z_]+)"', source))
    assert found, "no field() calls found — has describe() been rewritten?"
    return found


def fields_the_loader_writes() -> dict[str, list[str]]:
    """The per-database field lists declared in the shell script."""
    text = LOADER.read_text()
    out: dict[str, list[str]] = {}
    for db_key in DB_KEYS:
        variable = f"{db_key.upper()}_FIELDS"
        match = re.search(rf'^{variable}="([^"]*)"', text, re.MULTILINE)
        assert match, f"{variable} is not declared in {LOADER.name}"
        value = match.group(1)
        if value.startswith("$"):  # e.g. ORGDB_FIELDS="$MAINDB_FIELDS"
            value = out["maindb"]
            out[db_key] = list(value)
            continue
        out[db_key] = value.lower().split()
    return out


class TestTheTwoListsAgree:
    def test_every_field_the_resolver_reads_is_written_for_some_database(self):
        written = set().union(*fields_the_loader_writes().values())
        assert fields_the_resolver_reads() <= written

    def test_the_loader_writes_nothing_the_resolver_ignores(self):
        written = set().union(*fields_the_loader_writes().values())
        assert written <= fields_the_resolver_reads()

    def test_only_the_bastion_databases_get_tunnel_fields(self):
        written = fields_the_loader_writes()
        # trd365ai is a direct connection. Writing ssh_* for it would be
        # harmless and misleading — the resolver builds no tunnel for it, so the
        # values would sit unread and look like configuration.
        assert not _TUNNEL_FIELDS & set(written["trd365ai"])
        for db_key in ("maindb", "orgdb"):
            assert set(written[db_key]) >= _TUNNEL_FIELDS


class TestTheNamesThemselves:
    @pytest.mark.parametrize("env", [e for e in Environment if not e.is_production])
    def test_the_scoped_name_is_what_the_resolver_would_ask_for(self, env):
        # Reproduces the script's transform (lowercase, underscores to hyphens)
        # through the function the resolver itself uses, for every field of
        # every database, so a divergence in either fails here rather than in a
        # vault nobody is looking at.
        written = fields_the_loader_writes()
        for db_key in DB_KEYS:
            for field in written[db_key]:
                variable = f"TRD365_{env.value.upper()}_{db_key.upper()}_{field.upper()}"
                expected = f"trd365-{env.value}-{db_key}-{field.replace('_', '-')}"
                assert to_secret_name(variable) == expected

    def test_the_template_offers_exactly_the_fields_the_loader_expects(self):
        # The template is what a person fills in. A field missing from it is a
        # MISSING line at the end of a form somebody thought they had completed.
        declared = {
            line.split("=", 1)[0].strip()
            for line in TEMPLATE.read_text().splitlines()
            if line.strip() and not line.startswith("#") and "=" in line
        }
        written = fields_the_loader_writes()
        expected = {
            f"{db_key.upper()}_{field.upper()}"
            for db_key in DB_KEYS
            for field in written[db_key]
        }
        assert declared == expected
