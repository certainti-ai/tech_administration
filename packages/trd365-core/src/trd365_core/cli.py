"""
Shared command-line conventions.

Three rules, applied identically by every utility:

1. ``--env`` is required and has no default. The cost of a wrong default here
   is destroying the wrong database.
2. Writes happen only with ``--apply``. Without it a utility performs a dry run
   and reports what it *would* change.
3. ``--dry-run`` is a hard error, not a silent no-op.

Rule 3 exists because three of the original tools — including account deletion
and fiscal-year deletion — wrote **by default** and used ``--dry-run`` to
preview. Reversing that is right, but an operator with the old habit would
otherwise type ``--dry-run`` and have it ignored as an unknown flag while the
tool deleted for real. Failing loudly is the only safe way to make this change.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .environments import Environment
from .errors import UnsafeOperationError


class _RejectDryRun(argparse.Action):
    """Turn the removed ``--dry-run`` flag into an explanation, never a no-op."""

    def __call__(self, parser, namespace, values, option_string=None):  # noqa: ANN001
        parser.error(
            "--dry-run has been removed.\n\n"
            "Dry run is now the default: run the command with no extra flag to preview, "
            "and add --apply when you want the changes written.\n\n"
            "This changed because some tools previously wrote by default, which made "
            "forgetting a flag destructive. If you typed --dry-run out of habit, drop it "
            "and the command does what you intended."
        )


@dataclass(frozen=True)
class CommonArgs:
    """The arguments every utility shares, after parsing."""

    env: Environment
    apply: bool
    verbose: bool
    actor: str | None
    #: The interactive production confirmation was answered out of band.
    assume_yes: bool = False

    @property
    def dry_run(self) -> bool:
        return not self.apply

    @property
    def mode(self) -> str:
        return "APPLY" if self.apply else "DRY RUN"


def build_parser(
    description: str,
    *,
    destructive: bool = True,
    parents: Sequence[argparse.ArgumentParser] = (),
) -> argparse.ArgumentParser:
    """
    An argument parser carrying the shared conventions.

    ``destructive=False`` omits ``--apply`` for read-only utilities, so a
    reporting tool cannot advertise a flag that would do nothing.
    """
    parser = argparse.ArgumentParser(
        description=description,
        parents=list(parents),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env",
        required=True,
        choices=[e.value for e in Environment],
        help="Target environment. Required — there is deliberately no default.",
    )
    if destructive:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes. Omit for a dry run that reports what would change.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help=(
                "Skip the interactive production confirmation. For callers with no "
                "terminal — the orchestrator, which enforces a second approver instead."
            ),
        )
    parser.add_argument(
        "--dry-run",
        nargs=0,
        action=_RejectDryRun,
        help=argparse.SUPPRESS,  # accepted only so it can be explained, not advertised
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output.")
    parser.add_argument(
        "--actor",
        default=None,
        help="Who is running this, for the audit record. Defaults to the OS user.",
    )
    return parser


def common_args(namespace: argparse.Namespace) -> CommonArgs:
    return CommonArgs(
        env=Environment.parse(namespace.env),
        apply=bool(getattr(namespace, "apply", False)),
        verbose=bool(getattr(namespace, "verbose", False)),
        actor=getattr(namespace, "actor", None),
        assume_yes=bool(getattr(namespace, "yes", False)),
    )


def confirm_production(
    args: CommonArgs,
    utility: str,
    *,
    stream=None,
    input_fn=None,
    assume_yes: bool | None = None,
    isatty: Callable[[], bool] | None = None,
) -> None:
    """
    Require a typed confirmation before writing to production from a terminal.

    This is the CLI's backstop only. The web application enforces the real
    control — a second approver (PRD FR-4.3) — because a confirmation prompt
    stops accidents, not intent.

    Without a terminal this refuses rather than prompting. A subprocess started
    by the orchestrator has no stdin to read, and prompting there would hang the
    job forever with no indication of why; the orchestrator passes ``--yes``
    because it has already taken a second approval.
    """
    if not args.apply or not args.env.is_production:
        return
    if args.assume_yes if assume_yes is None else assume_yes:
        return

    at_terminal = isatty if isatty is not None else sys.stdin.isatty
    if not at_terminal():
        raise UnsafeOperationError(
            f"{utility} will not write to production without a confirmation, and there is "
            f"no terminal to ask at.\n"
            f"Run it interactively, or pass --yes if the approval was taken elsewhere."
        )

    # Both resolved here rather than as default arguments: a default binds at
    # import time, which breaks redirection, output capture, and any caller that
    # replaces the built-in to drive this non-interactively.
    stream = sys.stderr if stream is None else stream
    input_fn = input if input_fn is None else input_fn
    print(
        f"\n*** {utility} is about to WRITE TO PRODUCTION ***\n"
        f"Type the environment name to continue, anything else to abort.",
        file=stream,
    )
    if input_fn("environment> ").strip().lower() != Environment.PROD.value:
        raise UnsafeOperationError("Production confirmation failed; nothing was written.")


def describe_mode(args: CommonArgs, utility: str) -> str:
    """One-line banner every utility prints before doing anything."""
    suffix = "" if args.apply else "  (no changes will be written)"
    return f"{utility} | env={args.env.value} | {args.mode}{suffix}"
