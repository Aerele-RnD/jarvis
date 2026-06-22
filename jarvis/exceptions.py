class JarvisError(Exception):
    """Base class for all Jarvis-raised errors."""


class ToolNotFoundError(JarvisError):
    """Raised when a tool name is not registered."""


class PermissionDeniedError(JarvisError):
    """Raised when the calling user lacks permission for the requested operation."""


class InvalidArgumentError(JarvisError):
    """Raised when tool arguments fail validation."""


class OpenclawUnreachableError(JarvisError):
    """Raised when the openclaw gateway can't be reached (WS handshake
    failed, container down).

    Sprint-3 (2026-06-16 review): may carry a structured ``code`` taken
    from openclaw's rejection payload (``device-not-paired``,
    ``token-mismatch``, ``signature-invalid``, etc.). Downstream
    classifiers (e.g. _is_stale_pairing) should branch on this
    attribute, not on a substring match of the message. ``code`` is
    None when the error didn't originate from an openclaw response
    (e.g. network-level WS open failure)."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


class OpenclawReloadFailedError(JarvisError):
    """Raised when secrets.reload returned ok=false or timed out."""


class AdminUnreachableError(JarvisError):
	"""HTTPS call to jarvis_admin failed (network, timeout, 5xx, non-JSON)."""


class AdminAuthError(JarvisError):
	"""jarvis_admin rejected the token / site (401 / 403).

	``status_code`` carries the rejecting HTTP status (401 or 403) when known.
	The bench uses it to tell a *token* rejection (401 - revoked or raced past
	the ~15min cap; re-minting and retrying helps) apart from an
	*authorization* denial (403 - the same customer principal backs both the
	bearer and the legacy api_key:api_secret, so re-minting and the legacy
	fallback would just replay into the same 403 while storming the token
	endpoint). None when the status isn't known."""

	def __init__(self, message: str, *, status_code: int | None = None):
		super().__init__(message)
		self.status_code = status_code


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
