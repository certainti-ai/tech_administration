"""
Who is asking, and what they are allowed to do.

Entra ID sign-in belongs to the web application (PRD FR-4.1); what lives here is
the model it plugs into — roles, per-environment authorisation, and the rule
that production writes need a second person.

The default when no authenticator is configured is **not** "allow": it is to
refuse anything that writes. An unauthenticated deployment that could purge
production would be worse than one that does not start.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from trd365_core.environments import Environment
from trd365_core.errors import Trd365Error
from trd365_core.registry import Utility


class AuthorizationError(Trd365Error):
    """The caller may not do this."""


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    APPROVER = "approver"
    ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    """A caller, authenticated or not."""

    subject: str
    display_name: str
    roles: frozenset[Role] = field(default_factory=frozenset)

    #: Whether we know who this is. Distinct from holding no roles: somebody who
    #: signed in and has not been assigned anything is authenticated and
    #: powerless, and the two need different messages — "sign in" versus "ask for
    #: a role". Inferring it from an empty role set gave the first of those to
    #: somebody who needed the second.
    authenticated: bool = True

    def has(self, *roles: Role) -> bool:
        return bool(self.roles.intersection(roles))

    @property
    def is_anonymous(self) -> bool:
        return not self.roles


#: Used when no authenticator is configured, and when a request arrives with no
#: session. Deliberately holds no roles, so it can read nothing privileged and
#: run nothing at all.
ANONYMOUS = Principal(
    subject="anonymous", display_name="unauthenticated", authenticated=False
)


def can_view(principal: Principal) -> bool:
    return principal.has(Role.VIEWER, Role.OPERATOR, Role.APPROVER, Role.ADMIN)


def can_run(principal: Principal, utility: Utility, env: Environment) -> bool:
    """
    Whether this caller may *start* a run.

    Read-only utilities need only viewer. Anything that writes needs operator or
    admin. Production writes may be *requested* by an operator but do not start
    until approved — see :func:`can_approve`.
    """
    if not utility.impact.needs_apply:
        return can_view(principal)
    return principal.has(Role.OPERATOR, Role.ADMIN)


def can_approve(principal: Principal, requested_by: str) -> bool:
    """
    Whether this caller may approve someone else's production run.

    Self-approval is refused regardless of role: a second approver that can be
    the same person is not a second approver (PRD FR-4.3).
    """
    if principal.subject == requested_by:
        return False
    return principal.has(Role.APPROVER, Role.ADMIN)


def requires_approval(utility: Utility, env: Environment, apply: bool) -> bool:
    """
    Production writes need a second person.

    A dry run normally does not: the whole point of a preview is that it is safe
    to take without ceremony, because it counts rows and touches nothing.

    Some previews are not free. The project and project-fiscal purges preview by
    running the vendor's delete-and-recompute SQL inside a transaction they then
    roll back — same locks, same work, result discarded. A utility that declares
    ``dry_run_executes`` therefore needs the second person in production either
    way. Without this, granting somebody the operator role would let them start
    real work against production unreviewed just by calling it a preview.
    """
    if not env.is_production:
        return False
    if apply:
        return utility.impact.needs_apply
    return utility.dry_run_requires_approval_in_prod


def authorize_run(
    principal: Principal,
    utility: Utility,
    env: Environment,
    apply: bool,
    *,
    authentication_configured: bool,
) -> None:
    """Raise :class:`AuthorizationError` unless this run may be started."""
    if not authentication_configured and (apply or utility.impact.needs_apply):
        raise AuthorizationError(
            "Authentication is not configured, so this deployment will not run anything "
            "that writes. Configure an authenticator, or use dry runs only."
        )

    if env not in utility.environments:
        raise AuthorizationError(f"{utility.id} is not permitted in {env.value}.")

    if not can_run(principal, utility, env):
        need = "operator" if utility.impact.needs_apply else "viewer"
        raise AuthorizationError(
            f"{principal.display_name} needs the {need} role to run {utility.id}."
        )
