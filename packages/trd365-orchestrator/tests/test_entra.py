"""
Entra ID sign-in.

Almost every test here is about refusing something. That is the point: this
replaces a shared password and a header the caller could write themselves, and it
is only an improvement if the checks it adds actually hold.

ID tokens are signed with a real RSA key generated in the fixtures and verified
through the real PyJWT path, so signature verification is exercised rather than
stubbed. A test that mocks out the verification proves nothing about the thing
most worth proving.
"""

from __future__ import annotations

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from trd365_core.errors import ConfigError

from trd365_orchestrator import entra
from trd365_orchestrator.security import Role

TENANT = "b6734060-665c-4b7b-94e2-716458c1d933"
CLIENT = "11111111-2222-3333-4444-555555555555"
SECRET = "a-session-signing-secret-of-adequate-length"


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def config():
    return entra.EntraConfig(
        tenant_id=TENANT,
        client_id=CLIENT,
        client_secret="client-secret",
        redirect_uri="https://console.example/auth/callback",
        session_secret=SECRET,
    )


def id_token(key, **overrides):
    now = int(time.time())
    claims = {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "aud": CLIENT,
        "sub": "subject-abc",
        "tid": TENANT,
        "nonce": "the-nonce",
        "iat": now,
        "exp": now + 600,
        "name": "Priya Raman",
        "preferred_username": "priya@certainti.ai",
        "roles": ["operator"],
    }
    claims.update(overrides)
    for key_name in [k for k, v in claims.items() if v is None]:
        del claims[key_name]
    return jwt.encode(claims, key, algorithm="RS256")


class Keys:
    """Stands in for PyJWKClient, handing back the public key we signed with."""

    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, _token):
        return type("Key", (), {"key": self._key.public_key()})()


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_nothing_set_means_no_entra(self):
        # A deployment without SSO must keep working exactly as before.
        assert entra.config_from_environment({}) is None

    def test_a_partial_configuration_is_refused(self):
        # More dangerous than none: it would look configured and behave as though
        # it were not.
        with pytest.raises(ConfigError, match="partly configured"):
            entra.config_from_environment({"TRD365_ENTRA_TENANT_ID": TENANT})

    def test_the_error_names_what_is_missing(self):
        with pytest.raises(ConfigError) as raised:
            entra.config_from_environment(
                {"TRD365_ENTRA_TENANT_ID": TENANT, "TRD365_ENTRA_CLIENT_ID": CLIENT}
            )
        assert "TRD365_ENTRA_REDIRECT_URI" in str(raised.value)

    def test_a_complete_configuration_from_the_environment(self):
        found = entra.config_from_environment(
            {
                "TRD365_ENTRA_TENANT_ID": TENANT,
                "TRD365_ENTRA_CLIENT_ID": CLIENT,
                "TRD365_ENTRA_REDIRECT_URI": "https://c/auth/callback",
                "TRD365_ENTRA_CLIENT_SECRET": "s",
                "TRD365_SESSION_SECRET": SECRET,
            }
        )
        assert found.tenant_id == TENANT
        assert found.issuer == f"https://login.microsoftonline.com/{TENANT}/v2.0"

    def test_secrets_can_come_from_the_vault(self):
        class Vault:
            def get(self, name):
                held = {"entra-client-secret": "vaulted", "session-signing-secret": SECRET}
                return held.get(name)

        found = entra.config_from_environment(
            {
                "TRD365_ENTRA_TENANT_ID": TENANT,
                "TRD365_ENTRA_CLIENT_ID": CLIENT,
                "TRD365_ENTRA_REDIRECT_URI": "https://c/auth/callback",
            },
            secrets_source=Vault(),
        )
        assert found.client_secret == "vaulted"

    def test_a_missing_session_secret_is_refused(self):
        # Without one, session cookies could be forged, which would make the whole
        # exercise pointless.
        with pytest.raises(ConfigError, match="session signing secret"):
            entra.config_from_environment(
                {
                    "TRD365_ENTRA_TENANT_ID": TENANT,
                    "TRD365_ENTRA_CLIENT_ID": CLIENT,
                    "TRD365_ENTRA_REDIRECT_URI": "https://c/auth/callback",
                    "TRD365_ENTRA_CLIENT_SECRET": "s",
                }
            )

    @pytest.mark.parametrize("raw", ["g1=viewer", "g1=viewer,g2=admin", " g1 = operator "])
    def test_group_role_mappings_parse(self, raw):
        assert entra._group_roles(raw)

    @pytest.mark.parametrize("raw", ["g1=superuser", "g1", "=viewer"])
    def test_a_bad_group_role_mapping_is_refused(self, raw):
        # A typo would otherwise grant nobody anything, and "my access stopped
        # working" is a much worse way to discover it.
        with pytest.raises(ConfigError):
            entra._group_roles(raw)


