"""MCP streamable-http endpoint exposed at jarvis.mcp.serve.

Openclaw's embedded Pi agent calls this endpoint to discover and invoke Jarvis tools.
Auth is a shared bearer token (the same one in Jarvis Settings.openclaw_gateway_token).
Per-user identity arrives in the tool-call `arguments` as `_user`, injected by the
jarvis-openclaw-plugin's before_tool_call hook on the openclaw side.

Bearer validates the call came from our openclaw. `_user` identifies which Frappe user
the call is being made on behalf of. Tool execution runs under that user's permissions
via frappe.set_user.

Protocol: MCP streamable-http, protocolVersion 2025-11-25 (verified from spike trace).
"""

import hmac
import json

import frappe

from jarvis.exceptions import (
    InvalidArgumentError,
    JarvisError,
    PermissionDeniedError,
    ToolNotFoundError,
)
from jarvis.tools.registry import dispatch, list_tools


# JSON-RPC error codes (subset of standard MCP/JSON-RPC)
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

# Custom application-level error codes
_PERMISSION_DENIED_CODE = -32001

# Map our JarvisError subclasses to MCP-friendly error codes
_ERROR_CODE_MAP = {
    "ToolNotFoundError": JSONRPC_METHOD_NOT_FOUND,
    "InvalidArgumentError": JSONRPC_INVALID_PARAMS,
    "PermissionDeniedError": _PERMISSION_DENIED_CODE,
}

# MCP protocol version — confirmed from spike trace (openclaw sends 2025-11-25)
_PROTOCOL_VERSION = "2025-11-25"

# Tool schemas advertised in tools/list. Openclaw will namespace these as
# "jarvis__<name>" on its side (because the MCP server is registered as "jarvis"),
# but we advertise them unprefixed here.
_TOOL_SCHEMAS = [
    {
        "name": "get_schema",
        "description": (
            "Return a DocType's field list with child tables expanded inline. "
            "Useful before querying an unfamiliar DocType."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "Frappe DocType name, e.g. 'Customer', 'Sales Invoice'",
                },
                "_user": {
                    "type": "string",
                    "description": (
                        "Calling user's email — auto-injected by openclaw plugin; "
                        "do not set manually"
                    ),
                },
            },
            "required": ["doctype"],
        },
    },
    {
        "name": "get_doc",
        "description": (
            "Return a single document by DocType and name. "
            "Includes default fields like creation, owner, modified."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "doctype": {"type": "string"},
                "name": {
                    "type": "string",
                    "description": "Document name (primary key)",
                },
                "_user": {"type": "string", "description": "Auto-injected"},
            },
            "required": ["doctype", "name"],
        },
    },
    {
        "name": "get_list",
        "description": (
            "Filtered list of documents. Hard cap of 1000 results. "
            "Frappe permissions apply per-record."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "doctype": {"type": "string"},
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Field names to return (default: ['name'])",
                },
                "filters": {
                    "type": "object",
                    "description": "Frappe filter dict",
                },
                "order_by": {"type": "string"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "default": 20,
                },
                "_user": {"type": "string", "description": "Auto-injected"},
            },
            "required": ["doctype"],
        },
    },
    {
        "name": "run_report",
        "description": (
            "Execute a saved Frappe Report (Report Builder, Query, or Script report) "
            "by name."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_name": {"type": "string"},
                "filters": {"type": "object"},
                "_user": {"type": "string", "description": "Auto-injected"},
            },
            "required": ["report_name"],
        },
    },
]


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def serve():
    """MCP streamable-http endpoint.

    Handles the five protocol messages openclaw uses during a tool-using session:
      POST initialize        — protocol handshake
      POST notifications/*   — client notifications (no response)
      GET  (no body)         — SSE subscription (we return empty stream)
      POST tools/list        — tool discovery
      POST tools/call        — tool invocation
    """
    if not _validate_bearer():
        frappe.local.response.http_status_code = 401
        return {"error": "unauthorized"}

    if frappe.request.method == "GET":
        return _empty_sse_response()

    if frappe.request.method != "POST":
        frappe.local.response.http_status_code = 405
        return {"error": "method not allowed"}

    try:
        body = frappe.request.get_json(force=True)
    except Exception:
        return _jsonrpc_error(None, JSONRPC_PARSE_ERROR, "invalid JSON")

    if not isinstance(body, dict):
        return _jsonrpc_error(None, JSONRPC_INVALID_REQUEST, "body must be a JSON object")

    method = body.get("method")
    msg_id = body.get("id")  # None for notifications (they have no id)

    if method == "initialize":
        return _handle_initialize(msg_id)

    if method is not None and method.startswith("notifications/"):
        # Notifications require no response — return empty dict; Frappe will
        # serialise it as `{}` which openclaw safely ignores.
        return {}

    if method == "tools/list":
        return _handle_tools_list(msg_id)

    if method == "tools/call":
        return _handle_tools_call(body, msg_id)

    return _jsonrpc_error(msg_id, JSONRPC_METHOD_NOT_FOUND, f"unknown method: {method}")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _validate_bearer() -> bool:
    """Return True iff the Authorization header contains the correct gateway token."""
    header = frappe.request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return False
    presented = header[len("Bearer "):].strip()
    if not presented:
        return False
    settings = frappe.get_single("Jarvis Settings")
    expected = settings.get_password("openclaw_gateway_token") or ""
    if not expected:
        return False
    # Constant-time comparison to prevent timing-oracle attacks
    return hmac.compare_digest(presented, expected)


