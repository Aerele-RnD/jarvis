"""Tests for the `via_voice` flag on `Jarvis Chat Message` and the matching
`voice` param on `jarvis.chat.api.send_message` (2026-09-08 session-feedback
plan, Task 6).

Mirrors `test_chat_attachments.py`'s fixture pattern: a dedicated test user
(never Administrator) and `frappe.enqueue` patched out so no real turn runs.

Run ONLY this module (the full suite is destructive on a live dev site):
    bench --site <site> run-tests --app jarvis \\
        --module jarvis.tests.test_send_message_voice_flag
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.api import create_conversation, send_message
from jarvis.tests.test_chat_api import TEST_USER, _cleanup_user_conversations, _ensure_test_user

MSG = "Jarvis Chat Message"


def _send(conv, message="", voice=False):
	"""Persist a user message without enqueueing a real turn."""
	with patch("frappe.enqueue"):
		return send_message(conv, message, voice=voice)


class TestSendMessageVoiceFlag(FrappeTestCase):
	"""Runs as the fixture user (never Administrator) so a run cannot wipe real
	chat history; only TEST_USER's own conversations are created + cleaned."""

	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()
		self.conv = create_conversation()

	def tearDown(self):
		_cleanup_user_conversations()
		frappe.set_user(self._orig_user)

	def test_typed_message_has_via_voice_false(self):
		res = _send(self.conv, "typed by hand", voice=False)
		self.assertFalse(bool(frappe.db.get_value(MSG, res["message_id"], "via_voice")))

	def test_dictated_message_has_via_voice_true(self):
		res = _send(self.conv, "said out loud", voice=True)
		self.assertTrue(bool(frappe.db.get_value(MSG, res["message_id"], "via_voice")))

	def test_voice_defaults_false_when_param_omitted(self):
		"""Every existing caller (approvals_api, filebox, agents_api) omits
		`voice` entirely — it must keep defaulting to false, not error."""
		with patch("frappe.enqueue"):
			res = send_message(self.conv, "no voice kwarg at all")
		self.assertFalse(bool(frappe.db.get_value(MSG, res["message_id"], "via_voice")))
