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


class TestRunAgentTurnAugmentsMessage(FrappeTestCase):
	"""Worker should prepend `[Context: today is ...]` to the user message
	before sending it to openclaw, so the agent can resolve relative time
	expressions ("last quarter") without a clarifying round-trip.
	"""

	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()
		self.conv, self.user_msg = _make_conversation_with_user_message(
			"how many invoices last quarter?"
		)

	def tearDown(self):
		_cleanup_user_conversations()
		frappe.set_user(self._orig_user)

	def test_prepends_today_context_to_user_message(self):
		fake_sess = MagicMock()
		fake_sess.stream_agent_turn.return_value = _fake_event_stream([
			{"kind": "lifecycle", "phase": "start"},
			{"kind": "lifecycle", "phase": "end"},
		])
		with patch("jarvis.chat.worker.OpenclawSession.connect", return_value=fake_sess):
			with patch("jarvis.chat.worker.publish_to_user"):
				run_agent_turn(self.conv, self.user_msg, run_id="r1")

		# stream_agent_turn was called with (session_key, message_text, idem)
		fake_sess.stream_agent_turn.assert_called_once()
		_, kwargs = fake_sess.stream_agent_turn.call_args
		# args may be either positional or keyword — handle both
		positional = fake_sess.stream_agent_turn.call_args.args
		message_sent = (
			positional[1] if len(positional) >= 2
			else kwargs.get("message")
		)
		self.assertIsNotNone(message_sent)
		self.assertIn("[Context: today is ", message_sent)
		self.assertIn("how many invoices last quarter?", message_sent)
		# The DB-persisted user message stays untouched (no prefix)
		original = frappe.db.get_value(MSG, self.user_msg, "content")
		self.assertEqual(original, "how many invoices last quarter?")


class TestRunAgentTurnModelResolution(FrappeTestCase):
	"""Worker resolves the effective model from conv.model_override → settings.llm_model
	and threads it (with the openclaw provider id) into stream_agent_turn.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Jarvis Settings")
		cls._settings_snap = {
			"llm_auth_mode": settings.llm_auth_mode,
			"llm_provider": settings.llm_provider,
			"llm_model": settings.llm_model,
		}
		settings.db_set("llm_auth_mode", "oauth", update_modified=False)
		settings.db_set("llm_provider", "OpenAI", update_modified=False)
		settings.db_set("llm_model", "gpt-5.5", update_modified=False)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		settings = frappe.get_single("Jarvis Settings")
		for k, v in cls._settings_snap.items():
			settings.db_set(k, v, update_modified=False)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()
		self.conv, self.user_msg = _make_conversation_with_user_message("hi")

	def tearDown(self):
		_cleanup_user_conversations()
		frappe.set_user(self._orig_user)

	def _run_and_capture(self):
		fake_sess = MagicMock()
		fake_sess.stream_agent_turn.return_value = _fake_event_stream([
			{"kind": "lifecycle", "phase": "end"},
		])
		with patch("jarvis.chat.worker.OpenclawSession.connect", return_value=fake_sess):
			with patch("jarvis.chat.worker.publish_to_user"):
				run_agent_turn(self.conv, self.user_msg, run_id="r1")
		return fake_sess.stream_agent_turn.call_args

	def test_no_override_uses_settings_model_and_oauth_provider_id(self):
		"""conv.model_override empty → effective_model = settings.llm_model;
		provider id mapped from settings.llm_provider to openclaw provider id."""
		call = self._run_and_capture()
		kwargs = call.kwargs
		self.assertEqual(kwargs.get("model"), "gpt-5.5")
		self.assertEqual(kwargs.get("provider"), "openai-codex")

	def test_override_used_when_set(self):
		"""conv.model_override = gpt-5.4-mini → effective_model = gpt-5.4-mini."""
		frappe.db.set_value(CONV, self.conv, "model_override", "gpt-5.4-mini")
		frappe.db.commit()
		call = self._run_and_capture()
		kwargs = call.kwargs
		self.assertEqual(kwargs.get("model"), "gpt-5.4-mini")
		self.assertEqual(kwargs.get("provider"), "openai-codex")


class TestRunAgentTurnApiKeyModeOmitsProvider(FrappeTestCase):
	"""In api_key mode (not oauth), the worker should NOT thread the
	provider param — there's no per-tenant codex provider to override
	to; api-key-mode customers have one provider registered."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Jarvis Settings")
		cls._snap = {
			"llm_auth_mode": settings.llm_auth_mode,
			"llm_provider": settings.llm_provider,
			"llm_model": settings.llm_model,
		}
		settings.db_set("llm_auth_mode", "api_key", update_modified=False)
		settings.db_set("llm_provider", "Anthropic", update_modified=False)
		settings.db_set("llm_model", "claude-sonnet-4-6", update_modified=False)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		settings = frappe.get_single("Jarvis Settings")
		for k, v in cls._snap.items():
			settings.db_set(k, v, update_modified=False)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()
		self.conv, self.user_msg = _make_conversation_with_user_message("hi")

	def tearDown(self):
		_cleanup_user_conversations()
		frappe.set_user(self._orig_user)

	def test_provider_omitted_in_api_key_mode(self):
		fake_sess = MagicMock()
		fake_sess.stream_agent_turn.return_value = _fake_event_stream([
			{"kind": "lifecycle", "phase": "end"},
		])
		with patch("jarvis.chat.worker.OpenclawSession.connect", return_value=fake_sess):
			with patch("jarvis.chat.worker.publish_to_user"):
				run_agent_turn(self.conv, self.user_msg, run_id="r1")
		kwargs = fake_sess.stream_agent_turn.call_args.kwargs
		self.assertEqual(kwargs.get("model"), "claude-sonnet-4-6")
		self.assertIsNone(kwargs.get("provider"))
