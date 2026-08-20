"""
trd365-data-purge — entity purges across the three trd365 databases.

A purge is an entity-agnostic engine plus one module per entity:

``engine``      backup, chunked delete, FK deferral, and the post-run audit
``checkpoint``  resumable state, including id-sets captured before deletion
``reporting``   the text and JSON run reports
``cli``         shared argument conventions and the five-phase driver
``account``     the account manifest, scoping rules, and entry point

Every purge is a dry run unless given ``--apply``, backs rows up into the
``data_purge`` schema of the same database in the same transaction as the
delete, and leaves any table it cannot tie to the target completely untouched.
"""

# Imported for its side effect: importing this package registers its utilities
# with the shared catalogue, so the API and the UI list them without anyone
# having to know this package exists. Last, so the submodules above are bound
# before the registry module imports them back.
from . import registry as registry  # noqa: E402,F401  (side-effecting import)
from .checkpoint import Checkpoint, CheckpointStore
from .engine import BACKUP_SCHEMA, RunTag, SchemaCache, audit, run_steps
from .reporting import render_text, summarise, write_report

__version__ = "0.1.0"

__all__ = [
    "BACKUP_SCHEMA",
    "Checkpoint",
    "CheckpointStore",
    "RunTag",
    "SchemaCache",
    "__version__",
    "audit",
    "render_text",
    "run_steps",
    "summarise",
    "write_report",
]