# ---------------------------------------------------------------------------
# starting the flow
# ---------------------------------------------------------------------------


class TestStartingTheFlow:
    def test_it_asks_for_a_code_with_pkce(self, config):
        started = entra.start(config)
        assert "response_type=code" in started.url
        assert "code_challenge_method=S256" in started.url
        assert f"client_id={CLIENT}" in started.url

    def test_it_asks_only_for_identity_scopes(self, config):
        # Nothing here calls Graph. A scope not requested is a permission nobody
        # has to review.
        assert entra.SCOPES == ("openid", "profile", "email")
        assert "offline_access" not in entra.start(config).url

    def test_state_and_nonce_are_fresh_every_time(self, config):
        first = entra.unsign(entra.start(config).flow_cookie, SECRET)
        second = entra.unsign(entra.start(config).flow_cookie, SECRET)
        assert first["state"] != second["state"]
        assert first["nonce"] != second["nonce"]

    def test_the_verifier_matches_the_challenge_in_the_url(self):
        import base64
        import hashlib
        import urllib.parse

        config = entra.EntraConfig(TENANT, CLIENT, "s", "https://c/cb", SECRET)
        started = entra.start(config)
        verifier = entra.unsign(started.flow_cookie, SECRET)["verifier"]
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        query = urllib.parse.parse_qs(urllib.parse.urlparse(started.url).query)
        assert query["code_challenge"] == [expected]

    def test_the_flow_cookie_expires(self, config):
        payload = entra.unsign(entra.start(config).flow_cookie, SECRET)
        assert payload["exp"] <= time.time() + entra.FLOW_SECONDS + 1


class TestReturnTo:
    @pytest.mark.parametrize("value", ["/utilities", "/#/activity", "/"])
    def test_a_same_site_path_is_kept(self, value):
        assert entra.safe_return_to(value) == value

    @pytest.mark.parametrize(
        "value",
        ["https://evil.example/", "//evil.example/", "http://evil.example", "", None, "utilities"],
    )
    def test_anything_else_becomes_the_root(self, value):
        # A sign-in that will redirect anywhere afterwards is a phishing tool with
        # the organisation's own domain on it.
        assert entra.safe_return_to(value) == "/"


# ---------------------------------------------------------------------------
# verifying the token — the part that has to be right
# ---------------------------------------------------------------------------


class TestVerification:
    def test_a_good_token_verifies(self, config, key):
        claims = entra.verify(config, id_token(key), "the-nonce", jwks_client=Keys(key))
        assert claims["sub"] == "subject-abc"

    def test_a_token_signed_by_someone_else_is_refused(self, config, key):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = id_token(other)
        with pytest.raises(entra.SignInFailed, match="did not verify"):
            entra.verify(config, forged, "the-nonce", jwks_client=Keys(key))

    def test_a_tampered_token_is_refused(self, config, key):
        token = id_token(key)
        head, payload, signature = token.split(".")
        # Re-encode the payload with an extra role and keep the old signature.
        import base64

        decoded = json.loads(base64.urlsafe_b64decode(payload + "=="))
        decoded["roles"] = ["admin"]
        swapped = (
            base64.urlsafe_b64encode(json.dumps(decoded).encode()).rstrip(b"=").decode()
        )
        with pytest.raises(entra.SignInFailed):
            entra.verify(
                config, f"{head}.{swapped}.{signature}", "the-nonce", jwks_client=Keys(key)
            )

    def test_an_unsigned_token_is_refused(self, config, key):
        # The alg=none attack. PyJWT is given the algorithm explicitly, so this
        # cannot be talked into accepting it.
        forged = jwt.encode({"sub": "x", "aud": CLIENT}, key=None, algorithm=None)
        with pytest.raises(entra.SignInFailed):
            entra.verify(config, forged, "the-nonce", jwks_client=Keys(key))

    def test_another_tenants_token_is_refused(self, config, key):
        # The one that matters if the app registration is ever made multi-tenant:
        # a valid token from a different directory must not work here.
        token = id_token(key, tid="99999999-9999-9999-9999-999999999999")
        with pytest.raises(entra.SignInFailed, match="is for tenant"):
            entra.verify(config, token, "the-nonce", jwks_client=Keys(key))

    def test_a_token_for_another_application_is_refused(self, config, key):
        with pytest.raises(entra.SignInFailed):
            entra.verify(
                config, id_token(key, aud="another-app"), "the-nonce", jwks_client=Keys(key)
            )

    def test_a_token_from_another_issuer_is_refused(self, config, key):
        token = id_token(key, iss="https://login.microsoftonline.com/other/v2.0")
        with pytest.raises(entra.SignInFailed):
            entra.verify(config, token, "the-nonce", jwks_client=Keys(key))

    def test_an_expired_token_is_refused(self, config, key):
        token = id_token(key, exp=int(time.time()) - 10)
        with pytest.raises(entra.SignInFailed):
            entra.verify(config, token, "the-nonce", jwks_client=Keys(key))

    def test_a_replayed_token_from_another_sign_in_is_refused(self, config, key):
        # Correctly signed, right tenant, right audience — and obtained during a
        # different sign-in. The nonce is what stops it.
        with pytest.raises(entra.SignInFailed, match="nonce"):
            entra.verify(config, id_token(key), "a-different-nonce", jwks_client=Keys(key))

    def test_a_token_with_no_nonce_is_refused(self, config, key):
        with pytest.raises(entra.SignInFailed, match="nonce"):
            entra.verify(config, id_token(key, nonce=None), "the-nonce", jwks_client=Keys(key))

    def test_a_token_with_no_subject_is_refused(self, config, key):
        # Everything downstream keys off it, and an audit record with no actor is
        # not an audit record.
        with pytest.raises(entra.SignInFailed):
            entra.verify(config, id_token(key, sub=None), "the-nonce", jwks_client=Keys(key))


