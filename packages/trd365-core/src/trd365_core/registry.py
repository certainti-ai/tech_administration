"""
The catalogue of maintenance utilities.

One description per utility: what it does, what it takes, whether it writes,
and which databases it touches. The Phase-2 API and the Phase-3 invocation UI
are both generated from this, so adding a utility does not mean editing the
frontend (PRD FR-4.4).

It is also where the safety invariant is enforceable: a test asserts that every
registered destructive utility is dry-run by default, which is the regression
guard for the estate's headline bug.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .environments import DB_KEYS, Environment
from .errors import Trd365Error


class ParameterType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    PATH = "path"
    ENUM = "enum"


@dataclass(frozen=True)
class Parameter:
    name: str
    type: ParameterType
    help: str
    required: bool = False
    default: Any = None
    choices: tuple[str, ...] | None = None

    @property
    def cli_flag(self) -> str:
        return "--" + self.name.replace("_", "-")


class Impact(StrEnum):
    """What a utility does to the databases it touches."""

    READ_ONLY = "read-only"
    WRITES = "writes"
    DESTRUCTIVE = "destructive"

    @property
    def needs_apply(self) -> bool:
        return self is not Impact.READ_ONLY


@dataclass(frozen=True)
class Utility:
    id: str
    title: str
    description: str
    module: str
    impact: Impact
    databases: tuple[str, ...]
    parameters: tuple[Parameter, ...] = ()
    #: Environments this may run in. Prod stays allowed but gated by approval.
    environments: tuple[Environment, ...] = tuple(Environment)
    #: Set when a utility supersedes another that still exists.
    supersedes: str | None = None
    #: True when a dry run is *not* free — it does the work and discards it.
    #:
    #: Almost every utility previews by counting rows without touching them, so a
    #: dry run is safe to take without ceremony. The project and project-fiscal
    #: purges cannot: they run hand-written PL/pgSQL that deletes *and recomputes*
    #: financial aggregates, and the only way to preview that is to execute it
    #: inside a transaction that is then rolled back. Same locks, same work, result
    #: discarded. That is not something to start against production casually, so
    #: utilities that declare this need an approver in production even for a
    #: preview.
    dry_run_executes: bool = False
    notes: str = ""

    @property
    def is_destructive(self) -> bool:
        return self.impact is Impact.DESTRUCTIVE

    @property
    def requires_approval_in_prod(self) -> bool:
        """Anything that writes to production needs a second human (FR-4.3)."""
        return self.impact.needs_apply

    @property
    def dry_run_requires_approval_in_prod(self) -> bool:
        """A preview that is not free needs the same second human."""
        return self.dry_run_executes

    def to_dict(self) -> dict[str, Any]:
        """Serialisable form — this is the API payload the UI renders from."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "module": self.module,
            "impact": self.impact.value,
            "databases": list(self.databases),
            "environments": [e.value for e in self.environments],
            "requires_approval_in_prod": self.requires_approval_in_prod,
            "dry_run_executes": self.dry_run_executes,
            "supersedes": self.supersedes,
            "notes": self.notes,
            "parameters": [
                {
                    "name": p.name,
                    "flag": p.cli_flag,
                    "type": p.type.value,
                    "help": p.help,
                    "required": p.required,
                    "default": p.default,
                    "choices": list(p.choices) if p.choices else None,
                }
                for p in self.parameters
            ],
        }


class Registry:
    """An ordered collection of utilities, keyed by id."""

    def __init__(self, utilities: Iterable[Utility] = ()) -> None:
        self._utilities: dict[str, Utility] = {}
        for utility in utilities:
            self.register(utility)

    def register(self, utility: Utility) -> Utility:
        existing = self._utilities.get(utility.id)
        if existing is not None:
            # Registering the identical descriptor again is a no-op, not an
            # error: a utility package registers on import *and* advertises an
            # entry point, so both paths can run in one process. Registering a
            # *different* utility under the same id is still refused — that is
            # two tools disagreeing about what an id means.
            if existing == utility:
                return existing
            raise Trd365Error(
                f'A different utility with id "{utility.id}" is already registered.'
            )
        unknown = set(utility.databases) - set(DB_KEYS)
        if unknown:
            raise Trd365Error(
                f'{utility.id} declares unknown database(s): {", ".join(sorted(unknown))}.'
            )
        self._utilities[utility.id] = utility
        return utility

    def get(self, utility_id: str) -> Utility:
        try:
            return self._utilities[utility_id]
        except KeyError:
            raise Trd365Error(f'No utility with id "{utility_id}".') from None

    def all(self) -> list[Utility]:
        return list(self._utilities.values())

    def destructive(self) -> list[Utility]:
        return [u for u in self._utilities.values() if u.is_destructive]

    def for_environment(self, env: Environment) -> list[Utility]:
        return [u for u in self._utilities.values() if env in u.environments]

    def to_dict(self) -> list[dict[str, Any]]:
        return [u.to_dict() for u in self._utilities.values()]

    def __len__(self) -> int:
        return len(self._utilities)

    def __contains__(self, utility_id: object) -> bool:
        return utility_id in self._utilities


#: The process-wide registry. Utility packages register themselves on import.
registry = Registry()


#: Installed packages advertise their utilities under this entry-point group.
UTILITY_ENTRY_POINT_GROUP = "trd365.utilities"


def load_installed_utilities(target: Registry | None = None) -> list[str]:
    """
    Register the utilities of every installed package that advertises them.

    The orchestrator serves whatever utility packages are installed alongside
    it, so it must not carry a hard-coded list of them — adding a utility should
    mean installing a package, not editing the service. Each package declares an
    entry point in ``trd365.utilities`` pointing at a ``register(registry)``
    callable.

    A package that fails to import is skipped and named in the return value
    rather than taking the service down with it: one broken utility should not
    stop the other nine from being runnable.
    """
    from importlib.metadata import entry_points

    into = registry if target is None else target
    loaded: list[str] = []

    for point in entry_points(group=UTILITY_ENTRY_POINT_GROUP):
        try:
            point.load()(into)
            loaded.append(point.name)
        except Exception as exc:  # noqa: BLE001 — reported, never fatal
            loaded.append(f"{point.name} FAILED: {type(exc).__name__}: {exc}")

    return loaded


# --------------------------------------------------------------------------
# Parameters shared by several utilities.
# --------------------------------------------------------------------------

ACCOUNT_ID = Parameter(
    "account_id", ParameterType.STRING, "Customer-facing account id (r_number)."
)
ACCOUNT_RID = Parameter("account_rid", ParameterType.STRING, "Internal account row id.")
CHUNK_SIZE = Parameter(
    "chunk_size", ParameterType.INTEGER, "Rows per delete batch.", default=1000
)
ORG_SCHEMA = Parameter(
    "org_schema", ParameterType.STRING, "Single org tenant schema, e.g. trd365_00042."
)
OUT_DIR = Parameter("out_dir", ParameterType.PATH, "Directory for generated reports.")
