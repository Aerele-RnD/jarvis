"""Tests for jarvis.chat.events - openclaw event parsing + realtime publish wrapper."""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from jarvis.chat.events import parse_event, publish_to_user


class TestParseEvent(FrappeTestCase):
	def test_lifecycle_start(self):
		ev = parse_event({"stream": "lifecycle", "data": {"phase": "start"}})
		self.assertEqual(ev["kind"], "lifecycle")
		self.assertEqual(ev["phase"], "start")

	def test_lifecycle_end(self):
		ev = parse_event({"stream": "lifecycle", "data": {"phase": "end"}})
		self.assertEqual(ev["kind"], "lifecycle")
		self.assertEqual(ev["phase"], "end")

	def test_lifecycle_error(self):
		ev = parse_event({"stream": "lifecycle", "data": {"phase": "error", "error": "x"}})
		self.assertEqual(ev["kind"], "lifecycle")
		self.assertEqual(ev["phase"], "error")
		self.assertEqual(ev["error"], "x")

	def test_tool_start(self):
		ev = parse_event({
			"stream": "item",
			"data": {
				"kind": "tool",
				"phase": "start",
				"name": "jarvis__get_list",
				"toolCallId": "tc-1",
			},
		})
		self.assertEqual(ev["kind"], "tool")
		self.assertEqual(ev["phase"], "start")
		self.assertEqual(ev["tool_name"], "jarvis__get_list")
		self.assertEqual(ev["tool_call_id"], "tc-1")

	def test_tool_end(self):
		ev = parse_event({
			"stream": "item",
			"data": {
				"kind": "tool",
				"phase": "end",
				"name": "jarvis__get_list",
				"toolCallId": "tc-1",
				"status": "completed",
			},
		})
		self.assertEqual(ev["kind"], "tool")
		self.assertEqual(ev["phase"], "end")
		self.assertEqual(ev["status"], "completed")

	def test_assistant_delta(self):
		ev = parse_event({
			"stream": "assistant",
			"data": {"text": "Hello world", "delta": " world"},
		})
		self.assertEqual(ev["kind"], "assistant")
		self.assertEqual(ev["text"], "Hello world")
		self.assertEqual(ev["delta"], " world")

	def test_item_non_tool_returns_none(self):
		ev = parse_event({"stream": "item", "data": {"kind": "thinking"}})
		self.assertIsNone(ev)

	def test_unknown_stream_returns_none(self):
		ev = parse_event({"stream": "heartbeat", "data": {}})
		self.assertIsNone(ev)

	def test_empty_stream_returns_none(self):
		ev = parse_event({"stream": None, "data": {}})
		self.assertIsNone(ev)


class TestPublishToUser(FrappeTestCase):
	def test_publishes_to_jarvis_event_channel_scoped_to_user(self):
		with patch("frappe.publish_realtime") as mock_pub:
			publish_to_user("alice@example.com", {"kind": "run:start"})
		mock_pub.assert_called_once_with(
			"jarvis:event",
			{"kind": "run:start"},
			user="alice@example.com",
		)
