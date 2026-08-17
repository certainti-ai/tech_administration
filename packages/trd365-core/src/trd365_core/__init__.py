"""
trd365-core — shared foundation for the maintenance utilities.

Every utility builds on the same five pieces:

``environments``  the four environments and how their credentials resolve
``db``            connections, SSH tunnels, and reads that cannot hang
``datamodel``     the application data model every utility must know
``cli``           argument conventions, including the ``--apply`` safety rule
``audit``         append-only record of who ran what, where, and what changed
``registry``      the catalogue the API and UI are generated from
"""

from .audit import AuditedRun, JsonlAuditSink, MemoryAuditSink, RunRecord
from .cli import CommonArgs, build_parser, common_args, confirm_production, describe_mode
from .datamodel import (
    PRIMARY_ENTITIES,
    Entity,
    Reference,
    SchemaCatalog,
    entity,
    is_backup_table,
    is_polymorphic,
    load_catalog,
    references,
    resolve_parent_table,
    tenant_schemas,
)
from .db import ConnectionPool
from .environments import (
    DB_KEYS,
    ConnectionSettings,
    Environment,
    configuration_status,
    connection_settings,
    describe,
    is_configured,
)
from .errors import (
    ConfigError,
    DataModelError,
    PlaceholderCredentialError,
    Trd365Error,
    UnsafeOperationError,
)
from .registry import Impact, Parameter, ParameterType, Registry, Utility, registry

__version__ = "0.1.0"

__all__ = [
    "AuditedRun",
    "CommonArgs",
    "ConfigError",
    "ConnectionPool",
    "ConnectionSettings",
    "DB_KEYS",
    "DataModelError",
    "Entity",
    "Environment",
    "Impact",
    "JsonlAuditSink",
    "MemoryAuditSink",
    "PRIMARY_ENTITIES",
    "Parameter",
    "ParameterType",
    "PlaceholderCredentialError",
    "Reference",
    "Registry",
    "RunRecord",
    "SchemaCatalog",
    "Trd365Error",
    "UnsafeOperationError",
    "Utility",
    "__version__",
    "build_parser",
    "common_args",
    "configuration_status",
    "confirm_production",
    "connection_settings",
    "describe",
    "describe_mode",
    "entity",
    "is_backup_table",
    "is_configured",
    "is_polymorphic",
    "load_catalog",
    "references",
    "registry",
    "resolve_parent_table",
    "tenant_schemas",
]
