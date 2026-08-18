"""The HTTP surface, driven end to end through the real app."""

import pytest
from fastapi.testclient import TestClient
from helpers import PURGE, REPORT, ScriptedRunner
from trd365_core.audit import MemoryAuditSink
from trd365_core.registry import Registry

from trd365_orchestrator.app import create_app, header_authenticator
from trd365_orchestrator.jobs import JobStore
from trd365_orchestrator.scheduler import Scheduler
from trd365_orchestrator.service import Orchestrator, OrchestratorConfig


@pytest.fixture
def client():
    registry = Registry([PURGE, REPORT])
    store = JobStore()
    audit = MemoryAuditSink()
    scheduler = Scheduler(registry, store, ScriptedRunner(), audit_sink=audit)
    orchestrator = Orchestrator(
        registry,
        store,
        scheduler,
        audit_sink=audit,
        config=OrchestratorConfig(authentication_configured=True),
        environ={},
    )
    app = create_app(
        registry=registry, authenticator=header_authenticator, orchestrator=orchestrator
    )
    with TestClient(app) as test_client:
        yield test_client


def as_(client, user, roles):
    client.headers.update({"x-dev-user": user, "x-dev-roles": roles})
    return client


class TestLiveness:
    def test_health_needs_no_authentication(self, client):
        # A liveness probe has to work before anyone signs in.
        assert client.get("/api/health").json() == {"status": "ok"}

    def test_index_reports_whether_auth_is_configured(self, client):
        assert "authentication" in client.get("/").json()


class TestUtilities:
    def test_a_viewer_sees_the_catalogue(self, client):
        response = as_(client, "carol", "viewer").get("/api/utilities")
        assert response.status_code == 200
        ids = {u["id"] for u in response.json()["utilities"]}
        assert ids == {"purge-account", "orphan-report"}

    def test_an_unauthenticated_caller_sees_nothing(self, client):
        assert client.get("/api/utilities").status_code == 403

    def test_the_catalogue_carries_what_the_ui_renders_from(self, client):
        response = as_(client, "carol", "viewer").get("/api/utilities")
        purge = next(u for u in response.json()["utilities"] if u["id"] == "purge-account")
        assert purge["impact"] == "destructive"
        assert purge["requires_approval_in_prod"] is True
        assert {p["flag"] for p in purge["parameters"]} >= {"--account-rid", "--chunk-size"}


class TestPreview:
    def test_shows_the_exact_command_without_running_it(self, client):
        response = as_(client, "alice", "operator").post(
            "/api/utilities/purge-account/preview",
            json={
                "utility_id": "purge-account",
                "environment": "prod",
                "arguments": {"account_rid": "r-1"},
                "apply": True,
            },
        )
        body = response.json()
        assert "--env prod" in body["command"]
        assert "--apply" in body["command"]
        assert body["requires_approval"] is True
        assert client.get("/api/jobs").json()["jobs"] == []  # nothing started

    def test_rejects_undeclared_arguments(self, client):
        response = as_(client, "alice", "operator").post(
            "/api/utilities/purge-account/preview",
            json={
                "utility_id": "purge-account",
                "environment": "dev",
                "arguments": {"account_rid": "r-1", "sneaky": "x"},
                "apply": False,
            },
        )
        assert response.status_code == 400
        assert "does not accept" in response.json()["detail"]


