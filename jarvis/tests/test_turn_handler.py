"""Tests for jarvis.chat.turn_handler.handle_chat_send.

Phase 1 of the chat-bridge refactor extracts the turn body out of
``jarvis.chat.worker.run_agent_turn`` into
``jarvis.chat.turn_handler.handle_chat_send``. The worker function is
preserved as a thin shim that builds the payload dict and calls
``handle_chat_send``. The behavioural coverage is owned by
``test_chat_worker.py`` (which must keep passing unchanged); these
tests pin only the payload-mapping contract between the shim and the
handler so a future refactor cannot silently change the payload shape.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat import openclaw_session_pool
from jarvis.chat import turn_handler, worker
from jarvis.tests.test_chat_api import (
	TEST_USER,
	_cleanup_user_conversations,
	_ensure_test_user,
)
from jarvis.tests.test_chat_worker import (
	_fake_event_stream,
	_make_conversation_with_user_message,
)

MSG = "Jarvis Chat Message"


class TestHandleChatSendAcceptsPayloadDict(FrappeTestCase):
	"""``handle_chat_send`` is the new entry point. It must accept a
	payload dict with conversation_id/message_id/run_id and drive a
	turn end-to-end with the same effect as the RQ shim.
	"""

	def setUp(self):
		openclaw_session_pool._POOL.clear()
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()
		self.conv, self.user_msg = _make_conversation_with_user_message("hello")

	def tearDown(self):
		_cleanup_user_conversations()
		frappe.set_user(self._orig_user)

	def test_payload_dict_drives_a_full_turn(self):
		fake_sess = MagicMock()
		fake_sess.stream_agent_turn.return_value = _fake_event_stream([
			{"kind": "lifecycle", "phase": "start"},
			{"kind": "assistant", "text": "ok", "delta": "ok"},
			{"kind": "lifecycle", "phase": "end"},
		])
		with patch(
			"jarvis.chat.openclaw_session_pool.OpenclawSession.connect",
			return_value=fake_sess,
		):
			with patch("jarvis.chat.worker.publish_to_user") as pub:
				turn_handler.handle_chat_send({
					"conversation_id": self.conv,
					"message_id": self.user_msg,
					"run_id": "r-payload",
				})

		# The assistant placeholder was created, content was persisted,
		# streaming flipped off. (Behavioural depth lives in
		# test_chat_worker; we only need a smoke here.)
		rows = frappe.get_all(
			MSG,
			filters={"conversation": self.conv, "role": "assistant"},
			fields=["content", "streaming"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["content"], "ok")
		self.assertEqual(rows[0]["streaming"], 0)

		# run:start ... run:end bracket was published via the worker-
		# module indirection, confirming the patch path still wins for
		# code that now lives in turn_handler.
		kinds = [c.args[1]["kind"] for c in pub.call_args_list]
		self.assertIn("run:start", kinds)
		self.assertIn("run:end", kinds)

	def test_attachments_and_context_default_to_none(self):
		"""The payload omits ``attachments`` and ``context``; the handler
		must treat them as None and not blow up on missing keys."""
		fake_sess = MagicMock()
		fake_sess.stream_agent_turn.return_value = _fake_event_stream([
			{"kind": "lifecycle", "phase": "end"},
		])
		with patch(
			"jarvis.chat.openclaw_session_pool.OpenclawSession.connect",
			return_value=fake_sess,
		):
			with patch("jarvis.chat.worker.publish_to_user"):
				turn_handler.handle_chat_send({
					"conversation_id": self.conv,
					"message_id": self.user_msg,
					"run_id": "r-optional",
				})
		# Reached this line without KeyError: the payload contract for
		# the optional fields holds.
		self.assertTrue(True)


class TestRunAgentTurnShimForwardsToHandleChatSend(FrappeTestCase):
	"""The RQ entry point ``worker.run_agent_turn`` is now a thin shim
	that constructs the payload dict and calls ``handle_chat_send``.
	Pin the payload shape so a future refactor can't drop a field.
	"""

	def test_shim_builds_expected_payload(self):
		with patch("jarvis.chat.worker.handle_chat_send") as fake:
			worker.run_agent_turn(
				"conv-1",
				"msg-1",
				"run-1",
				attachments=[{"file_url": "/private/files/x.txt", "file_name": "x.txt"}],
				context={"doctype": "Sales Invoice", "name": "SINV-0001"},
			)

		fake.assert_called_once()
		(payload,), _ = fake.call_args
		self.assertEqual(payload["conversation_id"], "conv-1")
		self.assertEqual(payload["message_id"], "msg-1")
		self.assertEqual(payload["run_id"], "run-1")
		self.assertEqual(
			payload["attachments"],
			[{"file_url": "/private/files/x.txt", "file_name": "x.txt"}],
		)
		self.assertEqual(
			payload["context"],
			{"doctype": "Sales Invoice", "name": "SINV-0001"},
		)

	def test_shim_defaults_attachments_and_context_to_none(self):
		with patch("jarvis.chat.worker.handle_chat_send") as fake:
			worker.run_agent_turn("conv-2", "msg-2", "run-2")

		fake.assert_called_once()
		(payload,), _ = fake.call_args
		self.assertIsNone(payload["attachments"])
		self.assertIsNone(payload["context"])
