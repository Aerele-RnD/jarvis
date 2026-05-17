"""Tests for the MCP streamable-http endpoint (jarvis.mcp).

Strategy: we test the internal handler functions directly wherever possible
(_handle_initialize, _handle_tools_list, _handle_tools_call, _validate_bearer,
_jsonrpc_error). For serve() we use a lightweight frappe.request mock so we
don't need a live Werkzeug WSGI stack.
"""

import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.mcp import (
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_PARAMS,
    JSONRPC_METHOD_NOT_FOUND,
    _PERMISSION_DENIED_CODE,
    _PROTOCOL_VERSION,
    _TOOL_SCHEMAS,
    _handle_initialize,
    _handle_tools_call,
    _handle_tools_list,
    _jsonrpc_error,
    _validate_bearer,
    serve,
)

_TOKEN = "test-mcp-gateway-secret-xyz"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_token(token: str):
    """Write openclaw_gateway_token into Jarvis Settings via db_set."""
    settings = frappe.get_single("Jarvis Settings")
    settings.db_set("openclaw_gateway_token", token)
    frappe.db.commit()


def _clear_token():
    settings = frappe.get_single("Jarvis Settings")
    settings.db_set("openclaw_gateway_token", "")
    frappe.db.commit()


def _make_request(
    method: str = "POST",
    headers: dict | None = None,
    json_body: dict | None = None,
):
    """Build a minimal request stub accepted by serve() and _validate_bearer()."""
    req = MagicMock()
    req.method = method
    req.headers = headers or {}
    if json_body is not None:
        req.get_json = MagicMock(return_value=json_body)
    else:
        req.get_json = MagicMock(return_value=None)
    return req


