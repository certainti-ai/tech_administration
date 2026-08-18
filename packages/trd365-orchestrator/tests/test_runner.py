"""
SubprocessRunner against real processes.

This is the component that actually launches a purge, so testing it with a fake
would test nothing that matters. Cancellation in particular has to be verified
for real: a utility killed outright mid-transaction can leave a purge
half-applied, so it must get SIGTERM and a chance to roll back first.
"""

import asyncio
import sys
import time

from trd365_orchestrator.runner import SubprocessRunner


async def run(argv, *, grace=5.0, cancel_after=None):
    output: list[str] = []
    cancel = asyncio.Event()
    runner = SubprocessRunner(grace_seconds=grace)

    async def trigger():
        await asyncio.sleep(cancel_after)
        cancel.set()

    tasks = [asyncio.create_task(runner.run(argv, output.append, cancel))]
    if cancel_after is not None:
        tasks.append(asyncio.create_task(trigger()))

    exit_code = await tasks[0]
    for task in tasks[1:]:
        task.cancel()
    return exit_code, output


class TestExecution:
    async def test_returns_the_exit_code(self):
        code, _ = await run([sys.executable, "-c", "raise SystemExit(0)"])
        assert code == 0

    async def test_a_nonzero_exit_is_reported(self):
        code, _ = await run([sys.executable, "-c", "raise SystemExit(7)"])
        assert code == 7

    async def test_stdout_is_streamed(self):
        code, output = await run(
            [sys.executable, "-c", "print('first'); print('second')"]
        )
        assert code == 0
        assert output == ["first", "second"]

    async def test_stderr_is_captured_too(self):
        # A utility's diagnostics belong in the job log, not lost.
        _, output = await run(
            [sys.executable, "-c", "import sys; print('boom', file=sys.stderr)"]
        )
        assert "boom" in output

    async def test_output_is_decoded_leniently(self):
        # Undecodable bytes must not take down the job.
        _, output = await run(
            [sys.executable, "-c", r"import sys; sys.stdout.buffer.write(b'\xff\xfe ok\n')"]
        )
        assert any("ok" in line for line in output)


class TestCancellation:
    async def test_sigterm_lets_the_utility_exit_cleanly(self):
        """A well-behaved tool traps SIGTERM, rolls back, and exits."""
        script = (
            "import signal, sys, time\n"
            "def bye(*_):\n"
            "    print('rolling back'); sys.stdout.flush(); sys.exit(3)\n"
            "signal.signal(signal.SIGTERM, bye)\n"
            "print('working'); sys.stdout.flush()\n"
            "time.sleep(60)\n"
        )
        code, output = await run([sys.executable, "-c", script], cancel_after=0.5)

        assert "rolling back" in output, "the utility was not given a chance to clean up"
        assert any("SIGTERM" in line for line in output)
        assert code == 3

    async def test_a_process_ignoring_sigterm_is_eventually_killed(self):
        """Grace is a grace period, not an indefinite wait."""
        script = (
            "import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "print('stubborn'); sys.stdout.flush()\n"
            "time.sleep(60)\n"
        )
        code, output = await run([sys.executable, "-c", script], grace=1.0, cancel_after=0.3)

        assert any("SIGKILL" in line for line in output)
        # The operator is warned that state may be inconsistent.
        assert any("incomplete transaction" in line for line in output)
        assert code != 0

    async def test_cancelling_an_already_finished_process_is_harmless(self):
        code, _ = await run([sys.executable, "-c", "pass"], cancel_after=0.4)
        assert code == 0

    async def test_child_processes_are_signalled_too(self):
        """
        Utilities spawn children — psql, an ssh tunnel. Cancellation has to
        reach the whole process group, not just the parent.
        """
        script = (
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "print(f'child {child.pid}'); sys.stdout.flush()\n"
            "time.sleep(60)\n"
        )
        _, output = await run([sys.executable, "-c", script], grace=1.0, cancel_after=0.5)

        child_pid = int(next(line for line in output if line.startswith("child ")).split()[1])

        # `os.kill(pid, 0)` is the wrong probe here: it succeeds for a zombie,
        # because the PID entry survives until the process is reaped. What
        # matters is that the child is no longer *running*, so read its state.
        assert not _is_running(child_pid), "child survived cancellation of the group"


def _is_running(pid: int) -> bool:
    """True only if the process exists and is not a zombie awaiting reaping."""
    for _ in range(30):
        try:
            with open(f"/proc/{pid}/stat") as handle:
                state = handle.read().rsplit(")", 1)[1].split()[0]
        except FileNotFoundError:
            return False
        if state == "Z":
            return False
        time.sleep(0.1)
    return True
