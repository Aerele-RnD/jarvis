"""Tests for per-conversation thinking effort (Phase 2).

Covers _thinking_prefix (pure unit) and the directive-leading invariant
that holds even when _prepend_doc_context prefixes a [Viewing: ...] line
(spec section 7.3, verification item 10.3).
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat import openclaw_session_pool
from jarvis.chat.api import create_conversation, send_message
from jarvis.chat.turn_handler import _thinking_prefix
from jarvis.chat.worker import run_agent_turn
from jarvis.tests.test_chat_api import (
	TEST_USER,
	_cleanup_user_conversations,
	_ensure_test_user,
)


class TestThinkingPrefix(FrappeTestCase):
	def test_levels_emit_directive(self):
		self.assertEqual(_thinking_prefix("low"), "/think low\n")
		self.assertEqual(_thinking_prefix("MEDIUM"), "/think medium\n")
		self.assertEqual(_thinking_prefix("high"), "/think high\n")

	def test_empty_or_invalid_emits_nothing(self):
		self.assertEqual(_thinking_prefix(""), "")
		self.assertEqual(_thinking_prefix(None), "")
		self.assertEqual(_thinking_prefix("ultra"), "")


class TestThinkingDirectiveLeading(FrappeTestCase):
	"""The /think directive must be the FIRST bytes sent to openclaw
	even when _prepend_doc_context prepends a [Viewing: ...] line for
	floating-widget auto-context (spec 7.3, verification 10.3).

	These tests call run_agent_turn with a mocked openclaw session and
	capture the message argument actually passed to stream_agent_turn.

	test_directive_leads_with_doc_context is the RED-before / GREEN-after
	test: before the relocation fix in handle_chat_send it fails because
	_thinking_prefix was applied before _prepend_doc_context (so [Viewing:]
	displaced the directive); after the fix it passes.
	"""

	def setUp(self):
		openclaw_session_pool._POOL.clear()
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()
		# _ensure_session_key (chat/api.py) INSERTs a Jarvis Chat Session keyed
		# on a UNIQUE session_key and COMMITs it. _capture_message_sent drives the
		# real _ensure_session_key with fake_sess.create_session -> "agent:fake",
		# so every test here inserts the same "agent:fake" key. Because that row
		# is committed it survives FrappeTestCase's per-test rollback, so a
		# leftover from an earlier test in this class (or elsewhere) collides on
		# the unique session_key. Clear the test user's sessions so each test's
		# insert starts clean.
		frappe.db.delete("Jarvis Chat Session", {"user": TEST_USER})
		frappe.db.commit()
		conv = create_conversation()
		with patch("jarvis.chat.api._ensure_session_key", return_value="agent:fake"):
			with patch("frappe.enqueue"):
				result = send_message(
					conv, "what is the status?", thinking_override="high",
				)
		self.conv = conv
		self.user_msg = result["message_id"]

	def tearDown(self):
		_cleanup_user_conversations()
		# Drop the committed Jarvis Chat Session row(s) created by
		# _ensure_session_key so the unique session_key doesn't leak into the
		# next test (see setUp).
		frappe.db.delete("Jarvis Chat Session", {"user": TEST_USER})
		frappe.db.commit()
		frappe.set_user(self._orig_user)

	def _capture_message_sent(self, context=None):
		"""Run one agent turn and return the message arg passed to stream_agent_turn.

		Uses call_args_list[0] (the FIRST call) to capture the user turn message.
		The second call, if any, is the auto-title prompt and must be ignored.
		"""
		fake_sess = MagicMock()
		fake_sess.create_session.return_value = "agent:fake"
		fake_sess.stream_agent_turn.side_effect = lambda *a, **kw: iter([
			{"kind": "lifecycle", "phase": "start"},
			{"kind": "lifecycle", "phase": "end"},
		])
		with patch(
			"jarvis.chat.openclaw_session_pool.OpenclawSession.connect",
			return_value=fake_sess,
		):
			with patch("jarvis.chat.worker.publish_to_user"):
				run_agent_turn(
					self.conv, self.user_msg, run_id="r1", context=context,
				)
		first_call = fake_sess.stream_agent_turn.call_args_list[0]
		pos = first_call.args
		kw = first_call.kwargs
		return pos[1] if len(pos) >= 2 else kw.get("message")

	def test_directive_leads_with_doc_context(self):
		"""RED before fix / GREEN after: /think is first even with [Viewing: ...].

		Before the relocation fix the message was:
		  '[Viewing: Sales Order SO-001...]\n\n/think high\n[Context: ...]'
		After the fix:
		  '/think high\n[Viewing: Sales Order SO-001...]\n\n[Context: ...]'
		"""
		msg = self._capture_message_sent(
			context={"doctype": "Sales Order", "name": "SO-001"},
		)
		self.assertIsNotNone(msg)
		self.assertTrue(
			msg.startswith("/think high\n"),
			f"expected /think high as first bytes; got: {msg[:120]!r}",
		)
		self.assertIn("[Viewing: Sales Order SO-001", msg)
		self.assertIn("[Context:", msg)
		self.assertIn("what is the status?", msg)

	def test_context_text_preserved(self):
		"""[Viewing: ...] and [Context: ...] text is not mutated by the fix."""
		msg = self._capture_message_sent(
			context={"doctype": "Purchase Invoice", "name": "PINV-0001"},
		)
		self.assertIn(
			"[Viewing: Purchase Invoice PINV-0001; resolve 'this'/'here' against it]",
			msg,
		)
		self.assertIn("[Context:", msg)

	def test_directive_leads_without_doc_context(self):
		"""Baseline: /think is first even without doc-context (no regression)."""
		msg = self._capture_message_sent(context=None)
		self.assertTrue(
			msg.startswith("/think high\n"),
			f"expected /think high at start without doc-context; got: {msg[:120]!r}",
		)
