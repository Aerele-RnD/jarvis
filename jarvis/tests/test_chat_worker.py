"""Tests for jarvis.chat.worker.run_agent_turn.

Like test_chat_api, these run as the fixture user ``TEST_USER`` — never as
Administrator — so the test suite cannot wipe real chat history when run
against a dev site.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.api import create_conversation, send_message
from jarvis.chat.worker import run_agent_turn
from jarvis.tests.test_chat_api import (
	TEST_USER,
	_cleanup_user_conversations,
	_ensure_test_user,
)

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"


def _make_conversation_with_user_message(text: str = "hi") -> tuple[str, str]:
	"""Helper: create conversation, attach a user message, return (conv, msg)."""
	conv = create_conversation()
	with patch("jarvis.chat.api._ensure_session_key", return_value="agent:fake"):
		with patch("frappe.enqueue"):
			result = send_message(conv, text)
	return conv, result["message_id"]


def _fake_event_stream(events: list[dict]):
	"""Build a generator returning the given events (matching parse_event output)."""
	for ev in events:
		yield ev


class TestRunAgentTurnHappyPath(FrappeTestCase):
	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()
		self.conv, self.user_msg = _make_conversation_with_user_message()

	def tearDown(self):
		_cleanup_user_conversations()
		frappe.set_user(self._orig_user)

	def test_streams_assistant_deltas_to_db_and_realtime(self):
		fake_sess = MagicMock()
		fake_sess.stream_agent_turn.return_value = _fake_event_stream([
			{"kind": "lifecycle", "phase": "start"},
			{"kind": "assistant", "text": "Hello", "delta": "Hello"},
			{"kind": "assistant", "text": "Hello world", "delta": " world"},
			{"kind": "lifecycle", "phase": "end"},
		])
		with patch("jarvis.chat.worker.OpenclawSession.connect", return_value=fake_sess):
			with patch("jarvis.chat.worker.publish_to_user") as pub:
				run_agent_turn(self.conv, self.user_msg, run_id="r1")

		# One assistant message persisted, content = final cumulative text
		assistants = frappe.get_all(
			MSG,
			filters={"conversation": self.conv, "role": "assistant"},
			fields=["name", "content", "streaming"],
		)
		self.assertEqual(len(assistants), 1)
		self.assertEqual(assistants[0]["content"], "Hello world")
		self.assertEqual(assistants[0]["streaming"], 0)

		# Realtime publishes happened
		kinds = [c.args[1]["kind"] for c in pub.call_args_list]
		self.assertIn("run:start", kinds)
		self.assertIn("assistant:delta", kinds)
		self.assertIn("run:end", kinds)


class TestRunAgentTurnToolCall(FrappeTestCase):
	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()
		self.conv, self.user_msg = _make_conversation_with_user_message()

	def tearDown(self):
		_cleanup_user_conversations()
		frappe.set_user(self._orig_user)

	def test_tool_events_persist_tool_message_rows(self):
		fake_sess = MagicMock()
		fake_sess.stream_agent_turn.return_value = _fake_event_stream([
			{"kind": "lifecycle", "phase": "start"},
			{"kind": "tool", "phase": "start", "tool_name": "jarvis__get_list",
			 "tool_call_id": "tc-1"},
			{"kind": "tool", "phase": "end", "tool_name": "jarvis__get_list",
			 "tool_call_id": "tc-1", "status": "completed"},
			{"kind": "assistant", "text": "Done", "delta": "Done"},
			{"kind": "lifecycle", "phase": "end"},
		])
		with patch("jarvis.chat.worker.OpenclawSession.connect", return_value=fake_sess):
			with patch("jarvis.chat.worker.publish_to_user"):
				run_agent_turn(self.conv, self.user_msg, run_id="r1")

		tools = frappe.get_all(
			MSG,
			filters={"conversation": self.conv, "role": "tool"},
			fields=["tool_name", "tool_status"],
		)
		self.assertEqual(len(tools), 1)
		self.assertEqual(tools[0]["tool_name"], "jarvis__get_list")
		self.assertEqual(tools[0]["tool_status"], "completed")


class TestRunAgentTurnErrorPaths(FrappeTestCase):
	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()
		self.conv, self.user_msg = _make_conversation_with_user_message()

	def tearDown(self):
		_cleanup_user_conversations()
		frappe.set_user(self._orig_user)

	def test_connect_failure_publishes_run_error_and_marks_message_errored(self):
		from jarvis.exceptions import OpenclawUnreachableError
		with patch(
			"jarvis.chat.worker.OpenclawSession.connect",
			side_effect=OpenclawUnreachableError("connect refused"),
		):
			with patch("jarvis.chat.worker.publish_to_user") as pub:
				run_agent_turn(self.conv, self.user_msg, run_id="r1")

		assistants = frappe.get_all(
			MSG,
			filters={"conversation": self.conv, "role": "assistant"},
			fields=["error", "streaming"],
		)
		self.assertEqual(len(assistants), 1)
		self.assertIn("connect refused", assistants[0]["error"])
		self.assertEqual(assistants[0]["streaming"], 0)

		kinds = [c.args[1]["kind"] for c in pub.call_args_list]
		self.assertIn("run:error", kinds)

	def test_lifecycle_error_marks_message_errored(self):
		fake_sess = MagicMock()
		fake_sess.stream_agent_turn.return_value = _fake_event_stream([
			{"kind": "lifecycle", "phase": "start"},
			{"kind": "lifecycle", "phase": "error", "error": "model overloaded"},
		])
		with patch("jarvis.chat.worker.OpenclawSession.connect", return_value=fake_sess):
			with patch("jarvis.chat.worker.publish_to_user"):
				run_agent_turn(self.conv, self.user_msg, run_id="r1")

		assistants = frappe.get_all(
			MSG,
			filters={"conversation": self.conv, "role": "assistant"},
			fields=["error"],
		)
		self.assertIn("model overloaded", assistants[0]["error"])
