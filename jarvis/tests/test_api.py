from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.api import call_tool


class TestCallToolStandardAuth(FrappeTestCase):
	"""Direct-Python invocation path: behaves like Phase 1, runs as the current session user."""

	def test_calls_tool_and_returns_result(self):
		result = call_tool(tool="get_schema", args={"doctype": "Customer"})
		self.assertEqual(result["ok"], True)
		self.assertEqual(result["data"]["doctype"], "Customer")

	def test_accepts_json_string_args(self):
		result = call_tool(tool="get_schema", args='{"doctype": "Customer"}')
		self.assertEqual(result["ok"], True)

	def test_unknown_tool_returns_error_envelope(self):
		result = call_tool(tool="not_a_tool", args={})
		self.assertEqual(result["ok"], False)
		self.assertEqual(result["error"]["code"], "ToolNotFoundError")

	def test_invalid_args_returns_error_envelope(self):
		result = call_tool(tool="get_doc", args={"doctype": "Customer"})
		self.assertEqual(result["ok"], False)
		self.assertEqual(result["error"]["code"], "InvalidArgumentError")


class _FakeRequest:
	"""Minimal request stand-in for the plugin-auth tests."""

	def __init__(self, headers: dict[str, str]):
		self.headers = headers


class TestCallToolPluginAuth(FrappeTestCase):
	"""Plugin-auth path: X-Jarvis-Token + X-Jarvis-User → dispatch as that user."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Jarvis Settings")
		# Use a dedicated token for plugin-auth tests so we don't depend on
		# real openclaw config. db_set bypasses on_update — the value persists
		# only for this test class.
		cls._original_token = settings.get_password("openclaw_gateway_token") or ""
		settings.db_set("openclaw_gateway_token", "plugin-auth-test-token")
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("openclaw_gateway_token", cls._original_token)
		frappe.db.commit()
		super().tearDownClass()

	def _with_headers(self, headers: dict[str, str]):
		return patch.object(frappe, "request", _FakeRequest(headers), create=True)

	def test_valid_token_and_user_dispatches_as_that_user(self):
		"""Plugin-auth path runs frappe.set_user(X-Jarvis-User) for the dispatch."""
		seen_user: dict[str, str] = {}

		def spy_dispatch(name, args):
			seen_user["user"] = frappe.session.user
			return {"doctype": args["doctype"], "fields": []}

		with self._with_headers({
			"X-Jarvis-Token": "plugin-auth-test-token",
			"X-Jarvis-User": "Administrator",
		}):
			with patch("jarvis.api.dispatch", side_effect=spy_dispatch):
				result = call_tool(tool="get_schema", args={"doctype": "Customer"})

		self.assertEqual(result["ok"], True)
		self.assertEqual(seen_user["user"], "Administrator")

	def test_invalid_token_returns_401(self):
		with self._with_headers({
			"X-Jarvis-Token": "wrong-token",
			"X-Jarvis-User": "Administrator",
		}):
			result = call_tool(tool="get_schema", args={"doctype": "Customer"})
		self.assertEqual(result["ok"], False)
		self.assertEqual(result["error"]["code"], "AuthenticationError")
		self.assertEqual(frappe.local.response.http_status_code, 401)

	def test_token_without_user_header_returns_400(self):
		with self._with_headers({"X-Jarvis-Token": "plugin-auth-test-token"}):
			result = call_tool(tool="get_schema", args={"doctype": "Customer"})
		self.assertEqual(result["ok"], False)
		self.assertEqual(result["error"]["code"], "InvalidArgumentError")
		self.assertIn("X-Jarvis-User", result["error"]["message"])

	def test_token_with_unknown_user_returns_400(self):
		with self._with_headers({
			"X-Jarvis-Token": "plugin-auth-test-token",
			"X-Jarvis-User": "nonexistent-user@example.invalid",
		}):
			result = call_tool(tool="get_schema", args={"doctype": "Customer"})
		self.assertEqual(result["ok"], False)
		self.assertEqual(result["error"]["code"], "InvalidArgumentError")
		self.assertIn("unknown user", result["error"]["message"])

	def test_session_user_restored_after_dispatch(self):
		"""set_user is wrapped in try/finally — the calling user is preserved."""
		original = frappe.session.user
		with self._with_headers({
			"X-Jarvis-Token": "plugin-auth-test-token",
			"X-Jarvis-User": "Administrator",
		}):
			call_tool(tool="get_schema", args={"doctype": "Customer"})
		self.assertEqual(frappe.session.user, original)
