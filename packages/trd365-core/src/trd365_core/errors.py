"""Exception types shared across every maintenance utility."""


class Trd365Error(Exception):
    """Base for everything this package raises."""


class ConfigError(Trd365Error):
    """Configuration is missing, malformed, or still a placeholder."""


class PlaceholderCredentialError(ConfigError):
    """
    An environment was selected whose credentials have not been supplied yet.

    Raised instead of attempting a connection, so a half-configured environment
    fails immediately and unmistakably rather than timing out, or worse,
    resolving somewhere unintended.
    """


class UnsafeOperationError(Trd365Error):
    """A destructive operation was attempted without the required authorisation."""


class DataModelError(Trd365Error):
    """The database does not match the data model conventions this code assumes."""
