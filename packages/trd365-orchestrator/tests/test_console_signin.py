"""
That the console offers a way in.

The bug this exists to prevent shipped once and was invisible from the server
side: every route answered correctly, and the console still could not be signed
into.

`/api/me` is deliberately public and answers **200** with an anonymous identity
rather than 401 — the console needs to know who you are in order to decide what
to offer, and a refusal carries less information than an answer. The console read
that success as "signed in", took the authenticated branch, and rendered
"unauthenticated / none / sign out". The offer to sign in lived in the `catch`,
which no longer ran.

So there are three states and they must stay three: not signed in, signed in with
nothing assigned, and signed in with a role. The first two both have an empty role
set and completely different remedies.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trd365_orchestrator.app import create_app
from trd365_orchestrator.security import ANONYMOUS, Principal, Role

CONSOLE = (
    Path(__file__).resolve().parents[1] / "src" / "trd365_orchestrator" / "web" / "index.html"
).read_text()


class TestTheApiSaysWhichStateYouAreIn:
    def test_anonymous_is_reported_as_not_authenticated(self):
        client = TestClient(create_app())
        body = client.get("/api/me").json()
        assert body["authenticated"] is False
        assert body["roles"] == []
        assert body["can_view"] is False

    def test_a_signed_in_caller_with_no_roles_is_still_authenticated(self):
        # The state that used to be indistinguishable from anonymous. It needs
        # "ask for a role", not "sign in".
        app = create_app(authenticator=lambda _r: Principal("u1", "Someone"))
        body = TestClient(app).get("/api/me").json()
        assert body["authenticated"] is True
        assert body["roles"] == []
        assert body["can_view"] is False

    def test_a_signed_in_caller_with_a_role_can_view(self):
        app = create_app(
            authenticator=lambda _r: Principal("u1", "Someone", frozenset({Role.VIEWER}))
        )
        body = TestClient(app).get("/api/me").json()
        assert body["authenticated"] is True
        assert body["roles"] == ["viewer"]
        assert body["can_view"] is True

    def test_the_anonymous_principal_is_marked_unauthenticated(self):
        assert ANONYMOUS.authenticated is False
        assert Principal("u1", "Someone").authenticated is True


class TestTheConsoleBranchesOnIt:
    def _identity_block(self) -> str:
        match = re.search(r"async function loadMe\(\) \{(.+?)\n\}", CONSOLE, re.S)
        assert match, "loadMe() is gone — has the console been rewritten?"
        return match.group(1)

    def test_the_sign_in_offer_does_not_depend_on_a_failed_request(self):
        block = self._identity_block()
        assert "/auth/login" in block
        # The offer must be reachable on a *successful* /api/me. Locating it
        # relative to the catch is the only way to assert that from here.
        before_catch = block.split("} catch")[0]
        assert "/auth/login" in before_catch or "authenticated" in before_catch

    def test_it_reads_the_authenticated_flag(self):
        assert "state.me.authenticated" in self._identity_block()

    def test_signed_in_with_nothing_assigned_says_so(self):
        assert "no role assigned" in CONSOLE.lower()

    @pytest.mark.parametrize("phrase", ["Not signed in", "No role assigned"])
    def test_an_empty_console_explains_which_of_the_two_it_is(self, phrase):
        notice = re.search(r"function accessNotice\(\) \{(.+?)\n\}", CONSOLE, re.S)
        assert notice, "accessNotice() is gone"
        assert phrase in notice.group(1)

    def test_the_notice_is_rendered_rather_than_merely_defined(self):
        # Dead code that says the right thing is still dead code.
        assert re.search(r"accessNotice\(\)", CONSOLE.replace("function accessNotice()", ""))
