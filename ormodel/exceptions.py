class ORModelError(Exception):
    """Base exception for ormodel library."""

    pass


class DoesNotExist(ORModelError):
    """Raised when a query expects one result but finds none."""

    pass


class MultipleObjectsReturned(ORModelError):
    """Raised when a query expects one result but finds multiple."""

    pass


class ConfigError(ORModelError):
    """Raised for configuration-related errors."""

    pass


class SessionContextError(ORModelError):
    """Raised when a database session is required but not found in the context."""

    pass
