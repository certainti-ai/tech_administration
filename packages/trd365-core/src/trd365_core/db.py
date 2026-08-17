"""
Database connections, SSH tunnels, and reads that cannot hang forever.

Consolidates the connection layer that was copy-pasted byte-identically into
four separate modules. Behaviour worth preserving from the original is kept:
per-database tunnels, four connect attempts with linear backoff, and tearing a
partial tunnel down before retrying.

The pool takes its ``connect`` and ``tunnel_factory`` as arguments so the whole
class is exercisable against fakes — necessary here, because no Claude Code
session can reach these databases (docs/knowledge-base.md §5).
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from typing import Any

from .datamodel import DEFAULT_QUERY_TIMEOUT
from .environments import ConnectionSettings, Environment, connection_settings
from .errors import Trd365Error

CONNECT_ATTEMPTS = 4
BACKOFF_SECONDS = 5
CONNECT_TIMEOUT = 30


class ConnectionFailed(Trd365Error):
    """Every connect attempt failed."""


class QueryTimeout(Trd365Error):
    """A read exceeded its timeout — usually a dropped tunnel, not a slow query."""


def _default_connect(**kwargs: Any):
    import psycopg2

    return psycopg2.connect(**kwargs)


def _default_tunnel_factory(settings: ConnectionSettings):
    from sshtunnel import SSHTunnelForwarder

    tunnel = settings.ssh_tunnel
    assert tunnel is not None
    return SSHTunnelForwarder(
        (tunnel.ssh_host, tunnel.ssh_port),
        ssh_username=tunnel.ssh_user,
        ssh_password=tunnel.ssh_password,
        remote_bind_address=(settings.host, settings.port),
        local_bind_address=("127.0.0.1",),
    )


class ConnectionPool:
    """
    One connection per logical database key, for a single environment.

    A pool is bound to one :class:`Environment` at construction. Utilities
    therefore cannot accidentally hold connections to two environments at once,
    which is the mistake that turns a Dev cleanup into a Prod one.
    """

    def __init__(
        self,
        env: Environment,
        *,
        environ: dict[str, str] | None = None,
        connect: Callable[..., Any] = _default_connect,
        tunnel_factory: Callable[[ConnectionSettings], Any] = _default_tunnel_factory,
        log: Callable[[str], None] = print,
    ) -> None:
        self.env = env
        self._environ = environ
        self._connect = connect
        self._tunnel_factory = tunnel_factory
        self._log = log
        self._conns: dict[str, Any] = {}
        self._tunnels: dict[str, Any] = {}

    # ------------------------------------------------------------------ open

    def _open_tunnel(self, settings: ConnectionSettings) -> tuple[str, int]:
        tunnel = self._tunnel_factory(settings)
        tunnel.start()
        self._tunnels[settings.db_key] = tunnel
        port = tunnel.local_bind_port
        self._log(
            f"[tunnel] {settings.db_key}: 127.0.0.1:{port} -> {settings.host}:{settings.port}"
        )
        return "127.0.0.1", port

    def get(self, db_key: str, attempts: int = CONNECT_ATTEMPTS):
        """A live connection for ``db_key``, opening a tunnel first if needed."""
        cached = self._conns.get(db_key)
        if cached is not None:
            if getattr(cached, "closed", 0) == 0:
                return cached
            self.drop(db_key)  # cached connection died; reconnect below

        settings = connection_settings(self.env, db_key, self._environ)

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                host, port = settings.host, settings.port
                if settings.ssh_tunnel is not None:
                    host, port = self._open_tunnel(settings)

                conn = self._connect(
                    host=host,
                    port=port,
                    dbname=settings.dbname,
                    user=settings.user,
                    password=settings.password,
                    sslmode=settings.sslmode,
                    connect_timeout=CONNECT_TIMEOUT,
                )
                conn.autocommit = False
                self._conns[db_key] = conn
                return conn
            except Exception as exc:  # noqa: BLE001 — reported after retries
                last_error = exc
                self._stop_tunnel(db_key)  # never leave a half-open tunnel behind
                if attempt < attempts:
                    wait = BACKOFF_SECONDS * attempt
                    self._log(
                        f"[retry] {self.env.value}/{db_key} attempt {attempt}/{attempts} failed "
                        f"({type(exc).__name__}: {str(exc).strip()[:80]}); retrying in {wait}s…"
                    )
                    time.sleep(wait)

        raise ConnectionFailed(
            f"Could not connect to {self.env.value}/{db_key} "
            f"after {attempts} attempts: {last_error}"
        ) from last_error

    def verify(self, db_key: str) -> dict[str, str]:
        """Cheap identity probe. Feeds the health dashboard's connectivity tile."""
        conn = self.get(db_key)
        cur = conn.cursor()
        try:
            cur.execute("SELECT current_database(), current_user, version()")
            dbname, user, version = cur.fetchone()
        finally:
            cur.close()
            conn.rollback()
        return {"database": dbname, "user": user, "version": version.split(",")[0]}

    # ----------------------------------------------------------------- reads

    def fetch(
        self,
        db_key: str,
        query: str,
        params: list | None = None,
        timeout: int = DEFAULT_QUERY_TIMEOUT,
    ) -> list[tuple]:
        """
        Run a read with a watchdog.

        psycopg2 has no read timeout, so a tunnel that dies mid-query leaves a
        socket that never returns and the process hangs indefinitely. The query
        runs on a daemon thread; if it overruns, the connection is dropped to
        abort the read and the caller gets an exception it can skip past.
        """
        conn = self.get(db_key)
        result: dict[str, Any] = {}

        def work() -> None:
            try:
                cur = conn.cursor()
                if params is not None:
                    cur.execute(query, params)
                else:
                    cur.execute(query)
                result["rows"] = cur.fetchall()
                cur.close()
                conn.rollback()
            except BaseException as exc:  # noqa: BLE001 — handed to the caller
                result["error"] = exc

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        worker.join(timeout)

        if worker.is_alive():
            self.drop(db_key)
            raise QueryTimeout(
                f"{self.env.value}/{db_key}: read exceeded {timeout}s and was abandoned. "
                "The SSH tunnel has most likely dropped; the connection was discarded."
            )

        if "error" in result:
            raise result["error"]
        return result.get("rows", [])

    def fetcher(self) -> Callable[..., list[tuple]]:
        """A :class:`~trd365_core.datamodel.Fetcher` bound to this pool."""

        def fetch(db_key: str, query: str, params: list | None = None) -> list[tuple]:
            return self.fetch(db_key, query, params)

        return fetch

    # ----------------------------------------------------------------- close

    def _stop_tunnel(self, db_key: str) -> None:
        tunnel = self._tunnels.pop(db_key, None)
        if tunnel is not None:
            # Teardown failures must never mask the error that caused teardown.
            with contextlib.suppress(Exception):
                tunnel.stop()

    def drop(self, db_key: str) -> None:
        """Close and forget one connection, so the next ``get`` reconnects."""
        conn = self._conns.pop(db_key, None)
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()
        self._stop_tunnel(db_key)

    def close(self) -> None:
        for db_key in list(self._conns) + list(self._tunnels):
            self.drop(db_key)

    def __enter__(self) -> ConnectionPool:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
