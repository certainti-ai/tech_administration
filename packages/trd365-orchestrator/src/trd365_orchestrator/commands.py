"""
Turning a job into a command line.

The registry descriptor is the whitelist: an argument the utility did not
declare is rejected rather than passed through. Without that, the API would let
a caller append arbitrary flags to a command that can delete production data.
"""

from __future__ import annotations

import sys
from typing import Any

from trd365_core.environments import Environment
from trd365_core.errors import Trd365Error
from trd365_core.registry import ParameterType, Utility


class InvalidArguments(Trd365Error):
    """Arguments do not match what the utility declares."""


def _coerce(name: str, value: Any, expected: ParameterType) -> str:
    if expected is ParameterType.INTEGER:
        try:
            return str(int(value))
        except (TypeError, ValueError):
            raise InvalidArguments(f'"{name}" must be an integer, got {value!r}.') from None

    if expected is ParameterType.BOOLEAN:
        raise InvalidArguments(f'"{name}" is a flag and is handled separately.')

    text = str(value)
    if "\x00" in text or "\n" in text:
        raise InvalidArguments(f'"{name}" may not contain newlines or null bytes.')
    return text


def build_argv(
    utility: Utility,
    environment: Environment,
    arguments: dict[str, Any],
    *,
    apply: bool,
    python: str | None = None,
) -> list[str]:
    """
    Build the command line for a run.

    ``--env`` is always passed, and ``--apply`` only when the run is meant to
    write — the utility's own default remains the dry run, so a bug here fails
    safe rather than destructively.
    """
    declared = {p.name: p for p in utility.parameters}

    unknown = sorted(set(arguments) - set(declared))
    if unknown:
        raise InvalidArguments(
            f"{utility.id} does not accept: {', '.join(unknown)}. "
            f"Declared parameters: {', '.join(sorted(declared)) or '(none)'}."
        )

    missing = sorted(
        name for name, p in declared.items() if p.required and arguments.get(name) in (None, "")
    )
    if missing:
        raise InvalidArguments(f"{utility.id} requires: {', '.join(missing)}.")

    argv = [python or sys.executable, "-m", utility.module, "--env", environment.value]

    if apply and environment.is_production:
        # The utility's own terminal confirmation cannot be answered from a
        # subprocess. The service has already required a second approver
        # (FR-4.3), which is the stronger control the prompt stands in for.
        argv.append("--yes")

    for name in sorted(arguments):
        parameter = declared[name]
        value = arguments[name]
        if value is None or value == "":
            continue

        if parameter.type is ParameterType.BOOLEAN:
            if value:
                argv.append(parameter.cli_flag)
            continue

        if parameter.choices and str(value) not in parameter.choices:
            raise InvalidArguments(
                f'"{name}" must be one of: {", ".join(parameter.choices)}; got {value!r}.'
            )

        argv.extend([parameter.cli_flag, _coerce(name, value, parameter.type)])

    if apply:
        if not utility.impact.needs_apply:
            raise InvalidArguments(f"{utility.id} is read-only and cannot be run with --apply.")
        argv.append("--apply")

    return argv


def redacted_command(argv: list[str]) -> str:
    """A form of the command safe to show in the UI and the audit record."""
    return " ".join(argv)
