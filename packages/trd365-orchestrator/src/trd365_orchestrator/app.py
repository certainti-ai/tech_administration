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
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
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


def _secret_source():
    """
    The vault, if this host can reach one. Never fatal.

    A missing vault must not stop the service starting: the secrets may be in the
    environment instead, and if they are in neither, the Entra configuration says
    so with a message about what is missing.
    """
    try:
        from trd365_core.vault import default_secret_source

        return default_secret_source()
    except Exception:  # noqa: BLE001 — absence of a vault is not an error here
        return None


def _add_sign_in_routes(app: FastAPI, config) -> None:
    """``/auth/login``, ``/auth/callback``, ``/auth/logout``."""
    from . import entra

    @app.get("/auth/login", include_in_schema=False)
    def login(request: Request):
        started = entra.start(config, return_to=request.query_params.get("next", "/"))
        response = RedirectResponse(started.url, status_code=307)
        response.set_cookie(
            entra.FLOW_COOKIE,
            started.flow_cookie,
            max_age=entra.FLOW_SECONDS,
            httponly=True,
            secure=True,
            # Lax, not Strict: the browser arrives here from Entra's domain, and
            # Strict would withhold the cookie on exactly that navigation.
            samesite="lax",
            path="/auth",
        )
        return response

    @app.get("/auth/callback", include_in_schema=False)
    def callback(request: Request):
        flow = entra.unsign(request.cookies.get(entra.FLOW_COOKIE, ""), config.session_secret)
        if flow is None:
            return _sign_in_error(
                "This sign-in has expired or did not start here. Try again from the start."
            )

        if request.query_params.get("error"):
            return _sign_in_error(
                request.query_params.get("error_description")
                or request.query_params["error"]
            )

        # Compared before anything else is done with the reply.
        if not secrets_compare(request.query_params.get("state", ""), flow["state"]):
            return _sign_in_error("The sign-in reply did not match the request that started it.")

        code = request.query_params.get("code")
        if not code:
            return _sign_in_error("The sign-in reply carried no authorization code.")

        try:
            id_token = entra.exchange(config, code, flow["verifier"])
            claims = entra.verify(config, id_token, flow["nonce"])
        except entra.SignInFailed as exc:
            return _sign_in_error(str(exc))

        principal = entra.principal_from(claims, config.group_roles)
        try:
            entra.entitled(principal, config)
        except entra.NotEntitled as exc:
            # Verified, and not permitted. No session cookie is issued: there is
            # nothing for it to carry.
            return JSONResponse(
                {"error": "no access", "detail": str(exc)}, status_code=403
            )
        response = RedirectResponse(entra.safe_return_to(flow.get("return_to")), status_code=303)
        response.set_cookie(
            entra.SESSION_COOKIE,
            entra.session_for(principal, config),
            max_age=entra.SESSION_SECONDS,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
        response.delete_cookie(entra.FLOW_COOKIE, path="/auth")
        return response

    @app.get("/auth/logout", include_in_schema=False)
    def logout(request: Request):
        # Sign out of Entra too, not just here — leaving the Entra session live
        # means the next click signs straight back in and looks like nothing
        # happened.
        base = str(request.base_url).rstrip("/")
        response = RedirectResponse(
            entra.logout_url(config, return_to=f"{base}/"), status_code=303
        )
        response.delete_cookie(entra.SESSION_COOKIE, path="/")
        return response


def secrets_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode(), right.encode())


def _sign_in_error(detail: str) -> JSONResponse:
    """
    Say what went wrong without saying anything a caller could use.

    The detail here comes from our own checks or from Entra's own error
    description, never from a token or a claim.
    """
    return JSONResponse(
        {"error": "sign-in failed", "detail": detail, "retry": "/auth/login"},
        status_code=401,
    )


def entra_authenticator(config) -> Authenticator:
    """
    Read the caller from a signed session cookie set by the Entra sign-in.

    Nothing is trusted from a header. An unsigned, tampered or expired cookie is
    the same as no cookie: :data:`~trd365_orchestrator.security.ANONYMOUS`, which
    can read nothing privileged and run nothing.
    """

    def authenticate(request: Request) -> Principal:
        from . import entra

        found = entra.principal_from_session(
            request.cookies.get(entra.SESSION_COOKIE), config
        )
        return found or ANONYMOUS

    return authenticate


def create_app(
    *,
    registry=None,
    authenticator: Authenticator | None = None,
    orchestrator: Orchestrator | None = None,
) -> FastAPI:
    from . import entra

    dev_auth = os.environ.get("TRD365_DEV_AUTH") == "1"

    # Entra takes precedence over the development header authenticator whenever it
    # is configured, so a host that has both set cannot be signed into by naming
    # your own roles in a header.
    entra_config = entra.config_from_environment(secrets_source=_secret_source())
    if entra_config is not None:
        dev_auth = False

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
                authentication_configured=dev_auth or entra_config is not None,
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
    app.state.entra = entra_config
    app.state.authenticator = authenticator or (
        entra_authenticator(entra_config)
        if entra_config is not None
        else (header_authenticator if dev_auth else anonymous_authenticator)
    )
    app.include_router(router, prefix="/api")
    if entra_config is not None:
        _add_sign_in_routes(app, entra_config)

    def service_info() -> dict:
        return {
            "service": "trd365 orchestrator",
            "environments": [e.value for e in Environment],
            "docs": "/docs",
            "console": "/",
            "authentication": (
                "entra id"
                if entra_config is not None
                else ("development headers" if dev_auth else "not configured")
            ),
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
