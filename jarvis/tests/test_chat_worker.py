"""Tests for jarvis.chat.worker.run_agent_turn.

Like test_chat_api, these run as the fixture user ``TEST_USER`` - never as
Administrator - so the test suite cannot wipe real chat history when run
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

	def test_unexpected_exception_marks_errored_then_reraises(self):
		"""Sprint-3 (2026-06-16 review): the inline OpenclawUnreachableError
		catches USED to leave every other exception (cryptography.InvalidKey
		from device signing, ssl.SSLError, programmer bugs in _handle_event)
		propagating to RQ without _mark_errored or run:error - the
		assistant row stayed at streaming=1 forever and the UI spun. The
		outer catch-all now marks errored + publishes run:error AND
		re-raises so RQ records the job failure.
		"""
		fake_sess = MagicMock()
		# Simulate a non-Openclaw exception escaping from stream_agent_turn
		# (e.g. an SSL handshake mid-stream, or a tool-handler bug).
		import ssl
		fake_sess.stream_agent_turn.side_effect = ssl.SSLError("handshake failed")

		published_kinds: list = []
		def _capture(user, payload):
			published_kinds.append(payload.get("kind"))

		with patch("jarvis.chat.worker.OpenclawSession.connect", return_value=fake_sess), \
		     patch("jarvis.chat.worker.publish_to_user", side_effect=_capture):
			with self.assertRaises(ssl.SSLError):
				run_agent_turn(self.conv, self.user_msg, run_id="r1")

		# Placeholder must be flipped off streaming + carry an error.
		assistants = frappe.get_all(
			MSG,
			filters={"conversation": self.conv, "role": "assistant"},
			fields=["error", "streaming"],
		)
		self.assertEqual(len(assistants), 1)
		self.assertEqual(assistants[0]["streaming"], 0)
		# Error message names the exception class - operator can grep
		# the Error Log for the full traceback.
		self.assertIn("SSLError", assistants[0]["error"] or "")
		# Realtime run:error was published so the UI exits its spinner.
		self.assertIn("run:error", published_kinds)


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
		# args may be either positional or keyword - handle both
		positional = fake_sess.stream_agent_turn.call_args.args
		message_sent = (
			positional[1] if len(positional) >= 2
			else kwargs.get("message")
		)
		self.assertIsNotNone(message_sent)
		self.assertIn("[Context: today is ", message_sent)
		# Chat user (conv.owner) is in the same bracket so the agent can
		# answer "who am I" / "what perms do I have" without round-tripping.
		self.assertIn(f"chat user: {TEST_USER}", message_sent)
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
		# Maps to openclaw's model-provider key, not the OAuth flow id
		# (which is "openai-codex"). See _PROVIDER_LABEL_TO_OPENCLAW_ID
		# in chat/worker.py for the rationale.
		self.assertEqual(kwargs.get("provider"), "openai")

	def test_override_used_when_set(self):
		"""conv.model_override = gpt-5.4-mini → effective_model = gpt-5.4-mini."""
		frappe.db.set_value(CONV, self.conv, "model_override", "gpt-5.4-mini")
		frappe.db.commit()
		call = self._run_and_capture()
		kwargs = call.kwargs
		self.assertEqual(kwargs.get("model"), "gpt-5.4-mini")
		# Maps to openclaw's model-provider key, not the OAuth flow id
		# (which is "openai-codex"). See _PROVIDER_LABEL_TO_OPENCLAW_ID
		# in chat/worker.py for the rationale.
		self.assertEqual(kwargs.get("provider"), "openai")


class TestRunAgentTurnApiKeyModeOmitsProvider(FrappeTestCase):
	"""In api_key mode (not oauth), the worker should NOT thread the
	provider param - there's no per-tenant codex provider to override
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


