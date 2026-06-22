class JarvisError(Exception):
    """Base class for all Jarvis-raised errors."""


class ToolNotFoundError(JarvisError):
    """Raised when a tool name is not registered."""


class PermissionDeniedError(JarvisError):
    """Raised when the calling user lacks permission for the requested operation."""


class InvalidArgumentError(JarvisError):
    """Raised when tool arguments fail validation."""


class ResultTooLargeError(InvalidArgumentError):
    """Raised when a row-dumping tool's result exceeds the guard threshold
    and the caller did not opt in with ``confirm_large=True``.

    Background: the 2026-06-22 customer outage on openai/gpt-5.5 traced to
    a single chat turn that accumulated 800+ row Timesheet Detail dumps
    and 776-row joined query results into the agent transcript. Openclaw
    tried to auto-compact and the upstream summarization call hit a
    transport error - the whole turn died. The slim-`get_schema` walk-back
    (PR #133) cut the schema side of the bloat; the row guard handles the
    other axis (query result size).

    The guard is per-call, not per-turn. It blocks the wasteful payload
    from ever reaching the transcript by raising at the bench layer, with
    a structured error the agent can act on. Three actions the agent
    can take (in priority order): narrow the filter, aggregate with
    GROUP BY / COUNT / SUM, or pass ``confirm_large=True`` for the rare
    workflows where every row IS the answer (audit exports, bulk
    reconciliation).

    Inherits from InvalidArgumentError so existing error envelopes route
    it the same way; the ``row_count`` / ``limit`` / ``tool`` attributes
    let downstream classifiers branch on it specifically if needed.
    """

    def __init__(self, row_count: int, limit: int, tool: str):
        self.row_count = row_count
        self.limit = limit
        self.tool = tool
        message = (
            f"{tool} returned {row_count} rows, which exceeds the "
            f"{limit}-row default. To resolve: (a) narrow the filter "
            f"to match fewer rows, (b) aggregate with GROUP BY / "
            f"COUNT / SUM if you need a summary, or (c) pass "
            f"confirm_large=True if you genuinely need every row "
            f"(rare; usually means export, not chat answer). The "
            f"{limit}-row limit exists because large row sets in the "
            f"agent transcript cause context-window failures."
        )
        super().__init__(message)


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
