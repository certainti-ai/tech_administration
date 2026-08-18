"""
trd365-orchestrator — running the maintenance utilities safely.

    jobs        the record of what was asked for and what happened
    scheduler   execution, one writer per environment at a time
    runner      subprocess execution with cancellation that allows rollback
    commands    registry-checked command-line construction
    security    roles, per-environment authorisation, second-approver rule
    service     the use cases, independent of HTTP
    health      per-environment connectivity and model freshness
    api / app   the HTTP surface
"""

from .app import create_app
from .commands import InvalidArguments, build_argv
from .health import EnvironmentHealth, environment_health
from .jobs import Job, JobState, JobStore, new_job
from .runner import CallableRunner, SubprocessRunner
from .scheduler import Scheduler
from .security import ANONYMOUS, AuthorizationError, Principal, Role, requires_approval
from .service import Orchestrator, OrchestratorConfig

__version__ = "0.1.0"

__all__ = [
    "ANONYMOUS",
    "AuthorizationError",
    "CallableRunner",
    "EnvironmentHealth",
    "InvalidArguments",
    "Job",
    "JobState",
    "JobStore",
    "Orchestrator",
    "OrchestratorConfig",
    "Principal",
    "Role",
    "Scheduler",
    "SubprocessRunner",
    "__version__",
    "build_argv",
    "create_app",
    "environment_health",
    "new_job",
    "requires_approval",
]