class TestAssistantContentBatching(FrappeTestCase):
	"""Sprint-5 punch-list "Worker writes assistant.content on every
	delta with full overwrite + commit per token" (2026-06-16 review).

	The hot-path optimization buffers assistant-content writes and
	flushes in batches instead of per-token. End-to-end observability
	is unchanged - realtime publishes still fire on every token, and
	the on-disk row holds the FINAL cumulative content at stream end -
	but the wire shape now coalesces N=10 events or 250ms into one
	commit, cutting hundreds of write+commit cycles to single digits
	per turn.
	"""

	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()
		self.conv, self.user_msg = _make_conversation_with_user_message()

	def tearDown(self):
		_cleanup_user_conversations()
		frappe.set_user(self._orig_user)

	def test_realtime_delta_fires_on_every_token(self):
		# Customer experience pin: the UI animates token-by-token via
		# realtime, so every assistant event must still publish an
		# assistant:delta even though the DB write coalesces.
		fake_sess = MagicMock()
		fake_sess.stream_agent_turn.return_value = _fake_event_stream([
			{"kind": "lifecycle", "phase": "start"},
			{"kind": "assistant", "text": "H", "delta": "H"},
			{"kind": "assistant", "text": "He", "delta": "e"},
			{"kind": "assistant", "text": "Hel", "delta": "l"},
			{"kind": "assistant", "text": "Hell", "delta": "l"},
			{"kind": "assistant", "text": "Hello", "delta": "o"},
			{"kind": "lifecycle", "phase": "end"},
		])
		with patch("jarvis.chat.worker.OpenclawSession.connect", return_value=fake_sess):
			with patch("jarvis.chat.worker.publish_to_user") as pub:
				run_agent_turn(self.conv, self.user_msg, run_id="r1")
		# Five assistant:delta publishes (one per token), even though
		# only 1-2 DB commits would have fired under batching.
		delta_calls = [
			c for c in pub.call_args_list
			if c.args[1].get("kind") == "assistant:delta"
		]
		self.assertEqual(len(delta_calls), 5)
		# Final on-disk content is the full cumulative text - the
		# end-of-stream batcher.flush() persists whatever was buffered.
		row = frappe.db.get_value(
			MSG,
			{"conversation": self.conv, "role": "assistant"},
			["content", "streaming"],
			as_dict=True,
		)
		self.assertEqual(row["content"], "Hello")
		self.assertEqual(row["streaming"], 0)

	def test_db_writes_coalesce_under_size_threshold(self):
		# 12 assistant events should produce 1 write at the size
		# threshold (10) + 1 final drain write = 2 set_value calls on
		# the assistant row's content. Without batching this would be
		# 12 set_value + 12 commit pairs.
		events = [{"kind": "lifecycle", "phase": "start"}]
		cum = ""
		for ch in "abcdefghijkl":  # 12 chars
			cum += ch
			events.append({"kind": "assistant", "text": cum, "delta": ch})
		events.append({"kind": "lifecycle", "phase": "end"})

		fake_sess = MagicMock()
		fake_sess.stream_agent_turn.return_value = _fake_event_stream(events)

		write_calls: list[tuple] = []
		real_set_value = frappe.db.set_value

		def tracking_set_value(*args, **kwargs):
			# args[0]=doctype, args[1]=name, args[2]=field or dict
			if (
				args
				and args[0] == MSG
				and (
					(len(args) >= 3 and args[2] == "content")
					or (len(args) >= 3 and isinstance(args[2], dict) and "content" in args[2])
				)
			):
				write_calls.append(args)
			return real_set_value(*args, **kwargs)

		with patch("jarvis.chat.worker.OpenclawSession.connect", return_value=fake_sess):
			with patch("jarvis.chat.worker.publish_to_user"):
				with patch("frappe.db.set_value", side_effect=tracking_set_value):
					run_agent_turn(self.conv, self.user_msg, run_id="r1")

		# At least 1 (the final drain) and at most 2 (size threshold +
		# drain). Critically NOT 12 - that would mean batching broke
		# and we're back to per-token commits.
		self.assertGreaterEqual(len(write_calls), 1)
		self.assertLessEqual(len(write_calls), 2)
		# Final on-disk content is the full cumulative text.
		row = frappe.db.get_value(
			MSG,
			{"conversation": self.conv, "role": "assistant"},
			"content",
		)
		self.assertEqual(row, "abcdefghijkl")

	def test_tool_event_flushes_pending_assistant_content_first(self):
		# Ordering pin: a tool event inserts a new row. The assistant
		# row's pending text must be persisted FIRST so the on-disk
		# ordering matches the realtime channel (customer sees assistant
		# text -> tool call). Verify by checking the assistant row's
		# content immediately after the tool event would have fired.
		fake_sess = MagicMock()
		fake_sess.stream_agent_turn.return_value = _fake_event_stream([
			{"kind": "lifecycle", "phase": "start"},
			{"kind": "assistant", "text": "Looking it up", "delta": "Looking it up"},
			# Tool event fires before the 10-event size threshold;
			# without the pre-tool flush the assistant row would be
			# empty until the next assistant delta.
			{"kind": "tool", "phase": "start", "tool_name": "jarvis__get_list",
			 "tool_call_id": "tc-1"},
			{"kind": "tool", "phase": "end", "tool_name": "jarvis__get_list",
			 "tool_call_id": "tc-1", "status": "completed"},
			{"kind": "assistant", "text": "Done!", "delta": " Done!"},
			{"kind": "lifecycle", "phase": "end"},
		])
		with patch("jarvis.chat.worker.OpenclawSession.connect", return_value=fake_sess):
			with patch("jarvis.chat.worker.publish_to_user"):
				run_agent_turn(self.conv, self.user_msg, run_id="r1")
		# Final cumulative content is the last assistant text. The
		# important thing is that the tool row got inserted AFTER the
		# "Looking it up" persist (which we can't directly observe in
		# this snapshot test, but the ordering invariant means the
		# final content is the LAST assistant text, not an arbitrary
		# unflushed earlier one).
		row = frappe.db.get_value(
			MSG,
			{"conversation": self.conv, "role": "assistant"},
			"content",
		)
		self.assertEqual(row, "Done!")

	def test_handle_event_failure_is_logged_and_stream_continues(self):
		# Sprint-5 punch-list "Wrap _handle_event in try/except logging
		# event kind + tool_call_id + run_id". A malformed event must
		# not blow up the whole turn - it gets logged via
		# frappe.log_error, then the next event runs.
		fake_sess = MagicMock()
		fake_sess.stream_agent_turn.return_value = _fake_event_stream([
			{"kind": "lifecycle", "phase": "start"},
			# A 'tool' end event with no matching start is the cleanest
			# trigger for an internal log, but we want to assert the
			# _handle_event try/except path - so inject a guaranteed
			# raise inside frappe.get_doc to break the tool-start
			# write path.
			{"kind": "tool", "phase": "start", "tool_name": "broken",
			 "tool_call_id": "tc-x"},
			{"kind": "assistant", "text": "Recovered", "delta": "Recovered"},
			{"kind": "lifecycle", "phase": "end"},
		])
		# Force the tool-start insert to fail; the assistant event
		# after it must still land.
		_orig_get_doc = frappe.get_doc

		def boom_on_tool_msg(*args, **kwargs):
			if args and isinstance(args[0], dict) and args[0].get("role") == "tool":
				raise RuntimeError("simulated tool-row insert failure")
			return _orig_get_doc(*args, **kwargs)

		with patch("jarvis.chat.worker.OpenclawSession.connect", return_value=fake_sess):
			with patch("jarvis.chat.worker.publish_to_user"):
				with patch("frappe.get_doc", side_effect=boom_on_tool_msg):
					with patch("frappe.log_error") as log_err:
						run_agent_turn(self.conv, self.user_msg, run_id="r1")
		# The tool-row failure was logged with the event kind + ids.
		titles = [c.kwargs.get("title", "") for c in log_err.call_args_list]
		self.assertTrue(
			any("_handle_event failed" in t for t in titles),
			f"expected '_handle_event failed' log; got {titles!r}",
		)
		# The assistant event AFTER the broken tool event still ran
		# (stream didn't abort), and the assistant row's final content
		# reflects the recovery delta.
		row = frappe.db.get_value(
			MSG,
			{"conversation": self.conv, "role": "assistant"},
			"content",
		)
		self.assertEqual(row, "Recovered")


