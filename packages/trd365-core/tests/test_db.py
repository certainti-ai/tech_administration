"""
Connection pool behaviour, verified against fakes.

No Claude Code session can reach these databases (docs/knowledge-base.md §5),
so the pool takes its connect and tunnel factories as arguments and every
behaviour below is exercised without a driver.
"""

import pytest

from trd365_core.db import ConnectionFailed, ConnectionPool, QueryTimeout
from trd365_core.environments import Environment
from trd365_core.errors import PlaceholderCredentialError

PROD_ENV = {
    "MAINDB_HOST": "main.example.internal",
    "MAINDB_DBNAME": "main",
    "MAINDB_USER": "admin",
    "MAINDB_PASSWORD": "pw",
    "MAINDB_SSH_HOST": "10.0.0.1",
    "MAINDB_SSH_USER": "devops",
    "MAINDB_SSH_PASSWORD": "bastion",
    "ORGDB_HOST": "org.example.internal",
    "ORGDB_DBNAME": "org",
    "ORGDB_USER": "admin",
    "ORGDB_PASSWORD": "pw",
    "ORGDB_SSH_HOST": "10.0.0.1",
    "ORGDB_SSH_USER": "devops",
    "ORGDB_SSH_PASSWORD": "bastion",
    "TRD365AI_HOST": "ai.example.internal",
    "TRD365AI_DBNAME": "ai",
    "TRD365AI_USER": "aiadmin",
    "TRD365AI_PASSWORD": "pw",
}


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, query, params=None):
        self._conn.queries.append((query, params))
        if self._conn.raise_on_execute:
            raise self._conn.raise_on_execute

    def fetchall(self):
        return self._conn.rows

    def fetchone(self):
        return self._conn.rows[0]

    def close(self):
        pass


class FakeConnection:
    def __init__(self, rows=None, raise_on_execute=None):
        self.rows = rows if rows is not None else []
        self.raise_on_execute = raise_on_execute
        self.queries = []
        self.closed = 0
        self.autocommit = None
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = 1


class FakeTunnel:
    def __init__(self):
        self.local_bind_port = 15432
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def make_pool(connect=None, tunnel_factory=None, environ=None, env=Environment.PROD):
    tunnels = []

    def default_tunnel_factory(settings):
        tunnel = FakeTunnel()
        tunnels.append(tunnel)
        return tunnel

    pool = ConnectionPool(
        env,
        environ=environ if environ is not None else PROD_ENV,
        connect=connect or (lambda **kw: FakeConnection()),
        tunnel_factory=tunnel_factory or default_tunnel_factory,
        log=lambda _msg: None,
    )
    return pool, tunnels


class TestConnecting:
    def test_opens_a_tunnel_and_connects_through_it(self):
        seen = {}

        def connect(**kwargs):
            seen.update(kwargs)
            return FakeConnection()

        pool, tunnels = make_pool(connect=connect)
        pool.get("maindb")

        assert tunnels[0].started
        assert seen["host"] == "127.0.0.1"
        assert seen["port"] == 15432  # the tunnel's local port, not 5432
        assert seen["dbname"] == "main"

    def test_connects_directly_when_no_tunnel_is_configured(self):
        seen = {}

        def connect(**kwargs):
            seen.update(kwargs)
            return FakeConnection()

        pool, tunnels = make_pool(connect=connect)
        pool.get("trd365ai")

        assert tunnels == []  # trd365ai is reached directly
        assert seen["host"] == "ai.example.internal"

    def test_connections_are_reused(self):
        calls = []
        pool, _ = make_pool(connect=lambda **kw: calls.append(1) or FakeConnection())
        first = pool.get("maindb")
        assert pool.get("maindb") is first
        assert len(calls) == 1

    def test_a_closed_connection_is_replaced(self):
        pool, _ = make_pool()
        first = pool.get("maindb")
        first.closed = 1
        assert pool.get("maindb") is not first

    def test_autocommit_is_disabled(self):
        pool, _ = make_pool()
        assert pool.get("maindb").autocommit is False

    def test_placeholder_environments_refuse_before_any_connection(self):
        attempted = []
        pool, _ = make_pool(
            connect=lambda **kw: attempted.append(1), environ={}, env=Environment.DEV
        )
        with pytest.raises(PlaceholderCredentialError):
            pool.get("maindb")
        assert attempted == []


