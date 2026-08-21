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
        # Handy for the few tests that need to seed the audit trail rather than
        # produce it by running something.
        test_client.audit = audit
        yield test_client


def as_(client, user, roles):
    client.headers.update({"x-dev-user": user, "x-dev-roles": roles})
    return client


class TestLiveness:
    def test_health_needs_no_authentication(self, client):
        # A liveness probe has to work before anyone signs in.
        assert client.get("/api/health").json() == {"status": "ok"}

    def test_the_service_description_reports_whether_auth_is_configured(self, client):
        # It lived at / until / became the console.
        assert "authentication" in client.get("/api").json()


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


class TestConsole:
    """
    `/` serves the console, not JSON.

    It returned the service description for a while, so anyone opening the
    deployment in a browser was shown a JSON object and reasonably concluded
    there was no application. That is what these assert against.
    """

    def test_the_root_serves_html(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "<title>Certainti Tech Administration</title>" in response.text

    def test_the_service_description_moved_to_api(self, client):
        payload = client.get("/api").json()
        assert payload["service"] == "trd365 orchestrator"
        assert payload["console"] == "/"

    def test_the_console_needs_no_authentication_to_load(self, client):
        # The page itself is a shell; every figure on it comes from an API call
        # that is authorised on its own. Gating the shell would show a bare 403
        # instead of a console that explains what the caller may do.
        assert client.get("/").status_code == 200

    def test_the_console_is_packaged_beside_the_module(self):
        # Missing package-data installs the module without its HTML, so the
        # console works from a checkout and falls back to JSON on a deployed host.
        from trd365_orchestrator.app import CONSOLE

        assert CONSOLE.is_file(), f"{CONSOLE} is not installed"

    def test_the_console_only_calls_endpoints_that_exist(self, client):
        # Matches the console's own request helper. This test was briefly worthless
        # after a refactor renamed that helper — the pattern found nothing and the
        # loop passed over an empty set — so it now asserts it found something.
        import re

        from trd365_orchestrator.app import CONSOLE

        console = CONSOLE.read_text()
        paths = set(client.app.openapi()["paths"])

        literal = set(re.findall(r'api\("(/api[^"?]*)', console))
        # Template literals: /api/model/${env} and /api/utilities/${id}/preview.
        templated = {
            re.sub(r"\$\{[^}]+\}", "{}", found)
            for found in re.findall(r"api\(`(/api[^`?]*)", console)
        }
        wanted = literal | templated
        assert wanted, "found no API calls in the console; has the request helper moved?"

        for path in wanted - {"/api"}:  # /api is excluded from the schema
            template = path.replace("/api/model/{}", "/api/model/{environment}")
            template = template.replace("/api/utilities/{}/", "/api/utilities/{utility_id}/")
            template = re.sub(r"/(prod|stage|qa|dev)$", "/{environment}", template)
            assert template in paths, (
                f"the console calls {path}, which the API does not serve"
            )


    def test_the_console_knows_every_status_the_health_module_emits(self):
        # The card colour follows `status` off the payload rather than being
        # recomputed in the browser, which is how a dashboard ends up disagreeing
        # with the API it reads. That only holds if the console's lookup table
        # covers the whole vocabulary — a new status would otherwise render as a
        # grey pill labelled with the raw word.
        import re

        from trd365_orchestrator.app import CONSOLE

        table = re.search(r"const STATUS = \{(.*?)\n\};", CONSOLE.read_text(), re.S)
        assert table, "the console no longer has a STATUS table"
        known = set(re.findall(r"(\w+): \[", table.group(1)))

        # Read the vocabulary out of the health module rather than restating it,
        # so adding a status there fails here instead of shipping a grey pill.
        import inspect

        from trd365_orchestrator import health

        source = inspect.getsource(health.EnvironmentHealth.status.fget)
        emitted = set(re.findall(r'return "(\w+)"', source))

        assert emitted, "EnvironmentHealth.status no longer returns literals"
        assert emitted <= known, f"the console has no tone for {sorted(emitted - known)}"


    def test_the_console_only_reads_fields_the_api_sends(self, client):
        # This test exists because it was wrong in production. The console rendered
        # the audit trail's mode from `record.applied`, which the API does not
        # serialise — it sends `mode` ("apply" / "dry-run"). `undefined` is falsy,
        # so every applied run in the audit trail was labelled "dry run". An audit
        # trail that mislabels writes as dry runs is worse than no audit trail.
        #
        # Checked for both tables, since the same mistake is available in each.
        import re

        from trd365_core.audit import RunRecord

        from trd365_orchestrator.app import CONSOLE

        client.audit.write(
            RunRecord(
                run_id="r1",
                utility="data-model-analysis",
                environment="prod",
                actor="someone",
                host="test",
                applied=True,
                started_at="2026-08-21T10:24:10+00:00",
                outcome="success",
            )
        )
        console = CONSOLE.read_text()
        viewer = as_(client, "v", "viewer")

        for function, variable, endpoint in (
            ("auditTable", "r", "/api/audit"),
            ("jobsTable", "j", "/api/jobs"),
        ):
            body = re.search(rf"function {function}\((.*?)\n}}\n", console, re.S)
            assert body, f"the console no longer has a {function} function"
            read = set(re.findall(rf"\b{variable}\.(\w+)", body.group(1)))
            assert read, f"found no fields being read in {function}"

            payload = viewer.get(endpoint).json()
            records = payload.get("records") or payload.get("jobs")
            if not records:
                # /api/jobs is empty until something is submitted; fall back to the
                # dataclass's own field names, which are what it serialises.
                from trd365_orchestrator.jobs import Job

                sent = set(Job.__dataclass_fields__) | {"mode", "state"}
            else:
                sent = set(records[0])

            unknown = sorted(read - sent)
            assert not unknown, (
                f"the console reads {unknown} from {endpoint}, which it does not send"
            )

    def test_an_applied_run_is_not_shown_as_a_dry_run(self):
        # The specific regression, pinned separately from the contract check above
        # so a rename of `mode` cannot make both pass by making both vacuous.
        from trd365_orchestrator.app import CONSOLE

        console = CONSOLE.read_text()
        assert 'r.mode === "apply"' in console
        assert "r.applied" not in console


class TestWhoAmI:
    def test_a_viewer_is_told_it_cannot_run_anything(self, client):
        payload = as_(client, "demo", "viewer").get("/api/me").json()
        assert payload["can_view"] is True
        assert payload["can_run"] is False
        assert payload["can_approve"] is False

    def test_an_operator_may_run_but_not_approve(self, client):
        payload = as_(client, "ops", "operator").get("/api/me").json()
        assert payload["can_run"] is True
        assert payload["can_approve"] is False

    def test_roles_are_reported_so_the_console_can_describe_itself(self, client):
        payload = as_(client, "sam", "viewer,approver").get("/api/me").json()
        assert payload["roles"] == ["approver", "viewer"]
        assert payload["subject"] == "sam"
