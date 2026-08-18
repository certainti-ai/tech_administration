"""Execution: serialisation per environment, cancellation, and the audit record."""

import asyncio

import pytest
from helpers import ScriptedRunner
from trd365_core.environments import Environment

from trd365_orchestrator.jobs import JobState


def request(orchestrator, actor, env=Environment.DEV, apply=True, utility="purge-account"):
    return orchestrator.request_run(
        actor,
        utility_id=utility,
        environment=env,
        arguments={"account_rid": "r-1"} if utility == "purge-account" else {},
        apply=apply,
    )


class TestOutcomes:
    async def test_a_successful_run_is_recorded(self, make_orchestrator, operator, audit):
        orchestrator = make_orchestrator(ScriptedRunner(exit_code=0, output=["done"]))
        job = request(orchestrator, operator)
        await orchestrator.scheduler.wait(job.id)

        finished = orchestrator.store.get(job.id)
        assert finished.state is JobState.SUCCEEDED
        assert finished.exit_code == 0
        assert "done" in finished.output
        assert audit.records[0].outcome == "success"

    async def test_a_nonzero_exit_fails_the_job(self, make_orchestrator, operator, audit):
        orchestrator = make_orchestrator(ScriptedRunner(exit_code=3))
        job = request(orchestrator, operator)
        await orchestrator.scheduler.wait(job.id)

        finished = orchestrator.store.get(job.id)
        assert finished.state is JobState.FAILED
        assert "exited with code 3" in finished.error
        assert audit.records[0].outcome == "failed"

    async def test_the_command_is_the_first_line_of_output(self, make_orchestrator, operator):
        orchestrator = make_orchestrator()
        job = request(orchestrator, operator)
        await orchestrator.scheduler.wait(job.id)
        assert orchestrator.store.get(job.id).output[0].startswith("[orchestrator] ")

    async def test_dry_runs_are_audited_too(self, make_orchestrator, operator, audit):
        orchestrator = make_orchestrator()
        job = request(orchestrator, operator, apply=False)
        await orchestrator.scheduler.wait(job.id)
        assert audit.records[0].mode == "dry-run"


class TestCancellation:
    async def test_a_running_job_can_be_cancelled(self, make_orchestrator, operator, audit):
        gate = asyncio.Event()
        runner = ScriptedRunner(block=gate)
        orchestrator = make_orchestrator(runner)

        job = request(orchestrator, operator)
        await asyncio.wait_for(runner.started.wait(), timeout=2)

        orchestrator.cancel(operator, job.id)
        await orchestrator.scheduler.wait(job.id)

        finished = orchestrator.store.get(job.id)
        assert finished.state is JobState.CANCELLED
        # Cancellation is not failure: the distinction matters when reading back
        # what happened to a purge that was stopped deliberately.
        assert audit.records[0].outcome == "cancelled"
        assert audit.records[0].error is None

    async def test_a_queued_job_can_be_cancelled_before_it_starts(
        self, make_orchestrator, operator
    ):
        gate = asyncio.Event()
        orchestrator = make_orchestrator(ScriptedRunner(block=gate))

        first = request(orchestrator, operator)
        await asyncio.sleep(0)
        second = request(orchestrator, operator)

        orchestrator.cancel(operator, second.id)
        assert orchestrator.store.get(second.id).state is JobState.CANCELLED

        gate.set()
        await orchestrator.scheduler.wait(first.id)

    async def test_a_finished_job_cannot_be_cancelled(self, make_orchestrator, operator):
        orchestrator = make_orchestrator()
        job = request(orchestrator, operator)
        await orchestrator.scheduler.wait(job.id)

        with pytest.raises(Exception, match="already finished"):
            orchestrator.cancel(operator, job.id)

    async def test_the_requester_may_cancel_their_own_job(self, make_orchestrator):
        from trd365_orchestrator.security import Principal, Role

        gate = asyncio.Event()
        runner = ScriptedRunner(block=gate)
        orchestrator = make_orchestrator(runner)
        alice = Principal("alice", "alice", frozenset({Role.OPERATOR}))

        job = request(orchestrator, alice)
        await asyncio.wait_for(runner.started.wait(), timeout=2)
        orchestrator.cancel(alice, job.id)
        await orchestrator.scheduler.wait(job.id)
        assert orchestrator.store.get(job.id).state is JobState.CANCELLED


class TestEnvironmentSerialisation:
    async def test_two_writers_in_one_environment_do_not_overlap(
        self, make_orchestrator, operator
    ):
        """
        Two purges against the same database at once is how one deadlocks
        against the other, or half-deletes a tree the other is walking.
        """
        gate = asyncio.Event()
        runner = ScriptedRunner(block=gate)
        orchestrator = make_orchestrator(runner)

        first = request(orchestrator, operator)
        await asyncio.wait_for(runner.started.wait(), timeout=2)
        second = request(orchestrator, operator)
        await asyncio.sleep(0.05)

        assert orchestrator.store.get(first.id).state is JobState.RUNNING
        assert orchestrator.store.get(second.id).state is JobState.QUEUED
        assert orchestrator.scheduler.is_busy(Environment.DEV)

        gate.set()
        await orchestrator.scheduler.wait(first.id)
        await orchestrator.scheduler.wait(second.id)
        assert orchestrator.store.get(second.id).state is JobState.SUCCEEDED

    async def test_writers_in_different_environments_run_concurrently(
        self, make_orchestrator, operator
    ):
        gate = asyncio.Event()
        runner = ScriptedRunner(block=gate)
        orchestrator = make_orchestrator(runner)

        dev = request(orchestrator, operator, env=Environment.DEV)
        qa = request(orchestrator, operator, env=Environment.QA)
        await asyncio.sleep(0.05)

        assert orchestrator.store.get(dev.id).state is JobState.RUNNING
        assert orchestrator.store.get(qa.id).state is JobState.RUNNING

        gate.set()
        await orchestrator.scheduler.wait(dev.id)
        await orchestrator.scheduler.wait(qa.id)

    async def test_read_only_jobs_are_not_blocked_by_a_writer(self, make_orchestrator, operator):
        """Blocking a report behind a four-hour purge pushes people back to the CLI."""
        gate = asyncio.Event()
        runner = ScriptedRunner(block=gate)
        orchestrator = make_orchestrator(runner)

        purge = request(orchestrator, operator)
        await asyncio.wait_for(runner.started.wait(), timeout=2)

        report = request(orchestrator, operator, utility="orphan-report", apply=False)
        await asyncio.sleep(0.05)
        assert orchestrator.store.get(report.id).state is JobState.RUNNING

        gate.set()
        await orchestrator.scheduler.wait(purge.id)
        await orchestrator.scheduler.wait(report.id)


class TestOutputRetention:
    async def test_long_output_keeps_the_tail_and_says_what_it_dropped(self, store):
        from trd365_orchestrator.jobs import JobStore, new_job

        small = JobStore(max_output_lines=10)
        job = new_job(
            utility_id="purge-account",
            environment=Environment.DEV,
            apply=False,
            arguments={},
            requested_by="alice",
            needs_approval=False,
        )
        for i in range(50):
            small.append_output(job, f"line {i}")

        assert len(job.output) == 10
        assert "dropped" in job.output[0]
        assert job.output[-1] == "line 49"
