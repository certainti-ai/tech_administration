"""Shared test doubles and utility descriptors."""

import asyncio

from trd365_core.registry import Impact, Parameter, ParameterType, Utility

from trd365_orchestrator.security import Principal

PURGE = Utility(
    id="purge-account",
    title="Purge account",
    description="Remove an account and everything beneath it.",
    module="trd365_data_purge.account",
    impact=Impact.DESTRUCTIVE,
    databases=("maindb", "orgdb"),
    parameters=(
        Parameter("account_rid", ParameterType.STRING, "Account row id", required=True),
        Parameter("chunk_size", ParameterType.INTEGER, "Batch size", default=1000),
        Parameter("verbose", ParameterType.BOOLEAN, "Verbose"),
    ),
)

REPORT = Utility(
    id="orphan-report",
    title="Orphan report",
    description="Count orphaned rows per tenant schema.",
    module="trd365_data_model_analysis.orphans",
    impact=Impact.READ_ONLY,
    databases=("orgdb",),
    parameters=(Parameter("org_schema", ParameterType.STRING, "Tenant schema"),),
)


def principal(name="alice", *roles):
    return Principal(subject=name, display_name=name, roles=frozenset(roles))


class ScriptedRunner:
    """Runner that returns a chosen exit code, optionally after a barrier."""

    def __init__(self, exit_code=0, output=(), block: asyncio.Event | None = None):
        self.exit_code = exit_code
        self.output = list(output)
        self.block = block
        self.calls: list[list[str]] = []
        self.started = asyncio.Event()

    async def run(self, argv, on_output, cancel):
        self.calls.append(argv)
        self.started.set()
        for line in self.output:
            on_output(line)
        if self.block is not None:
            waiter = asyncio.create_task(self.block.wait())
            canceller = asyncio.create_task(cancel.wait())
            _done, pending = await asyncio.wait(
                {waiter, canceller}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
        return self.exit_code
