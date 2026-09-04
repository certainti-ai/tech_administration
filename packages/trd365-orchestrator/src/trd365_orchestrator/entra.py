"""
Entra ID sign-in (PRD FR-4.1: "Entra ID SSO. No local accounts.").

This replaces two things that were only ever meant to be temporary: the shared
Caddy password, and :func:`~trd365_orchestrator.app.header_authenticator`, which
trusts whatever roles a request claims to have. Both were tolerable because
uvicorn binds loopback and Caddy is the only thing that can reach it. Neither is
something to keep.

## What it does

The OpenID Connect authorization-code flow with PKCE, against one tenant:

1. ``/auth/login`` redirects to Entra with ``state``, ``nonce`` and a PKCE
   challenge, and remembers all three in a short-lived signed cookie. No
   server-side state, so a restart mid-sign-in fails cleanly rather than
   mysteriously.
2. ``/auth/callback`` checks ``state``, exchanges the code for an ID token,
   verifies that token's signature against the tenant's published keys, and
   checks issuer, audience, tenant and nonce.
3. The claims become a :class:`~trd365_orchestrator.security.Principal`, stored
   in a signed session cookie. No access token is kept: nothing here calls Graph,
   and a token we do not hold is a token that cannot leak.

## Why the app validates the token itself

The alternative — an authenticating proxy that injects identity headers — is less
work and strictly weaker: the application ends up trusting a header, which is
exactly the property that makes the development authenticator unfit for
production. Here the signature is checked against Entra's keys, so a forged
header is not enough and the trust boundary is the token, not the network path.

## Roles

Two sources, both optional, unioned:

* **App roles** — defined on the app registration and assigned to people or
  groups, arriving in the ``roles`` claim. Preferred: the mapping lives in Entra
  where it can be audited and delegated, and the claim stays small.
* **Group ids** — an explicit map from group object id to role, for
  organisations that would rather assign an existing security group than create
  app roles. Off unless configured.

A signed-in person with neither ends up with no roles, which by
:data:`~trd365_orchestrator.security.ANONYMOUS`'s own rule can read nothing
privileged and run nothing. Being known is not the same as being permitted.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from trd365_core.errors import ConfigError

from .security import Principal, Role

#: How long a sign-in is good for before Entra is consulted again.
SESSION_SECONDS = 8 * 60 * 60

#: How long the caller has to complete a sign-in once it has started.
FLOW_SECONDS = 10 * 60

SESSION_COOKIE = "trd365_session"
FLOW_COOKIE = "trd365_auth_flow"

#: The scopes the sign-in asks for. Only identity — no Graph, no mail, nothing
#: that would make this application a reason to hand over more than it needs.
SCOPES = ("openid", "profile", "email")


@dataclass(frozen=True)
class EntraConfig:
    """Everything the flow needs, and nothing it does not."""

    tenant_id: str
    client_id: str
    client_secret: str
    redirect_uri: str
    session_secret: str
    #: Group object id -> role, for tenants assigning existing security groups
    #: instead of app roles.
    group_roles: dict[str, Role] = field(default_factory=dict)
    #: Refuse the sign-in outright when a verified person holds no role here.
    #:
    #: On by default. Without it, everybody in the tenant can sign in and get a
    #: session that can do nothing — technically safe, and a poor answer to
    #: "who has access to this?", because the honest answer becomes "everyone,
    #: they just cannot see anything". Refusing makes access a list somebody
    #: maintains, and tells the person what to ask for.
    require_role: bool = True

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}"

    @property
    def issuer(self) -> str:
        return f"{self.authority}/v2.0"

    @property
    def jwks_uri(self) -> str:
        return f"{self.authority}/discovery/v2.0/keys"

    @property
    def token_endpoint(self) -> str:
        return f"{self.authority}/oauth2/v2.0/token"

    @property
    def authorize_endpoint(self) -> str:
        return f"{self.authority}/oauth2/v2.0/authorize"

    @property
    def logout_endpoint(self) -> str:
        return f"{self.authority}/oauth2/v2.0/logout"


def _group_roles(raw: str | None) -> dict[str, Role]:
    """
    Parse ``<group-id>=<role>,<group-id>=<role>``.

    An unparseable entry is an error rather than a skip: a typo in a role name
    would otherwise silently grant nobody anything, and "my access stopped
    working" is a much worse way to find out.
    """
    mapping: dict[str, Role] = {}
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        group, _, role = entry.partition("=")
        group, role = group.strip(), role.strip().lower()
        if not group or role not in set(Role):
            raise ConfigError(
                f"TRD365_ENTRA_GROUP_ROLES entry {entry!r} is not "
                f"<group-object-id>=<{'|'.join(sorted(Role))}>."
            )
        mapping[group] = Role(role)
    return mapping


def config_from_environment(
    environ: dict[str, str] | None = None, secrets_source=None
) -> EntraConfig | None:
    """
    Build the configuration, or ``None`` when Entra is not configured.

    ``None`` rather than an exception, so a deployment without SSO keeps working
    exactly as before. What must never happen is a *partial* configuration
    silently behaving like no configuration, so anything half-set is an error.

    The client secret and the session secret come from the vault when it has them,
    because neither belongs in a unit file or a process listing.
    """
    env = os.environ if environ is None else environ
    tenant = env.get("TRD365_ENTRA_TENANT_ID", "").strip()
    client = env.get("TRD365_ENTRA_CLIENT_ID", "").strip()
    redirect = env.get("TRD365_ENTRA_REDIRECT_URI", "").strip()

    if not any((tenant, client, redirect)):
        return None

    missing = [
        name
        for name, value in (
            ("TRD365_ENTRA_TENANT_ID", tenant),
            ("TRD365_ENTRA_CLIENT_ID", client),
            ("TRD365_ENTRA_REDIRECT_URI", redirect),
        )
        if not value
    ]
    if missing:
        raise ConfigError(
            "Entra sign-in is partly configured, which is more dangerous than not "
            f"configuring it: {', '.join(missing)} is missing. Set all of them, or none."
        )

    secret = _secret("TRD365_ENTRA_CLIENT_SECRET", "entra-client-secret", env, secrets_source)
    session = _secret("TRD365_SESSION_SECRET", "session-signing-secret", env, secrets_source)
    if not secret:
        raise ConfigError(
            "Entra sign-in is configured but no client secret was found, in "
            "TRD365_ENTRA_CLIENT_SECRET or the vault as 'entra-client-secret'."
        )
    if not session:
        raise ConfigError(
            "Entra sign-in needs a session signing secret, in TRD365_SESSION_SECRET or "
            "the vault as 'session-signing-secret'. Without one, session cookies could "
            "be forged. Generate 32 random bytes; it is not a password anyone types."
        )

    return EntraConfig(
        tenant_id=tenant,
        client_id=client,
        client_secret=secret,
        redirect_uri=redirect,
        session_secret=session,
        group_roles=_group_roles(env.get("TRD365_ENTRA_GROUP_ROLES")),
        require_role=env.get("TRD365_ENTRA_REQUIRE_ROLE", "1") != "0",
    )


def _secret(variable: str, vault_name: str, env, secrets_source) -> str:
    direct = env.get(variable, "").strip()
    if direct:
        return direct
    if secrets_source is None:
        return ""
    return (secrets_source.get(vault_name) or "").strip()


# ---------------------------------------------------------------------------
# signing — sessions and the in-flight flow
# ---------------------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    """
    Decode, or raise :class:`ValueError`.

    ``base64`` raises ``binascii.Error`` for a string it cannot decode, and every
    caller here is handling a cookie an attacker chooses. Unhandled, that is a 500
    from a one-byte request. ``binascii.Error`` subclasses ``ValueError``, so the
    callers catch the one thing.
    """
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


#: Marks what a signed token is for. Both tokens here are signed with the same
#: secret, and without this the two are one type: a session cookie presented as
#: the in-flight flow cookie is a payload the callback then reads fields off that
#: are not there. Stamping the purpose and checking it on the way back in makes
#: each token usable only where it was issued for.
PURPOSE_FLOW = "flow"
PURPOSE_SESSION = "session"


def sign(payload: dict[str, Any], secret: str, *, purpose: str | None = None) -> str:
    """
    A signed, unencrypted token: ``<base64 payload>.<base64 hmac>``.

    Deliberately not a JWT. Nothing here needs the algorithm to be negotiable, and
    an algorithm field an attacker can set is the single most common way JWT
    verification is got wrong. One algorithm, chosen here, not stated in the token.

    ``purpose`` is stamped into the payload as ``typ`` and checked by
    :func:`unsign`. It is signed along with everything else, so it cannot be
    changed without the secret.
    """
    import hmac

    if purpose is not None:
        payload = {**payload, "typ": purpose}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def unsign(token: str, secret: str, *, purpose: str | None = None) -> dict[str, Any] | None:
    """
    The payload if the signature holds, the purpose matches and it has not
    expired, else ``None``.

    Every branch returns ``None`` rather than raising. The argument is a cookie,
    which is to say a string an unauthenticated caller chose: a malformed one has
    to be an anonymous request, not a stack trace.
    """
    import hmac

    body, _, provided = token.partition(".")
    if not body or not provided:
        return None
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    try:
        signature = _unb64(provided)
    except ValueError:
        return None
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if purpose is not None and payload.get("typ") != purpose:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


# ---------------------------------------------------------------------------
# starting the flow
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Started:
    """Where to send the caller, and the cookie that remembers why."""

    url: str
    flow_cookie: str


def start(config: EntraConfig, *, return_to: str = "/") -> Started:
    """
    Build the authorize URL, with PKCE, and the cookie that binds the reply to it.

    ``state`` defends the callback against being driven by a third party.
    ``nonce`` binds the ID token to *this* request, so one obtained elsewhere
    cannot be replayed here. PKCE is not strictly required for a confidential
    client, but it costs one hash and removes an entire class of code-interception
    problem, so there is no reason not to.

    ``return_to`` is kept in the signed cookie rather than passed through Entra,
    and only a path is accepted — a full URL there is an open redirect waiting to
    be found.
    """
    verifier = _b64(secrets.token_bytes(32))
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    state = _b64(secrets.token_bytes(16))
    nonce = _b64(secrets.token_bytes(16))

    query = urllib.parse.urlencode(
        {
            "client_id": config.client_id,
            "response_type": "code",
            "redirect_uri": config.redirect_uri,
            "response_mode": "query",
            "scope": " ".join(SCOPES),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    flow = sign(
        {
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "return_to": safe_return_to(return_to),
            "exp": int(time.time()) + FLOW_SECONDS,
        },
        config.session_secret,
        purpose=PURPOSE_FLOW,
    )
    return Started(url=f"{config.authorize_endpoint}?{query}", flow_cookie=flow)


def safe_return_to(value: str | None) -> str:
    """
    A same-site path, or ``/``.

    Anything with a scheme or a host, and anything starting ``//``, is discarded.
    A login endpoint that will redirect anywhere afterwards is a phishing tool
    with the organisation's own domain on it.
    """
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


# ---------------------------------------------------------------------------
# finishing it
# ---------------------------------------------------------------------------


class SignInFailed(Exception):
    """The callback could not be turned into a signed-in person."""


class NotEntitled(SignInFailed):
    """Verified, and holds no role for this application."""


def exchange(config: EntraConfig, code: str, verifier: str, *, post=None) -> str:
    """Swap the authorization code for an ID token. Returns the raw token."""
    body = urllib.parse.urlencode(
        {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": config.redirect_uri,
            "code_verifier": verifier,
            "scope": " ".join(SCOPES),
        }
    )
    payload = (post or _post)(config.token_endpoint, body)
    token = payload.get("id_token")
    if not token:
        raise SignInFailed(
            f"the token endpoint returned no id_token: "
            f"{payload.get('error_description') or payload.get('error') or 'no reason given'}"
        )
    return token


def _post(url: str, body: str) -> dict[str, Any]:
    import urllib.request

    request = urllib.request.Request(
        url, data=body.encode(), headers={"content-type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:  # Entra puts the reason in the body
        try:
            return json.load(exc)
        except Exception:
            raise SignInFailed(f"the token endpoint returned {exc.code}") from exc
    except Exception as exc:
        raise SignInFailed(f"could not reach the token endpoint: {exc}") from exc


def verify(config: EntraConfig, id_token: str, nonce: str, *, jwks_client=None) -> dict[str, Any]:
    """
    Verify the ID token's signature and every claim that matters.

    ``jwt.decode`` is given the algorithm explicitly rather than reading it from
    the token, and ``audience`` and ``issuer`` are checked by the library. Three
    further checks are ours because they are specific to what this deployment
    accepts:

    * ``tid`` is *this* tenant, so a token minted for another tenant's copy of the
      app registration cannot be presented here;
    * ``nonce`` matches the one from this sign-in, so a token obtained elsewhere
      cannot be replayed;
    * there is a subject at all, since everything downstream keys off it and an
      audit record with no actor is not an audit record.
    """
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise SignInFailed(
            "PyJWT is not installed, so ID tokens cannot be verified. Entra sign-in "
            "refuses rather than accepting an unverified token."
        ) from exc

    client = jwks_client or jwt.PyJWKClient(config.jwks_uri, cache_keys=True)
    try:
        key = client.get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(
            id_token,
            key=key,
            algorithms=["RS256"],
            audience=config.client_id,
            issuer=config.issuer,
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )
    except Exception as exc:
        raise SignInFailed(f"the ID token did not verify: {exc}") from exc

    if claims.get("tid") != config.tenant_id:
        raise SignInFailed(
            f"the ID token is for tenant {claims.get('tid')}, not {config.tenant_id}."
        )
    if not nonce or claims.get("nonce") != nonce:
        raise SignInFailed("the ID token's nonce does not match this sign-in.")
    if not claims.get("sub"):
        raise SignInFailed("the ID token carries no subject.")
    return claims


def roles_from(claims: dict[str, Any], group_roles: dict[str, Role]) -> frozenset[Role]:
    """
    The roles this person holds, from app roles and configured groups.

    Unrecognised app roles are ignored rather than refused: Entra is where the
    assignment lives, and a role added there for some other purpose should not
    lock everybody out of this one.
    """
    found: set[Role] = set()
    for value in claims.get("roles") or ():
        if str(value).lower() in set(Role):
            found.add(Role(str(value).lower()))
    for group in claims.get("groups") or ():
        role = group_roles.get(str(group))
        if role is not None:
            found.add(role)
    return frozenset(found)


def entitled(principal: Principal, config: EntraConfig) -> None:
    """
    Raise :class:`NotEntitled` when a verified person holds no role here.

    Separate from verification on purpose. The token is genuine and the person is
    who they say they are — they simply have no business in this application, which
    is a different answer and deserves a different message.
    """
    if config.require_role and not principal.roles:
        raise NotEntitled(
            f"{principal.subject} signed in successfully but has no role for this "
            f"application. Access is granted per person in Entra ID, not by having a "
            f"certainti.ai account. Ask an administrator to assign one of: "
            f"{', '.join(sorted(Role))}."
        )


def principal_from(claims: dict[str, Any], group_roles: dict[str, Role]) -> Principal:
    """Turn verified claims into the caller this service reasons about."""
    subject = (
        claims.get("preferred_username") or claims.get("email") or claims.get("sub")
    )
    return Principal(
        subject=str(subject),
        display_name=str(claims.get("name") or subject),
        roles=roles_from(claims, group_roles),
    )


def session_for(principal: Principal, config: EntraConfig, *, now: float | None = None) -> str:
    """The signed session cookie for a signed-in person."""
    issued = int(now if now is not None else time.time())
    return sign(
        {
            "sub": principal.subject,
            "name": principal.display_name,
            "roles": sorted(str(role) for role in principal.roles),
            "iat": issued,
            "exp": issued + SESSION_SECONDS,
        },
        config.session_secret,
        purpose=PURPOSE_SESSION,
    )


def principal_from_session(cookie: str | None, config: EntraConfig) -> Principal | None:
    """The signed-in person a session cookie names, or ``None``."""
    if not cookie:
        return None
    payload = unsign(cookie, config.session_secret, purpose=PURPOSE_SESSION)
    if payload is None or not payload.get("sub"):
        return None
    roles = frozenset(
        Role(value) for value in payload.get("roles", []) if value in set(Role)
    )
    return Principal(
        subject=str(payload["sub"]),
        display_name=str(payload.get("name") or payload["sub"]),
        roles=roles,
    )


def logout_url(config: EntraConfig, *, return_to: str) -> str:
    """Sign out of Entra as well, not just out of this application."""
    query = urllib.parse.urlencode({"post_logout_redirect_uri": return_to})
    return f"{config.logout_endpoint}?{query}"
