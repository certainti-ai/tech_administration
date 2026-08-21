"""
The ASGI application. This is what the systemd unit runs:

    uvicorn trd365_orchestrator.app:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from trd365_core.audit import JsonlAuditSink, default_audit_path
from trd365_core.db import ConnectionPool
from trd365_core.environments import Environment
from trd365_core.model_snapshot import FileModelStore
from trd365_core.registry import load_installed_utilities
from trd365_core.registry import registry as default_registry

from .api import router
from .jobs import JobStore
from .runner import SubprocessRunner
from .scheduler import Scheduler
from .security import ANONYMOUS, Principal, Role
from .service import Orchestrator, OrchestratorConfig

Authenticator = Callable[[Request], Principal]

#: The console, shipped as package data beside this module.
CONSOLE = Path(__file__).parent / "web" / "index.html"


def header_authenticator(request: Request) -> Principal:
    """
    Development authenticator: trusts request headers.

    Enabled only when ``TRD365_DEV_AUTH=1``. It exists so the API can be driven
    locally before Entra ID is wired in (Phase 3), and it is never the default —
    a deployment that forgot to configure auth gets :data:`ANONYMOUS`, which can
    do nothing, rather than a caller who can name their own roles.
    """
    subject = request.headers.get("x-dev-user", "dev")
    raw_roles = request.headers.get("x-dev-roles", "")
    roles = frozenset(
        Role(value.strip()) for value in raw_roles.split(",") if value.strip() in set(Role)
    )
    return Principal(subject=subject, display_name=subject, roles=roles)


def anonymous_authenticator(_request: Request) -> Principal:
    return ANONYMOUS


def create_app(
    *,
    registry=None,
    authenticator: Authenticator | None = None,
    orchestrator: Orchestrator | None = None,
) -> FastAPI:
    dev_auth = os.environ.get("TRD365_DEV_AUTH") == "1"

    # Whatever utility packages are installed alongside the service, not a list
    # this file has to keep up to date. A caller that supplies its own registry
    # has already decided what is in it.
    discovered = load_installed_utilities() if registry is None else []

    if orchestrator is None:
        store = JobStore()
        audit_sink = JsonlAuditSink(default_audit_path())
        scheduler = Scheduler(
            registry or default_registry,
            store,
            SubprocessRunner(env=dict(os.environ)),
            audit_sink=audit_sink,
        )
        orchestrator = Orchestrator(
            registry or default_registry,
            store,
            scheduler,
            model_store=FileModelStore(),
            pool_factory=lambda env: ConnectionPool(env),
            audit_sink=audit_sink,
            config=OrchestratorConfig(
                authentication_configured=dev_auth,
                probe_databases=os.environ.get("TRD365_PROBE_DATABASES") == "1",
            ),
        )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        yield
        # Let in-flight jobs finish rather than dropping a purge mid-transaction.
        await application.state.orchestrator.scheduler.drain()

    app = FastAPI(
        title="Certainti Tech Administration",
        description=(
            "Job execution, approvals, audit and health for the trd365 "
            "maintenance utilities."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.orchestrator = orchestrator
    app.state.authenticator = authenticator or (
        header_authenticator if dev_auth else anonymous_authenticator
    )
    app.include_router(router, prefix="/api")

    def service_info() -> dict:
        return {
            "service": "trd365 orchestrator",
            "environments": [e.value for e in Environment],
            "docs": "/docs",
            "console": "/",
            "authentication": "development headers" if dev_auth else "not configured",
            "utilities": len(app.state.orchestrator.registry),
            "discovered": discovered,
        }

    @app.get("/api", include_in_schema=False)
    def info() -> dict:
        """Service description. This used to live at `/` — see `index` below."""
        return service_info()

    @app.get("/", include_in_schema=False)
    def index():
        """
        The operator console.

        `/` used to return the service description as JSON, which meant anyone
        opening the deployment in a browser was shown a JSON object and
        reasonably concluded there was no application. The description moved to
        `/api`; this serves the console.

        The page is one self-contained file with no build step, deliberately.
        The VM has no Node runtime, so a bundled front end would mean either
        installing a toolchain on a host that can purge production or committing
        build output. Neither is worth it for a console that reads six endpoints.
        A richer front end (PRD FR-4.x) can replace this without the API moving.
        """
        if not CONSOLE.exists():  # pragma: no cover - packaging failure
            return JSONResponse(service_info())
        return FileResponse(CONSOLE, media_type="text/html")

    return app


app = create_app()
