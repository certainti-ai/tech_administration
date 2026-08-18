"""Production writes need a second person. This is the rule that matters most."""

import pytest
from helpers import principal
from trd365_core.environments import Environment

from trd365_orchestrator.jobs import JobState
from trd365_orchestrator.security import AuthorizationError, Role


def request(orchestrator, actor, env=Environment.PROD, apply=True, utility="purge-account"):
    return orchestrator.request_run(
        actor,
        utility_id=utility,
        environment=env,
        arguments={"account_rid": "r-1"} if utility == "purge-account" else {},
        apply=apply,
    )


class TestWhenApprovalIsRequired:
    async def test_production_writes_wait_for_approval(self, make_orchestrator, operator):
        orchestrator = make_orchestrator()
        job = request(orchestrator, operator)
        assert job.state is JobState.PENDING_APPROVAL

    async def test_production_dry_runs_do_not(self, make_orchestrator, operator):
        # The point of a preview is that it is safe to take without ceremony.
        orchestrator = make_orchestrator()
        job = request(orchestrator, operator, apply=False)
        assert job.state is not JobState.PENDING_APPROVAL

    async def test_lower_environments_do_not(self, make_orchestrator, operator):
        orchestrator = make_orchestrator()
        for env in (Environment.DEV, Environment.QA, Environment.STAGE):
            job = request(orchestrator, operator, env=env)
            assert job.state is not JobState.PENDING_APPROVAL

    async def test_read_only_utilities_never_do(self, make_orchestrator, operator):
        orchestrator = make_orchestrator()
        job = request(orchestrator, operator, utility="orphan-report", apply=False)
        assert job.state is not JobState.PENDING_APPROVAL


class TestApproval:
    async def test_a_different_approver_releases_the_job(
        self, make_orchestrator, operator, approver
    ):
        orchestrator = make_orchestrator()
        job = request(orchestrator, operator)

        approved = orchestrator.approve(approver, job.id)
        assert approved.approved_by == "bob"
        assert approved.state in {JobState.QUEUED, JobState.RUNNING, JobState.SUCCEEDED}
        await orchestrator.scheduler.wait(job.id)

    async def test_self_approval_is_refused(self, make_orchestrator):
        """A second approver who can be the same person is not a second approver."""
        orchestrator = make_orchestrator()
        alice = principal("alice", Role.OPERATOR, Role.APPROVER)
        job = request(orchestrator, alice)

        with pytest.raises(AuthorizationError, match="cannot approve your own"):
            orchestrator.approve(alice, job.id)
        assert orchestrator.store.get(job.id).state is JobState.PENDING_APPROVAL

    async def test_an_operator_without_approver_cannot_approve(self, make_orchestrator, operator):
        orchestrator = make_orchestrator()
        job = request(orchestrator, operator)
        other_operator = principal("dave", Role.OPERATOR)

        with pytest.raises(AuthorizationError, match="Approver role"):
            orchestrator.approve(other_operator, job.id)

    async def test_an_admin_may_approve(self, make_orchestrator, operator):
        orchestrator = make_orchestrator()
        job = request(orchestrator, operator)
        orchestrator.approve(principal("root", Role.ADMIN), job.id)
        await orchestrator.scheduler.wait(job.id)
        assert orchestrator.store.get(job.id).state is JobState.SUCCEEDED

    async def test_rejection_is_terminal(self, make_orchestrator, operator, approver):
        orchestrator = make_orchestrator()
        job = request(orchestrator, operator)

        rejected = orchestrator.reject(approver, job.id, "not this quarter")
        assert rejected.state is JobState.REJECTED
        assert rejected.error == "not this quarter"

        from trd365_core.errors import Trd365Error

        with pytest.raises(Trd365Error, match="not awaiting approval"):
            orchestrator.approve(approver, job.id)

    async def test_an_approved_job_records_its_approver_in_the_audit_trail(
        self, make_orchestrator, operator, approver, audit
    ):
        orchestrator = make_orchestrator()
        job = request(orchestrator, operator)
        orchestrator.approve(approver, job.id)
        await orchestrator.scheduler.wait(job.id)

        record = audit.records[0]
        assert any("approved by bob" in note for note in record.notes)


class TestAuthorisation:
    async def test_a_viewer_cannot_start_a_write(self, make_orchestrator, viewer):
        orchestrator = make_orchestrator()
        with pytest.raises(AuthorizationError, match="operator role"):
            request(orchestrator, viewer, env=Environment.DEV)

    async def test_a_viewer_may_run_a_read_only_utility(self, make_orchestrator, viewer):
        orchestrator = make_orchestrator()
        job = request(orchestrator, viewer, utility="orphan-report", apply=False)
        await orchestrator.scheduler.wait(job.id)
        assert orchestrator.store.get(job.id).state is JobState.SUCCEEDED

    async def test_unconfigured_authentication_refuses_every_write(
        self, make_orchestrator, operator
    ):
        """
        A deployment that forgot to configure auth must not be able to write.
        Refusing is better than allowing an unauthenticated production purge.
        """
        orchestrator = make_orchestrator(authenticated=False)
        with pytest.raises(AuthorizationError, match="Authentication is not configured"):
            request(orchestrator, operator, env=Environment.DEV)

    async def test_unconfigured_authentication_still_allows_read_only(
        self, make_orchestrator, viewer
    ):
        orchestrator = make_orchestrator(authenticated=False)
        job = request(orchestrator, viewer, utility="orphan-report", apply=False)
        await orchestrator.scheduler.wait(job.id)
        assert orchestrator.store.get(job.id).state is JobState.SUCCEEDED