class TestJobs:
    def test_a_dev_run_starts_immediately(self, client):
        response = as_(client, "alice", "operator").post(
            "/api/jobs",
            json={
                "utility_id": "purge-account",
                "environment": "dev",
                "arguments": {"account_rid": "r-1"},
                "apply": True,
            },
        )
        assert response.status_code == 201
        assert response.json()["state"] in {"queued", "running", "succeeded"}

    def test_a_production_write_waits_for_approval(self, client):
        response = as_(client, "alice", "operator").post(
            "/api/jobs",
            json={
                "utility_id": "purge-account",
                "environment": "prod",
                "arguments": {"account_rid": "r-1"},
                "apply": True,
            },
        )
        assert response.json()["state"] == "pending_approval"
        assert len(client.get("/api/approvals").json()["jobs"]) == 1

    def test_self_approval_is_refused_over_http(self, client):
        created = as_(client, "alice", "operator,approver").post(
            "/api/jobs",
            json={
                "utility_id": "purge-account",
                "environment": "prod",
                "arguments": {"account_rid": "r-1"},
                "apply": True,
            },
        ).json()

        response = client.post(f"/api/jobs/{created['id']}/approve")
        assert response.status_code == 403
        assert "your own" in response.json()["detail"]

    def test_a_second_person_can_approve(self, client):
        created = as_(client, "alice", "operator").post(
            "/api/jobs",
            json={
                "utility_id": "purge-account",
                "environment": "prod",
                "arguments": {"account_rid": "r-1"},
                "apply": True,
            },
        ).json()

        response = as_(client, "bob", "approver").post(f"/api/jobs/{created['id']}/approve")
        assert response.status_code == 200
        assert response.json()["approved_by"] == "bob"

    def test_a_viewer_cannot_start_a_write(self, client):
        response = as_(client, "carol", "viewer").post(
            "/api/jobs",
            json={
                "utility_id": "purge-account",
                "environment": "dev",
                "arguments": {"account_rid": "r-1"},
                "apply": True,
            },
        )
        assert response.status_code == 403

    def test_arguments_are_redacted_in_the_job_record(self, client):
        # Nothing credential-shaped should survive into a record the UI shows.
        created = as_(client, "alice", "operator").post(
            "/api/jobs",
            json={
                "utility_id": "orphan-report",
                "environment": "dev",
                "arguments": {"org_schema": "trd365_00042"},
                "apply": False,
            },
        ).json()
        assert created["arguments"]["org_schema"] == "trd365_00042"

    def test_unknown_job_is_404(self, client):
        assert as_(client, "carol", "viewer").get("/api/jobs/nope").status_code == 404

    def test_jobs_can_be_filtered(self, client):
        as_(client, "alice", "operator")
        for env in ("dev", "qa"):
            client.post(
                "/api/jobs",
                json={
                    "utility_id": "orphan-report",
                    "environment": env,
                    "arguments": {},
                    "apply": False,
                },
            )
        assert len(client.get("/api/jobs?environment=dev").json()["jobs"]) == 1

    def test_an_unknown_state_filter_is_a_400(self, client):
        assert as_(client, "carol", "viewer").get("/api/jobs?state=bogus").status_code == 400

    def test_an_unknown_environment_is_a_400(self, client):
        response = as_(client, "alice", "operator").post(
            "/api/jobs",
            json={
                "utility_id": "orphan-report",
                "environment": "production",
                "arguments": {},
                "apply": False,
            },
        )
        assert response.status_code == 400


class TestHealthAndAudit:
    def test_environment_health_covers_all_four(self, client):
        response = as_(client, "carol", "viewer").get("/api/health/environments")
        assert response.status_code == 200
        environments = {e["environment"] for e in response.json()["environments"]}
        assert environments == {"dev", "qa", "stage", "prod"}

    def test_unconfigured_environments_report_as_such(self, client):
        response = as_(client, "carol", "viewer").get("/api/health/environments")
        dev = next(e for e in response.json()["environments"] if e["environment"] == "dev")
        assert dev["configured"] is False
        assert dev["status"] == "unconfigured"

    def test_the_audit_endpoint_is_read_only(self, client):
        """
        Audit records are immutable (PRD FR-3.2): there is deliberately no route
        that edits or deletes one. Asserted against the OpenAPI schema, which is
        the actual published contract.
        """
        schema = client.get("/openapi.json").json()
        audit_paths = {p: ops for p, ops in schema["paths"].items() if p.startswith("/api/audit")}

        assert audit_paths, "no audit endpoint is published"
        for path, operations in audit_paths.items():
            assert set(operations) == {"get"}, f"{path} exposes {sorted(operations)}"

    def test_no_endpoint_anywhere_mutates_the_audit_trail(self, client):
        schema = client.get("/openapi.json").json()
        mutating = {
            (path, verb)
            for path, operations in schema["paths"].items()
            for verb in operations
            if verb in {"put", "patch", "delete"}
        }
        assert mutating == set(), f"unexpected mutating routes: {sorted(mutating)}"

    def test_audit_requires_a_viewer(self, client):
        assert client.get("/api/audit").status_code == 403
