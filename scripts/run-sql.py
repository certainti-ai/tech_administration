#!/usr/bin/env python3
"""
Run one .sql file against one database, through the bastion where there is one.

    run-sql.py --env prod --db orgdb --file path/to.sql          # dry: parse and report
    run-sql.py --env prod --db orgdb --file path/to.sql --apply

The scripts this exists for use psql meta-commands (``\\set ON_ERROR_STOP on``)
and rely on psql's transaction handling, so they are handed to psql rather than
executed statement by statement through a driver. The tunnel is opened here
because psql cannot open one itself.

Without ``--apply`` nothing is executed: the file is read, the statements are
counted and the connection is opened and closed. That is a real check — it
proves the tunnel, the credentials and the database are all working before
anything is run against them.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "trd365-core" / "src"))

from trd365_core.db import ConnectionPool  # noqa: E402
from trd365_core.environments import Environment, connection_settings  # noqa: E402


def statement_count(text: str) -> int:
    return sum(
        1
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("--", "\\"))
        and line.rstrip().endswith(";")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True, choices=[e.value for e in Environment])
    parser.add_argument("--db", required=True, help="maindb, orgdb or trd365ai")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="actually run it")
    args = parser.parse_args()

    if not args.file.is_file():
        print(f"no such file: {args.file}", file=sys.stderr)
        return 2

    # psql runs with cwd set to the file's directory, so that the `\i` lines in
    # the *_all.sql drivers resolve. The path handed to --file must therefore be
    # absolute, or psql looks for it relative to that new directory and fails.
    args.file = args.file.resolve()

    text = args.file.read_text()
    env = Environment(args.env)
    settings = connection_settings(env, args.db)
    print(f"file      {args.file}")
    print(f"target    {env.value}/{args.db} → {settings.host}")
    print(f"database  {settings.dbname} as {settings.user}")
    print(f"contains  {statement_count(text)} statement(s), {len(text.splitlines())} lines")

    # The pool opens the tunnel and reports the local port it forwards from.
    with ConnectionPool(env) as pool:
        pool.verify(args.db)
        # The pool records the forwarded port when it opens a tunnel; a database
        # reached directly has none, and psql then talks to the server itself.
        tunnel = pool._tunnels.get(args.db)
        host, port = (
            ("127.0.0.1", tunnel.local_bind_port) if tunnel else (settings.host, settings.port)
        )
        print(f"psql via  {host}:{port}" + ("  (bastion tunnel)" if tunnel else "  (direct)"))

        if not args.apply:
            print("\nDRY RUN — connection verified, nothing executed. Add --apply to run.")
            return 0

        # PGSSLMODE as well as the password. psql does not read our settings, and
        # its own default is `prefer` — which silently accepts an unencrypted
        # connection. For a tool that runs arbitrary SQL against production, the
        # transport has to be the one the environment declares, not psql's guess.
        environment = dict(
            os.environ,
            PGPASSWORD=settings.password,
            PGSSLMODE=settings.sslmode,
        )
        command = [
            "psql",
            "--host", str(host),
            "--port", str(port),
            "--username", settings.user,
            "--dbname", settings.dbname,
            "--set", "ON_ERROR_STOP=on",
            "--echo-errors",
            "--no-psqlrc",
            "--file", str(args.file),
        ]
        print(f"\nrunning: psql … --file {args.file.name}\n")
        result = subprocess.run(command, env=environment, cwd=args.file.parent)
        print(f"\npsql exited {result.returncode}")
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
