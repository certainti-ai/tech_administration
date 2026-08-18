"""
Executing a utility as a subprocess, with output streamed and cancellation that
gives the tool a chance to clean up.

Utilities are command-line programs that open database transactions. Killing one
outright can leave a purge half-applied, so cancellation is SIGTERM first, with
a grace period for the tool to roll back, and SIGKILL only if it will not go.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections.abc import Awaitable, Callable
from typing import Protocol

OutputCallback = Callable[[str], None]

#: Seconds a utility gets to roll back after SIGTERM before it is killed.
TERMINATE_GRACE_SECONDS = 30


class Runner(Protocol):
    async def run(
        self,
        argv: list[str],
        on_output: OutputCallback,
        cancel: asyncio.Event,
    ) -> int: ...


class SubprocessRunner:
    """Runs the utility in its own process group so cancellation reaches children."""

    def __init__(
        self,
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        grace_seconds: float = TERMINATE_GRACE_SECONDS,
    ) -> None:
        self._env = env
        self._cwd = cwd
        self._grace = grace_seconds

    async def run(
        self,
        argv: list[str],
        on_output: OutputCallback,
        cancel: asyncio.Event,
    ) -> int:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=self._env,
            cwd=self._cwd,
            # Its own process group, so a SIGTERM reaches psql or an ssh tunnel
            # the utility started rather than only the parent.
            start_new_session=True,
        )

        async def pump() -> None:
            assert process.stdout is not None
            async for raw in process.stdout:
                on_output(raw.decode(errors="replace").rstrip("\n"))

        async def watch_cancel() -> None:
            await cancel.wait()
            await self._stop(process, on_output)

        pump_task = asyncio.create_task(pump())
        cancel_task = asyncio.create_task(watch_cancel())
        try:
            exit_code = await process.wait()
            await pump_task
        finally:
            cancel_task.cancel()

        return exit_code

    async def _stop(self, process: asyncio.subprocess.Process, on_output: OutputCallback) -> None:
        if process.returncode is not None:
            return

        on_output("[orchestrator] cancellation requested; sending SIGTERM")
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return

        try:
            await asyncio.wait_for(process.wait(), timeout=self._grace)
            on_output("[orchestrator] utility exited after SIGTERM")
        except TimeoutError:
            on_output(
                f"[orchestrator] still running after {self._grace:.0f}s; sending SIGKILL. "
                "The database may hold an incomplete transaction — check before re-running."
            )
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)


class CallableRunner:
    """
    Runs an ordinary coroutine instead of a process.

    Used by the tests, and by any future utility that is better invoked in
    process than shelled out to.
    """

    def __init__(self, fn: Callable[[list[str], OutputCallback, asyncio.Event], Awaitable[int]]):
        self._fn = fn

    async def run(
        self,
        argv: list[str],
        on_output: OutputCallback,
        cancel: asyncio.Event,
    ) -> int:
        return await self._fn(argv, on_output, cancel)
