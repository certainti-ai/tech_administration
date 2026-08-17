"""Connection management with optional SSH tunnels (per-DB, from db_config.json).

Inherited from account_deletion/engine/db.py — same tunnel setup, retry/backoff
and connection logging — with two additions used by the fiscal-year runner:
  * notice buffers are collected into an unbounded deque (psycopg2's default list
    silently keeps only the last ~50 notices; SECTION 1 emits more than that and
    the backup-schema announcement must never be dropped), and
  * rollback_all() so a --dry-run can discard every uncommitted section at once.
"""

import getpass
import json
import os
import sys
import time
from pathlib import Path


class NoticeSink:
    """Collects PostgreSQL NOTICE messages. psycopg2 calls append() as each notice
    is delivered; the runner reads `.last` for a live heartbeat while a section is
    still running and `.snapshot()` for the full list once it finishes. Replaces
    psycopg2's default list (which silently keeps only the last ~50)."""

    def __init__(self):
        self._items = []

    def append(self, msg):
        self._items.append(str(msg).rstrip("\n"))

    def clear(self):
        self._items = []

    def __iter__(self):
        return iter(list(self._items))

    def snapshot(self):
        return list(self._items)

    @property
    def last(self):
        items = self._items
        return items[-1] if items else None

try:
    import psycopg2
    from psycopg2 import errorcodes  # noqa: F401  (re-exported for callers)
except ImportError:
    sys.exit("psycopg2 is required. Install with:  pip install -r requirements.txt")

try:
    from sshtunnel import SSHTunnelForwarder
except ImportError:
    SSHTunnelForwarder = None


def load_config(config_path):
    p = Path(config_path)
    if not p.exists():
        sys.exit(f"Config not found: {p}")
    with open(p) as fh:
        return json.load(fh)


class ConnectionPool:
    """One connection per logical DB key; opens an SSH tunnel first if configured."""

    def __init__(self, config):
        self.config = config
        self._conns = {}
        self._tunnels = {}

    def _tunnel(self, db_key, tcfg, remote_host, remote_port):
        if SSHTunnelForwarder is None:
            sys.exit(f"DB '{db_key}' needs an SSH tunnel but 'sshtunnel' is not installed.")
        pw = (tcfg.get("ssh_password")
              or os.environ.get(f"SSH_{db_key.upper()}_PASSWORD")
              or os.environ.get("SSH_TUNNEL_PASSWORD"))
        if not pw:
            pw = getpass.getpass(f"SSH password {tcfg.get('ssh_user')}@{tcfg.get('ssh_host')}: ")
        t = SSHTunnelForwarder(
            (tcfg["ssh_host"], int(tcfg.get("ssh_port", 22))),
            ssh_username=tcfg["ssh_user"], ssh_password=pw,
            remote_bind_address=(remote_host, int(remote_port)),
            local_bind_address=("127.0.0.1",),
        )
        t.start()
        self._tunnels[db_key] = t
        print(f"[tunnel] {db_key}: 127.0.0.1:{t.local_bind_port} -> {remote_host}:{remote_port}")
        return "127.0.0.1", t.local_bind_port

    def get(self, db_key, retries=4):
        if db_key in self._conns:
            c = self._conns[db_key]
            if getattr(c, "closed", 0) == 0:
                return c
            self.drop(db_key)  # dead cached connection — reconnect below
        if db_key not in self.config:
            sys.exit(f"No connection config for DB key '{db_key}'.")
        base = dict(self.config[db_key])
        base.pop("_comment", None)
        tcfg = base.pop("ssh_tunnel", None)
        pw = base.get("password") or os.environ.get(f"PG_{db_key.upper()}_PASSWORD")
        if not pw:
            pw = getpass.getpass(f"DB password for {db_key}: ")

        last = None
        for attempt in range(1, retries + 1):
            try:
                params = dict(base)
                if tcfg:
                    host, port = self._tunnel(db_key, tcfg, base["host"], base.get("port", 5432))
                    params["host"], params["port"] = host, port
                params["password"] = pw
                params["connect_timeout"] = params.get("connect_timeout", 30)
                conn = psycopg2.connect(**params)
                conn.autocommit = False
                # Custom sink: unbounded (psycopg2's default list keeps only the
                # last ~50 notices, and SECTION 1 emits more than that) and exposes
                # `.last` so the runner can show live progress mid-section.
                conn.notices = NoticeSink()
                self._conns[db_key] = conn
                print(f"[connect] {db_key}: connected "
                      f"({params.get('host')}:{params.get('port')}/{params.get('dbname')})")
                return conn
            except Exception as exc:
                last = exc
                t = self._tunnels.pop(db_key, None)  # tear down partial tunnel
                if t:
                    try:
                        t.stop()
                    except Exception:
                        pass
                if attempt < retries:
                    wait = 5 * attempt
                    print(f"[retry] {db_key} connect attempt {attempt}/{retries} failed "
                          f"({type(exc).__name__}: {str(exc).strip()[:80]}); retrying in {wait}s…")
                    time.sleep(wait)
        raise last

    def rollback_all(self):
        """Roll back every open connection (used by --dry-run to discard changes)."""
        for c in self._conns.values():
            try:
                c.rollback()
            except Exception:
                pass

    def drop(self, db_key):
        """Close + forget a connection (and its tunnel) so the next get() reconnects."""
        c = self._conns.pop(db_key, None)
        if c:
            try:
                c.close()
            except Exception:
                pass
        t = self._tunnels.pop(db_key, None)
        if t:
            try:
                t.stop()
            except Exception:
                pass

    def drop_all(self):
        for db_key in list(self._conns) + list(self._tunnels):
            self.drop(db_key)

    def close_all(self):
        for c in self._conns.values():
            try:
                c.close()
            except Exception:
                pass
        for t in self._tunnels.values():
            try:
                t.stop()
            except Exception:
                pass
