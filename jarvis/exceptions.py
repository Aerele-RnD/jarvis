class JarvisError(Exception):
    """Base class for all Jarvis-raised errors."""


class ToolNotFoundError(JarvisError):
    """Raised when a tool name is not registered."""


class PermissionDeniedError(JarvisError):
    """Raised when the calling user lacks permission for the requested operation."""


class InvalidArgumentError(JarvisError):
    """Raised when tool arguments fail validation."""
