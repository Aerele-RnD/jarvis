"""Tests for the X-Jarvis-Session header support on jarvis.api.call_tool."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.api import call_tool

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"
SESS = "Jarvis Chat Session"

PLUGIN_TOKEN = "test-plugin-token-xyz"


class _FakeRequest:
	def __init__(self, headers: dict):
		self.headers = headers


def _cleanup_for_session(session_key: str):
	convs = frappe.get_all(CONV, filters={"session_key": session_key}, pluck="name")
	for conv in convs:
		for child in frappe.get_all(MSG, filters={"conversation": conv}, pluck="name"):
			frappe.delete_doc(MSG, child, ignore_permissions=True, force=True)
		frappe.delete_doc(CONV, conv, ignore_permissions=True, force=True)
	sess_rows = frappe.get_all(SESS, filters={"session_key": session_key}, pluck="name")
	for s in sess_rows:
		frappe.delete_doc(SESS, s, ignore_permissions=True, force=True)
	frappe.db.commit()


class TestCallToolWithSessionHeader(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Jarvis Settings")
		cls._original_token = settings.get_password("openclaw_gateway_token") or ""
		settings.db_set("openclaw_gateway_token", PLUGIN_TOKEN)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("openclaw_gateway_token", cls._original_token)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		self.session_key = "agent:test:abc-123"
		_cleanup_for_session(self.session_key)
		conv = frappe.get_doc({
			"doctype": CONV,
			"title": "T",
			"session_key": self.session_key,
			"status": "active",
		})
		conv.insert(ignore_permissions=True)
		frappe.get_doc({
			"doctype": SESS,
			"session_key": self.session_key,
			"user": "Administrator",
		}).insert(ignore_permissions=True)
		frappe.db.commit()
		self.conv_name = conv.name

	def tearDown(self):
		_cleanup_for_session(self.session_key)

	def test_session_header_persists_tool_message(self):
		req = _FakeRequest({
			"X-Jarvis-Token": PLUGIN_TOKEN,
			"X-Jarvis-User": "Administrator",
			"X-Jarvis-Session": self.session_key,
		})
		with patch.object(frappe, "request", req, create=True):
			with patch("jarvis.api.publish_realtime_tool_result"):
				result = call_tool("get_schema", args={"doctype": "Customer"})

		self.assertTrue(result["ok"])
		tools = frappe.get_all(
			MSG,
			filters={"conversation": self.conv_name, "role": "tool"},
			fields=["tool_name", "tool_args", "tool_result", "tool_status"],
		)
		self.assertEqual(len(tools), 1)
		self.assertEqual(tools[0]["tool_name"], "get_schema")
		self.assertEqual(tools[0]["tool_status"], "completed")

	def test_session_header_publishes_realtime_tool_result(self):
		req = _FakeRequest({
			"X-Jarvis-Token": PLUGIN_TOKEN,
			"X-Jarvis-User": "Administrator",
			"X-Jarvis-Session": self.session_key,
		})
		with patch.object(frappe, "request", req, create=True):
			with patch("jarvis.api.publish_realtime_tool_result") as pub:
				call_tool("get_schema", args={"doctype": "Customer"})
		pub.assert_called_once()
		_, kwargs = pub.call_args
		self.assertEqual(kwargs["tool_name"], "get_schema")
		self.assertEqual(kwargs["status"], "completed")

	def test_no_session_header_does_not_publish(self):
		req = _FakeRequest({
			"X-Jarvis-Token": PLUGIN_TOKEN,
			"X-Jarvis-User": "Administrator",
		})
		with patch.object(frappe, "request", req, create=True):
			with patch("jarvis.api.publish_realtime_tool_result") as pub:
				call_tool("get_schema", args={"doctype": "Customer"})
		pub.assert_not_called()
		tools = frappe.get_all(MSG, filters={"conversation": self.conv_name, "role": "tool"})
		self.assertEqual(len(tools), 0)

	def test_unknown_session_does_not_break_dispatch(self):
		req = _FakeRequest({
			"X-Jarvis-Token": PLUGIN_TOKEN,
			"X-Jarvis-User": "Administrator",
			"X-Jarvis-Session": "agent:nonexistent",
		})
		with patch.object(frappe, "request", req, create=True):
			result = call_tool("get_schema", args={"doctype": "Customer"})
		# Dispatch still succeeds; session-side persistence is best-effort
		self.assertTrue(result["ok"])