# ---------------------------------------------------------------------------
# roles
# ---------------------------------------------------------------------------


class TestRoles:
    def test_app_roles_become_roles(self):
        found = entra.roles_from({"roles": ["operator", "viewer"]}, {})
        assert found == frozenset({Role.OPERATOR, Role.VIEWER})

    def test_an_unrecognised_app_role_is_ignored_not_fatal(self):
        # Entra is where assignment lives; a role added there for something else
        # must not lock everybody out of this.
        assert entra.roles_from({"roles": ["operator", "billing-admin"]}, {}) == frozenset(
            {Role.OPERATOR}
        )

    def test_group_ids_can_map_to_roles(self):
        found = entra.roles_from({"groups": ["group-1"]}, {"group-1": Role.APPROVER})
        assert found == frozenset({Role.APPROVER})

    def test_both_sources_are_unioned(self):
        found = entra.roles_from(
            {"roles": ["viewer"], "groups": ["group-1"]}, {"group-1": Role.OPERATOR}
        )
        assert found == frozenset({Role.VIEWER, Role.OPERATOR})

    def test_an_unmapped_group_grants_nothing(self):
        assert entra.roles_from({"groups": ["group-9"]}, {"group-1": Role.ADMIN}) == frozenset()

    def test_signing_in_with_no_assignment_grants_nothing(self):
        # Being known is not the same as being permitted. A signed-in person with
        # no role can read nothing privileged and run nothing.
        principal = entra.principal_from({"sub": "s", "name": "Sam"}, {})
        assert principal.roles == frozenset()
        assert principal.is_anonymous

    def test_the_subject_prefers_the_username_a_person_would_recognise(self):
        principal = entra.principal_from(
            {"sub": "opaque-guid", "preferred_username": "priya@certainti.ai", "name": "Priya"}, {}
        )
        # This is what lands in every audit record, so it has to be legible.
        assert principal.subject == "priya@certainti.ai"
        assert principal.display_name == "Priya"

    def test_it_falls_back_to_the_subject_when_there_is_no_username(self):
        assert entra.principal_from({"sub": "opaque-guid"}, {}).subject == "opaque-guid"


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------


