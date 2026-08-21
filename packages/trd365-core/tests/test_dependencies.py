"""
That the real dependency set actually works.

Every other test fakes the tunnel and the driver, which is right — no test should
need a bastion or a database. The cost is that a broken dependency *combination*
is invisible: `sshtunnel` 0.4.0 reads `paramiko.DSSKey`, paramiko 4 removed it
with the rest of DSA, and unpinned pip installs paramiko 5. The whole suite passed
and the first real connection from the VM died with
`module 'paramiko' has no attribute 'DSSKey'` after four retries.

These tests exercise the imports the faked paths stand in for. They are skipped
where the optional dependency is genuinely absent, so they add a guard without
making the suite require anything new.
"""

from __future__ import annotations

import pytest


class TestSshTunnel:
    def test_the_tunnel_forwarder_is_importable(self):
        sshtunnel = pytest.importorskip("sshtunnel")
        assert hasattr(sshtunnel, "SSHTunnelForwarder")

    def test_paramiko_still_has_what_sshtunnel_reads(self):
        # sshtunnel names these three key classes directly. Any of them
        # disappearing breaks every tunnel at runtime, not at import.
        pytest.importorskip("sshtunnel")
        paramiko = pytest.importorskip("paramiko")
        for attribute in ("RSAKey", "DSSKey", "ECDSAKey"):
            assert hasattr(paramiko, attribute), (
                f"paramiko has no {attribute}; sshtunnel reads it directly, so "
                f"every SSH tunnel will fail at connection time. Check the "
                f"paramiko pin in pyproject.toml."
            )

    def test_the_real_factory_builds_a_forwarder_without_connecting(self):
        # Constructing SSHTunnelForwarder resolves the key types but opens no
        # socket, so this reaches the code the fakes replace.
        pytest.importorskip("sshtunnel")
        pytest.importorskip("paramiko")
        from trd365_core.db import _default_tunnel_factory
        from trd365_core.environments import ConnectionSettings, SshTunnel

        settings = ConnectionSettings(
            db_key="maindb",
            host="db.internal",
            port=5432,
            dbname="d",
            user="u",
            password="p",
            sslmode="require",
            ssh_tunnel=SshTunnel(
                ssh_host="127.0.0.1", ssh_port=22, ssh_user="ops", ssh_password="x"
            ),
        )
        forwarder = _default_tunnel_factory(settings)
        assert forwarder is not None


class TestDriver:
    def test_psycopg2_is_importable_and_exposes_what_the_engine_uses(self):
        psycopg2 = pytest.importorskip("psycopg2")
        # The purge engine branches on pgcode to detect a foreign-key violation.
        assert hasattr(psycopg2, "connect")
        assert hasattr(psycopg2, "Error")