def _auth_headers(token: str = _TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Test: Bearer auth via _validate_bearer()
# ---------------------------------------------------------------------------


class TestValidateBearer(FrappeTestCase):
    def setUp(self):
        super().setUp()
        _set_token(_TOKEN)

    def tearDown(self):
        super().tearDown()
        _clear_token()

    def test_correct_token_returns_true(self):
        req = _make_request(headers=_auth_headers(_TOKEN))
        with patch("jarvis.mcp.frappe") as mock_frappe:
            # We need the real frappe.get_single, frappe.db — patch only the request
            pass
        # Use real frappe — just patch frappe.request
        with patch("frappe.request", _make_request(headers=_auth_headers(_TOKEN))):
            result = _validate_bearer()
        self.assertTrue(result)

    def test_wrong_token_returns_false(self):
        with patch("frappe.request", _make_request(headers=_auth_headers("wrong-token"))):
            result = _validate_bearer()
        self.assertFalse(result)

    def test_missing_authorization_header_returns_false(self):
        with patch("frappe.request", _make_request(headers={})):
            result = _validate_bearer()
        self.assertFalse(result)

    def test_empty_token_in_settings_returns_false(self):
        _clear_token()
        with patch("frappe.request", _make_request(headers=_auth_headers(_TOKEN))):
            result = _validate_bearer()
        self.assertFalse(result)

    def test_non_bearer_scheme_returns_false(self):
        with patch("frappe.request", _make_request(headers={"Authorization": "Basic dXNlcjpwYXNz"})):
            result = _validate_bearer()
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# Test: serve() — HTTP-level routing (auth + method dispatch)
# ---------------------------------------------------------------------------


class TestServeAuth(FrappeTestCase):
    def setUp(self):
        super().setUp()
        _set_token(_TOKEN)

    def tearDown(self):
        super().tearDown()
        _clear_token()

    def test_wrong_token_returns_401_error(self):
        req = _make_request(
            headers=_auth_headers("totally-wrong"),
            json_body={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        with patch("frappe.request", req):
            result = serve()
        # After serve() sets the status code via frappe.local.response, read it back
        self.assertEqual(frappe.local.response.http_status_code, 401)
        self.assertEqual(result, {"error": "unauthorized"})

    def test_missing_auth_returns_401(self):
        req = _make_request(
            headers={},
            json_body={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        with patch("frappe.request", req):
            result = serve()
        self.assertEqual(frappe.local.response.http_status_code, 401)
        self.assertEqual(result, {"error": "unauthorized"})


# ---------------------------------------------------------------------------
# Test: initialize
# ---------------------------------------------------------------------------


class TestHandleInitialize(FrappeTestCase):
    def test_returns_protocol_version(self):
        result = _handle_initialize(msg_id=0)
        self.assertEqual(result["jsonrpc"], "2.0")
        self.assertEqual(result["id"], 0)
        self.assertEqual(result["result"]["protocolVersion"], _PROTOCOL_VERSION)

    def test_protocol_version_matches_spike(self):
        # Confirmed from scratch/mcp-server.log: openclaw sends 2025-11-25
        self.assertEqual(_PROTOCOL_VERSION, "2025-11-25")

    def test_returns_capabilities_with_tools(self):
        result = _handle_initialize(msg_id=1)
        caps = result["result"]["capabilities"]
        self.assertIn("tools", caps)

    def test_returns_server_info(self):
        result = _handle_initialize(msg_id=2)
        info = result["result"]["serverInfo"]
        self.assertEqual(info["name"], "jarvis-frappe")
        self.assertIn("version", info)

    def test_initialize_via_serve(self):
        """End-to-end: serve() routes initialize POST correctly."""
        _set_token(_TOKEN)
        body = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.0.0"},
            },
        }
        req = _make_request(headers=_auth_headers(_TOKEN), json_body=body)
        with patch("frappe.request", req):
            result = serve()
        _clear_token()
        self.assertIn("result", result)
        self.assertEqual(result["result"]["protocolVersion"], "2025-11-25")


# ---------------------------------------------------------------------------
# Test: notifications/initialized (and other notifications)
# ---------------------------------------------------------------------------


class TestNotifications(FrappeTestCase):
    def test_notifications_initialized_returns_empty_dict(self):
        """notifications/initialized is a notification — server must not reply."""
        _set_token(_TOKEN)
        body = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        req = _make_request(headers=_auth_headers(_TOKEN), json_body=body)
        with patch("frappe.request", req):
            result = serve()
        _clear_token()
        self.assertEqual(result, {})

    def test_notifications_have_no_id(self):
        """Confirmed from spike log: notifications/initialized has no id field."""
        body = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self.assertNotIn("id", body)


# ---------------------------------------------------------------------------
# Test: tools/list
# ---------------------------------------------------------------------------


class TestHandleToolsList(FrappeTestCase):
    def test_returns_four_tools(self):
        result = _handle_tools_list(msg_id=1)
        tools = result["result"]["tools"]
        self.assertEqual(len(tools), 4)

    def test_returns_expected_tool_names(self):
        result = _handle_tools_list(msg_id=1)
        names = {t["name"] for t in result["result"]["tools"]}
        self.assertEqual(names, {"get_schema", "get_doc", "get_list", "run_report"})

    def test_each_tool_has_input_schema(self):
        result = _handle_tools_list(msg_id=1)
        for tool in result["result"]["tools"]:
            self.assertIn("inputSchema", tool, f"{tool['name']} missing inputSchema")
            self.assertIn("description", tool, f"{tool['name']} missing description")

    def test_tools_list_via_serve(self):
        """End-to-end: serve() routes tools/list POST correctly."""
        _set_token(_TOKEN)
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        req = _make_request(headers=_auth_headers(_TOKEN), json_body=body)
        with patch("frappe.request", req):
            result = serve()
        _clear_token()
        self.assertIn("result", result)
        self.assertEqual(len(result["result"]["tools"]), 4)


# ---------------------------------------------------------------------------
# Test: tools/call — happy path
# ---------------------------------------------------------------------------


class TestHandleToolsCallHappy(FrappeTestCase):
    def test_get_schema_returns_content_text(self):
        """Happy path: tools/call get_schema as Administrator returns MCP content."""
        body = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "get_schema",
                "arguments": {
                    "doctype": "Customer",
                    "_user": "Administrator",
                },
            },
        }
        result = _handle_tools_call(body, msg_id=3)
        self.assertEqual(result["jsonrpc"], "2.0")
        self.assertEqual(result["id"], 3)
        self.assertIn("result", result)
        content = result["result"]["content"]
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["type"], "text")
        # The text should be JSON-serialised tool output
        data = json.loads(content[0]["text"])
        self.assertEqual(data["doctype"], "Customer")
        self.assertIn("fields", data)

    def test_runs_as_specified_user(self):
        """_user in arguments sets the execution context to that Frappe user."""
        # We use Administrator which always has access
        body = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "get_schema",
                "arguments": {
                    "doctype": "Customer",
                    "_user": "Administrator",
                },
            },
        }
        result = _handle_tools_call(body, msg_id=4)
        self.assertNotIn("error", result)
        self.assertIn("result", result)

    def test_original_user_is_restored_after_call(self):
        """frappe.session.user must be restored to the original after tool call."""
        original = frappe.session.user
        body = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "get_schema",
                "arguments": {
                    "doctype": "Customer",
                    "_user": "Administrator",
                },
            },
        }
        _handle_tools_call(body, msg_id=5)
        self.assertEqual(frappe.session.user, original)


# ---------------------------------------------------------------------------
# Test: tools/call — error cases
# ---------------------------------------------------------------------------


