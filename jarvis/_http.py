"""Shared HTTP helpers for Jarvis whitelisted endpoints.

Provides _validate_bearer() and _raw_json_response() so that both mcp.py
and api.py can share the same auth logic and raw-response behaviour without
duplication.
"""

import hmac
import json

import frappe
from werkzeug.wrappers import Response as WerkzeugResponse


def validate_bearer() -> bool:
    """Return True iff the X-Jarvis-Token header contains the correct agent token.

    We use a custom header rather than ``Authorization: Bearer`` so that Frappe's
    built-in OAuth validator (which runs before our handler) does not see a Bearer
    token it cannot resolve and raise AuthenticationError prematurely.
    """
    presented = frappe.request.headers.get("X-Jarvis-Token", "").strip()
    if not presented:
        return False
    settings = frappe.get_single("Jarvis Settings")
    expected = settings.get_password("agent_token") or ""
    if not expected:
        return False
    # Constant-time comparison to prevent timing-oracle attacks
    return hmac.compare_digest(presented, expected)


def raw_json_response(data: dict, status_code: int = 200) -> WerkzeugResponse:
    """Return ``data`` as a raw JSON Werkzeug response, bypassing Frappe's wrapper.

    Frappe's ``@frappe.whitelist`` normally wraps return values in
    ``{"message": <value>}``.  The MCP SDK validates the raw JSON-RPC envelope
    and rejects the wrapper.  Returning a werkzeug ``Response`` object directly
    from a whitelist function causes Frappe's API handler to pass it through
    unchanged (see ``frappe.api.handle``: ``if isinstance(data, Response): return data``).
    """
    resp = WerkzeugResponse(
        response=json.dumps(data),
        status=status_code,
        content_type="application/json",
    )
    return resp