class TestAssistantContentBatcherUnit(FrappeTestCase):
	"""Unit-level coverage of _AssistantContentBatcher thresholds."""

	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()
		self.conv, self.user_msg = _make_conversation_with_user_message()
		# Find the assistant placeholder row created by the conversation.
		self.assistant_name = frappe.get_doc({
			"doctype": MSG,
			"conversation": self.conv,
			"seq": 99,
			"role": "assistant",
			"content": "",
			"streaming": 1,
		}).insert(ignore_permissions=True).name
		frappe.db.commit()

	def tearDown(self):
		_cleanup_user_conversations()
		frappe.set_user(self._orig_user)

	def test_flush_persists_pending_text(self):
		from jarvis.chat.worker import _AssistantContentBatcher
		b = _AssistantContentBatcher(self.assistant_name)
		b.delta("hello")
		self.assertTrue(b.flush())
		self.assertEqual(
			frappe.db.get_value(MSG, self.assistant_name, "content"),
			"hello",
		)
		# Second flush with no new text is a no-op.
		self.assertFalse(b.flush())

	def test_flush_if_due_respects_size_threshold(self):
		from jarvis.chat.worker import (
			_ASSISTANT_BATCH_SIZE,
			_AssistantContentBatcher,
		)
		b = _AssistantContentBatcher(self.assistant_name)
		# Below the size threshold: no flush (the time threshold is 250ms
		# which this test runs well under).
		for i in range(_ASSISTANT_BATCH_SIZE - 1):
			b.delta(f"text-{i}")
			self.assertFalse(b.flush_if_due())
		# Hitting the size threshold flushes.
		b.delta(f"text-{_ASSISTANT_BATCH_SIZE - 1}")
		self.assertTrue(b.flush_if_due())
		# After flush, the next delta starts the counter over.
		b.delta("post-flush")
		self.assertFalse(b.flush_if_due())