class TestHandleToolsCallErrors(FrappeTestCase):
    def test_missing_user_returns_invalid_params(self):
        """_user not present → JSONRPC_INVALID_PARAMS."""
        body = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "get_schema",
                "arguments": {"doctype": "Customer"},
            },
        }
        result = _handle_tools_call(body, msg_id=10)
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], JSONRPC_INVALID_PARAMS)

    def test_empty_user_returns_invalid_params(self):
        body = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "get_schema",
                "arguments": {"doctype": "Customer", "_user": ""},
            },
        }
        result = _handle_tools_call(body, msg_id=11)
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], JSONRPC_INVALID_PARAMS)

    def test_unknown_user_returns_invalid_params(self):
        """User that does not exist in Frappe → JSONRPC_INVALID_PARAMS."""
        body = {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "get_schema",
                "arguments": {
                    "doctype": "Customer",
                    "_user": "definitely-not-a-real-user@example.com",
                },
            },
        }
        result = _handle_tools_call(body, msg_id=12)
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], JSONRPC_INVALID_PARAMS)
        self.assertIn("unknown user", result["error"]["message"])

    def test_unknown_tool_returns_method_not_found(self):
        """Tool name not in registry → JSONRPC_METHOD_NOT_FOUND."""
        body = {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "not_a_real_tool",
                "arguments": {"_user": "Administrator"},
            },
        }
        result = _handle_tools_call(body, msg_id=13)
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], JSONRPC_METHOD_NOT_FOUND)
        self.assertEqual(result["error"]["data"]["type"], "ToolNotFoundError")

    def test_permission_denied_for_low_perm_user(self):
        """Low-permission user trying get_doc on Customer → permission denied error."""
        user_email = "mcp-lowperm@example.com"
        if not frappe.db.exists("User", user_email):
            frappe.get_doc({
                "doctype": "User",
                "email": user_email,
                "first_name": "MCP LowPerm",
                "send_welcome_email": 0,
            }).insert(ignore_permissions=True)

        # get_schema is what fails for no-role users based on PermissionDeniedError
        body = {
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {
                "name": "get_schema",
                "arguments": {
                    "doctype": "Customer",
                    "_user": user_email,
                },
            },
        }
        result = _handle_tools_call(body, msg_id=14)
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], _PERMISSION_DENIED_CODE)
        self.assertEqual(result["error"]["data"]["type"], "PermissionDeniedError")

    def test_user_restored_after_permission_error(self):
        """frappe.session.user must be restored even when tool raises PermissionDeniedError."""
        user_email = "mcp-lowperm@example.com"
        if not frappe.db.exists("User", user_email):
            frappe.get_doc({
                "doctype": "User",
                "email": user_email,
                "first_name": "MCP LowPerm",
                "send_welcome_email": 0,
            }).insert(ignore_permissions=True)

        original = frappe.session.user
        body = {
            "jsonrpc": "2.0",
            "id": 15,
            "method": "tools/call",
            "params": {
                "name": "get_schema",
                "arguments": {
                    "doctype": "Customer",
                    "_user": user_email,
                },
            },
        }
        _handle_tools_call(body, msg_id=15)
        self.assertEqual(frappe.session.user, original)

    def test_missing_tool_name_returns_invalid_params(self):
        body = {
            "jsonrpc": "2.0",
            "id": 16,
            "method": "tools/call",
            "params": {"arguments": {"_user": "Administrator"}},
        }
        result = _handle_tools_call(body, msg_id=16)
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], JSONRPC_INVALID_PARAMS)


# ---------------------------------------------------------------------------
# Test: unknown JSON-RPC method
# ---------------------------------------------------------------------------


class TestUnknownMethod(FrappeTestCase):
    def test_unknown_method_via_serve(self):
        _set_token(_TOKEN)
        body = {"jsonrpc": "2.0", "id": 99, "method": "ping"}
        req = _make_request(headers=_auth_headers(_TOKEN), json_body=body)
        with patch("frappe.request", req):
            result = serve()
        _clear_token()
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], JSONRPC_METHOD_NOT_FOUND)
        self.assertIn("ping", result["error"]["message"])


# ---------------------------------------------------------------------------
# Test: _jsonrpc_error helper
# ---------------------------------------------------------------------------


class TestJsonrpcError(FrappeTestCase):
    def test_basic_error_shape(self):
        result = _jsonrpc_error(1, -32600, "bad request")
        self.assertEqual(result["jsonrpc"], "2.0")
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["error"]["code"], -32600)
        self.assertEqual(result["error"]["message"], "bad request")
        self.assertNotIn("data", result["error"])

    def test_error_with_type_includes_data(self):
        result = _jsonrpc_error(2, -32601, "not found", error_type="ToolNotFoundError")
        self.assertEqual(result["error"]["data"]["type"], "ToolNotFoundError")

    def test_null_id_for_notifications(self):
        result = _jsonrpc_error(None, -32700, "parse error")
        self.assertIsNone(result["id"])