class TestSessions:
    def test_a_session_round_trips(self, config, key):
        claims = entra.verify(config, id_token(key), "the-nonce", jwks_client=Keys(key))
        principal = entra.principal_from(claims, {})
        restored = entra.principal_from_session(entra.session_for(principal, config), config)
        assert restored == principal

    def test_a_tampered_session_is_rejected(self, config):
        from trd365_orchestrator.security import Principal

        cookie = entra.session_for(Principal("p", "P", frozenset({Role.VIEWER})), config)
        body, _, signature = cookie.partition(".")
        payload = json.loads(entra._unb64(body))
        payload["roles"] = ["admin"]
        forged = f"{entra._b64(json.dumps(payload).encode())}.{signature}"
        assert entra.principal_from_session(forged, config) is None

    def test_a_session_signed_with_another_secret_is_rejected(self, config):
        from trd365_orchestrator.security import Principal

        other = entra.EntraConfig(TENANT, CLIENT, "s", "https://c/cb", "a-different-secret")
        cookie = entra.session_for(Principal("p", "P", frozenset({Role.ADMIN})), other)
        assert entra.principal_from_session(cookie, config) is None

    def test_an_expired_session_is_rejected(self, config):
        from trd365_orchestrator.security import Principal

        cookie = entra.session_for(
            Principal("p", "P", frozenset({Role.VIEWER})),
            config,
            now=time.time() - entra.SESSION_SECONDS - 60,
        )
        assert entra.principal_from_session(cookie, config) is None

    def test_no_cookie_is_no_principal(self, config):
        assert entra.principal_from_session(None, config) is None
        assert entra.principal_from_session("", config) is None
        assert entra.principal_from_session("nonsense", config) is None

    def test_the_session_holds_no_tokens(self, config):
        from trd365_orchestrator.security import Principal

        cookie = entra.session_for(Principal("p", "P", frozenset({Role.VIEWER})), config)
        payload = json.loads(entra._unb64(cookie.partition(".")[0]))
        # Nothing here calls Graph, so no access or refresh token is kept. A token
        # not held is a token that cannot leak.
        assert set(payload) == {"sub", "name", "roles", "iat", "exp"}

    def test_the_signature_does_not_state_its_own_algorithm(self, config):
        # Deliberately not a JWT: an algorithm field the attacker can set is the
        # most common way token verification is got wrong.
        from trd365_orchestrator.security import Principal

        cookie = entra.session_for(Principal("p", "P", frozenset()), config)
        assert cookie.count(".") == 1
        assert "alg" not in json.loads(entra._unb64(cookie.partition(".")[0]))


# ---------------------------------------------------------------------------
# the routes
# ---------------------------------------------------------------------------


class TestSignInRoutes:
    """The three endpoints, driven through the real app."""

    @pytest.fixture
    def client(self, monkeypatch):
        from fastapi.testclient import TestClient

        from trd365_orchestrator.app import create_app

        for name, value in (
            ("TRD365_ENTRA_TENANT_ID", TENANT),
            ("TRD365_ENTRA_CLIENT_ID", CLIENT),
            ("TRD365_ENTRA_REDIRECT_URI", "https://console.example/auth/callback"),
            ("TRD365_ENTRA_CLIENT_SECRET", "client-secret"),
            ("TRD365_SESSION_SECRET", SECRET),
        ):
            monkeypatch.setenv(name, value)
        monkeypatch.delenv("TRD365_DEV_AUTH", raising=False)
        with TestClient(create_app(), base_url="https://console.example") as c:
            yield c

    def test_login_redirects_to_entra(self, client):
        response = client.get("/auth/login", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"].startswith(
            f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize?"
        )

    def test_login_sets_a_locked_down_flow_cookie(self, client):
        response = client.get("/auth/login", follow_redirects=False)
        cookie = response.headers["set-cookie"]
        assert entra.FLOW_COOKIE in cookie
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "Path=/auth" in cookie

    def test_a_callback_with_no_flow_cookie_is_refused(self, client):
        response = client.get("/auth/callback?code=x&state=y")
        assert response.status_code == 401
        assert "expired or did not start here" in response.json()["detail"]

    def test_a_callback_whose_state_does_not_match_is_refused(self, client):
        client.get("/auth/login", follow_redirects=False)
        response = client.get("/auth/callback?code=x&state=not-the-state")
        assert response.status_code == 401
        assert "did not match" in response.json()["detail"]

    def test_an_error_from_entra_is_reported_not_swallowed(self, client):
        client.get("/auth/login", follow_redirects=False)
        response = client.get("/auth/callback?error=access_denied&error_description=Not+assigned")
        assert response.status_code == 401
        assert "Not assigned" in response.json()["detail"]

    def test_logout_clears_the_session_and_signs_out_of_entra(self, client):
        response = client.get("/auth/logout", follow_redirects=False)
        assert response.status_code == 303
        assert "/oauth2/v2.0/logout" in response.headers["location"]
        assert entra.SESSION_COOKIE in response.headers["set-cookie"]

    def test_the_api_is_anonymous_without_a_session(self, client):
        # No session cookie, so no roles, so nothing readable.
        assert client.get("/api/utilities").status_code == 403

    def test_a_valid_session_is_accepted_by_the_api(self, client, config):
        from trd365_orchestrator.security import Principal

        cookie = entra.session_for(
            Principal("priya@certainti.ai", "Priya", frozenset({Role.VIEWER})), config
        )
        client.cookies.set(entra.SESSION_COOKIE, cookie)
        payload = client.get("/api/me").json()
        assert payload["subject"] == "priya@certainti.ai"
        assert payload["can_view"] is True
        assert payload["can_run"] is False

    def test_a_forged_role_header_is_ignored_once_entra_is_on(self, client):
        # The whole point. With the development authenticator this header *was* the
        # identity; now it is just a header.
        assert client.get("/api/utilities", headers={"x-dev-roles": "admin"}).status_code == 403

    def test_the_service_says_it_uses_entra(self, client):
        assert client.get("/api").json()["authentication"] == "entra id"

    def test_writes_are_permitted_at_all_once_entra_is_configured(self, client, config):
        # Regression: `authentication_configured` used to be derived from the dev
        # flag alone, so turning Entra on turned dev auth off and the orchestrator
        # refused every write as "authentication is not configured".
        from trd365_orchestrator.security import Principal

        cookie = entra.session_for(
            Principal("ops@certainti.ai", "Ops", frozenset({Role.OPERATOR})), config
        )
        client.cookies.set(entra.SESSION_COOKIE, cookie)
        response = client.post(
            "/api/jobs",
            json={
                "utility_id": "purge-account",
                "environment": "dev",
                "arguments": {"account_rid": "r-1"},
                "apply": True,
            },
        )
        assert "authentication is not configured" not in response.text.lower()