# ---------------------------------------------------------------------------
# SSE stub
# ---------------------------------------------------------------------------

def _empty_sse_response():
    """Return a minimal SSE response.

    Openclaw opens a GET /mcp subscription immediately after
    notifications/initialized. We don't push events, but we must respond
    cleanly so the client doesn't error. Frappe's response layer doesn't
    support true streaming SSE, so we return an HTTP 200 with
    Content-Type text/event-stream and an empty body. Openclaw tolerates
    an empty SSE stream — it only uses this channel for server-push events
    which we never generate.
    """
    frappe.local.response.http_status_code = 200
    # Frappe serialises whitelist return values as JSON by default.
    # Switch to a raw response to emit plain text instead.
    frappe.local.response["type"] = "binary"
    frappe.local.response["filename"] = None
    frappe.local.response["filecontent"] = b""
    frappe.local.response["content_type"] = "text/event-stream"
    return None


# ---------------------------------------------------------------------------
# Protocol handlers
# ---------------------------------------------------------------------------

def _handle_initialize(msg_id) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": "jarvis-frappe",
                "version": "0.1.0",
            },
        },
    }


def _handle_tools_list(msg_id) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {"tools": _TOOL_SCHEMAS},
    }


def _handle_tools_call(body: dict, msg_id) -> dict:
    params = body.get("params") or {}
    tool_name = params.get("name")
    arguments = dict(params.get("arguments") or {})

    if not tool_name:
        return _jsonrpc_error(msg_id, JSONRPC_INVALID_PARAMS, "missing tool name")

    # Extract _user — injected by the jarvis-openclaw-plugin before_tool_call hook
    user = arguments.pop("_user", None)
    if not user or not isinstance(user, str):
        return _jsonrpc_error(
            msg_id,
            JSONRPC_INVALID_PARAMS,
            "missing or invalid _user (must be injected by jarvis-openclaw-plugin hook)",
        )

    if not frappe.db.exists("User", user):
        return _jsonrpc_error(
            msg_id, JSONRPC_INVALID_PARAMS, f"unknown user: {user}"
        )

    original_user = frappe.session.user
    try:
        frappe.set_user(user)
        try:
            result_data = dispatch(tool_name, arguments)
        except JarvisError as exc:
            code = _ERROR_CODE_MAP.get(type(exc).__name__, JSONRPC_INTERNAL_ERROR)
            return _jsonrpc_error(
                msg_id, code, str(exc), error_type=type(exc).__name__
            )
        except frappe.PermissionError as exc:
            return _jsonrpc_error(
                msg_id,
                _PERMISSION_DENIED_CODE,
                str(exc) or "permission denied",
                error_type="PermissionDeniedError",
            )
    finally:
        frappe.set_user(original_user)

    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "content": [
                {"type": "text", "text": json.dumps(result_data, default=str)},
            ],
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jsonrpc_error(
    msg_id, code: int, message: str, error_type: str | None = None
) -> dict:
    err: dict = {"code": code, "message": message}
    if error_type:
        err["data"] = {"type": error_type}
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": err,
    }