class TestRetry:
    def test_retries_then_succeeds(self, monkeypatch):
        monkeypatch.setattr("trd365_core.db.time.sleep", lambda _s: None)
        attempts = []

        def connect(**kwargs):
            attempts.append(1)
            if len(attempts) < 3:
                raise OSError("connection refused")
            return FakeConnection()

        pool, _ = make_pool(connect=connect)
        assert pool.get("maindb") is not None
        assert len(attempts) == 3

    def test_gives_up_after_the_configured_attempts(self, monkeypatch):
        monkeypatch.setattr("trd365_core.db.time.sleep", lambda _s: None)

        def connect(**kwargs):
            raise OSError("connection refused")

        pool, _ = make_pool(connect=connect)
        with pytest.raises(ConnectionFailed, match="after 4 attempts"):
            pool.get("maindb")

    def test_a_failed_attempt_tears_its_tunnel_down(self, monkeypatch):
        """A partial tunnel left open would leak a port on every retry."""
        monkeypatch.setattr("trd365_core.db.time.sleep", lambda _s: None)
        tunnels = []

        def tunnel_factory(settings):
            tunnel = FakeTunnel()
            tunnels.append(tunnel)
            return tunnel

        def connect(**kwargs):
            raise OSError("refused")

        pool, _ = make_pool(connect=connect, tunnel_factory=tunnel_factory)
        with pytest.raises(ConnectionFailed):
            pool.get("maindb")

        assert len(tunnels) == 4
        assert all(t.stopped for t in tunnels)


class TestFetch:
    def test_returns_rows_and_ends_the_transaction(self):
        conn = FakeConnection(rows=[("project", "rid")])
        pool, _ = make_pool(connect=lambda **kw: conn)

        assert pool.fetch("maindb", "SELECT 1") == [("project", "rid")]
        assert conn.rollbacks == 1

    def test_passes_parameters_through(self):
        conn = FakeConnection(rows=[])
        pool, _ = make_pool(connect=lambda **kw: conn)
        pool.fetch("maindb", "SELECT %s", ["trd365_00042"])
        assert conn.queries == [("SELECT %s", ["trd365_00042"])]

    def test_query_errors_propagate(self):
        conn = FakeConnection(raise_on_execute=ValueError("bad sql"))
        pool, _ = make_pool(connect=lambda **kw: conn)
        with pytest.raises(ValueError, match="bad sql"):
            pool.fetch("maindb", "SELECT 1")

    def test_a_hung_read_times_out_and_drops_the_connection(self):
        """
        psycopg2 has no read timeout, so a dropped tunnel would otherwise hang
        the process forever. The watchdog must abandon the read.
        """
        import time as _time

        class HangingCursor(FakeCursor):
            def execute(self, query, params=None):
                _time.sleep(5)

        conn = FakeConnection()
        conn.cursor = lambda: HangingCursor(conn)  # type: ignore[method-assign]
        pool, _ = make_pool(connect=lambda **kw: conn)

        with pytest.raises(QueryTimeout, match="tunnel"):
            pool.fetch("maindb", "SELECT 1", timeout=1)
        assert conn.closed == 1

    def test_fetcher_matches_the_datamodel_protocol(self):
        from trd365_core import datamodel as dm

        conn = FakeConnection(rows=[("project", "rid"), ("task", "project_rid")])
        pool, _ = make_pool(connect=lambda **kw: conn)

        catalog = dm.load_catalog(pool.fetcher(), "orgdb", "trd365_00042")
        assert catalog.tables["project"].has_pk
        assert catalog.tables["task"].fk_columns == ["project_rid"]


class TestVerify:
    def test_reports_identity(self):
        conn = FakeConnection(rows=[("main", "admin", "PostgreSQL 15.4, compiled")])
        pool, _ = make_pool(connect=lambda **kw: conn)
        assert pool.verify("maindb") == {
            "database": "main",
            "user": "admin",
            "version": "PostgreSQL 15.4",
        }


class TestTeardown:
    def test_close_shuts_connections_and_tunnels(self):
        conn = FakeConnection()
        pool, tunnels = make_pool(connect=lambda **kw: conn)
        pool.get("maindb")
        pool.close()

        assert conn.closed == 1
        assert tunnels[0].stopped

    def test_context_manager_closes(self):
        conn = FakeConnection()
        with ConnectionPool(
            Environment.PROD,
            environ=PROD_ENV,
            connect=lambda **kw: conn,
            tunnel_factory=lambda s: FakeTunnel(),
            log=lambda _m: None,
        ) as pool:
            pool.get("maindb")
        assert conn.closed == 1

    def test_a_pool_is_bound_to_one_environment(self):
        """Holding two environments at once is how a Dev job hits Prod."""
        pool, _ = make_pool()
        assert pool.env is Environment.PROD
        assert not hasattr(pool, "set_env")
