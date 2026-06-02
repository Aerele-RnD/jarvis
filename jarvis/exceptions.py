class JarvisError(Exception):
    """Base class for all Jarvis-raised errors."""


class ToolNotFoundError(JarvisError):
    """Raised when a tool name is not registered."""


class PermissionDeniedError(JarvisError):
    """Raised when the calling user lacks permission for the requested operation."""


class InvalidArgumentError(JarvisError):
    """Raised when tool arguments fail validation."""


class OpenclawUnreachableError(JarvisError):
    """Raised when the openclaw gateway can't be reached (WS handshake failed, container down)."""


class OpenclawReloadFailedError(JarvisError):
    """Raised when secrets.reload returned ok=false or timed out."""


class OpenclawRestartFailedError(JarvisError):
    """Raised when docker compose restart failed or the gateway didn't come back healthy."""


class AdminUnreachableError(JarvisError):
	"""HTTPS call to jarvis_admin failed (network, timeout, 5xx, non-JSON)."""


class AdminAuthError(JarvisError):
	"""jarvis_admin rejected the token / site (401 / 403)."""


class AdminValidationError(JarvisError):
	"""jarvis_admin raised a Frappe ValidationError (or similar user-input
	error) inside a whitelisted endpoint. Carries the clean operator-facing
	message - never the traceback dump."""


class AdminRateLimitedError(JarvisError):
	"""jarvis_admin returned HTTP 429 - caller should back off and retry later.

	``retry_after_seconds`` carries the body's hint when the admin provides
	one (0 if absent)."""

	def __init__(self, message: str = "rate_limited", retry_after_seconds: int = 0):
		super().__init__(message)
		self.retry_after_seconds = retry_after_seconds