class TestWhoGetsIn:
    """
    Having a certainti.ai account is not access. Access is an assignment.

    Three outcomes, and the tenant-wide one is the default: no assignment means the
    sign-in is refused, not that a blind session is issued.
    """

    def test_no_assignment_is_refused(self, config):
        from trd365_orchestrator.security import Principal

        with pytest.raises(entra.NotEntitled, match="no role for this application"):
            entra.entitled(Principal("nobody@certainti.ai", "Nobody", frozenset()), config)

    def test_the_refusal_says_what_to_ask_for(self, config):
        from trd365_orchestrator.security import Principal

        with pytest.raises(entra.NotEntitled) as raised:
            entra.entitled(Principal("nobody@certainti.ai", "Nobody", frozenset()), config)
        message = str(raised.value)
        assert "not by having a certainti.ai account" in message
        for role in Role:
            assert str(role) in message

    def test_a_viewer_gets_in(self, config):
        from trd365_orchestrator.security import Principal

        entra.entitled(Principal("v@certainti.ai", "V", frozenset({Role.VIEWER})), config)

    def test_an_operator_gets_in(self, config):
        from trd365_orchestrator.security import Principal

        entra.entitled(Principal("o@certainti.ai", "O", frozenset({Role.OPERATOR})), config)

    def test_it_can_be_turned_off_deliberately(self):
        from trd365_orchestrator.security import Principal

        relaxed = entra.EntraConfig(
            TENANT, CLIENT, "s", "https://c/cb", SECRET, require_role=False
        )
        entra.entitled(Principal("anyone@certainti.ai", "Anyone", frozenset()), relaxed)

    def test_it_is_on_unless_explicitly_disabled(self):
        base = {
            "TRD365_ENTRA_TENANT_ID": TENANT,
            "TRD365_ENTRA_CLIENT_ID": CLIENT,
            "TRD365_ENTRA_REDIRECT_URI": "https://c/auth/callback",
            "TRD365_ENTRA_CLIENT_SECRET": "s",
            "TRD365_SESSION_SECRET": SECRET,
        }
        assert entra.config_from_environment(base).require_role is True
        assert entra.config_from_environment(
            {**base, "TRD365_ENTRA_REQUIRE_ROLE": "0"}
        ).require_role is False

    def test_read_only_and_update_are_different_roles(self):
        # The answer to "how do I control read-only versus update": viewer reads and
        # cannot start anything that writes; operator can.
        from helpers import PURGE
        from trd365_core.environments import Environment

        from trd365_orchestrator.security import Principal, can_run, can_view

        viewer = Principal("v", "V", frozenset({Role.VIEWER}))
        operator = Principal("o", "O", frozenset({Role.OPERATOR}))

        assert can_view(viewer) and can_view(operator)
        assert can_run(viewer, PURGE, Environment.DEV) is False
        assert can_run(operator, PURGE, Environment.DEV) is True

    def test_and_approving_is_a_third_role_that_cannot_be_self_served(self):
        from trd365_orchestrator.security import Principal, can_approve

        operator = Principal("o", "O", frozenset({Role.OPERATOR}))
        both = Principal("o", "O", frozenset({Role.OPERATOR, Role.APPROVER}))
        other = Principal("a", "A", frozenset({Role.APPROVER}))

        assert can_approve(operator, "someone-else") is False
        assert can_approve(both, "o") is False, "self-approval must stay refused"
        assert can_approve(other, "o") is True
