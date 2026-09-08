"""Tests for the once-per-session feedback popup's backend: the maintained
``Jarvis Conversation.turn_count`` counter and the two whitelisted endpoints.

Runs as a dedicated fixture user so cleanups stay scoped to disposable rows,
and mirrors ``test_chat_feedback.py``'s fixture shape rather than a
rollback-based one: ``settlement._bump_turn_count`` commits its own tiny
transaction by design, so an ``addCleanup(frappe.db.rollback)`` would be
hollow. The admin forward is always mocked - these never hit a real admin.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.api import create_conversation
from jarvis.chat.feedback import (
	SESSION_FEEDBACK_TURN_THRESHOLD,
	session_feedback_status,
	submit_session_feedback,
)
from jarvis.chat.settlement import _bump_turn_count

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"
TEST_USER = "jarvis-session-feedback-test@example.com"

_PUSH = "jarvis.admin_client.push_session_feedback"


def _ensure_test_user(user: str = TEST_USER) -> None:
	if frappe.db.exists("User", user):
		return
	doc = frappe.get_doc(
		{
			"doctype": "User",
			"email": user,
			"first_name": "Session",
			"last_name": "Feedback",
			"enabled": 1,
			"send_welcome_email": 0,
			"user_type": "System User",
		}
	).insert(ignore_permissions=True)
	doc.add_roles("System Manager")
	frappe.db.commit()


def _delete_conv(name: str) -> None:
	for child in frappe.get_all(MSG, filters={"conversation": name}, pluck="name"):
		frappe.delete_doc(MSG, child, ignore_permissions=True, force=True)
	if frappe.db.exists(CONV, name):
		frappe.delete_doc(CONV, name, ignore_permissions=True, force=True)
	frappe.db.commit()


def _cleanup_user_conversations(user: str = TEST_USER) -> None:
	for name in frappe.get_all(CONV, filters={"owner": user}, pluck="name"):
		_delete_conv(name)


class _SessionFeedbackTestCase(FrappeTestCase):
	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()
		self.conv = create_conversation()

	def tearDown(self):
		_cleanup_user_conversations()
		frappe.set_user(self._orig_user)

	def _turn_count(self, conversation=None):
		return frappe.db.get_value(CONV, conversation or self.conv, "turn_count")

	def _set_turns(self, n, conversation=None):
		frappe.db.set_value(CONV, conversation or self.conv, "turn_count", n, update_modified=False)


class TestTurnCounter(_SessionFeedbackTestCase):
	def test_turn_count_increments_once_per_bump(self):
		for _ in range(3):
			_bump_turn_count(self.conv)
		self.assertEqual(self._turn_count(), 3)

	def test_turn_count_never_counts_messages(self):
		"""The counter is MAINTAINED, not a live COUNT(*) over the message table:
		it advances with zero Jarvis Chat Message rows in the conversation, which
		a COUNT(*)-derived value could not do."""
		_bump_turn_count(self.conv)
		self.assertEqual(frappe.db.count(MSG, {"conversation": self.conv}), 0)
		self.assertEqual(self._turn_count(), 1)

	def test_file_box_conversation_is_not_counted(self):
		# Server-set path: the controller gates a generic save that ENABLES
		# file_box, exactly as the real File Box drop path bypasses it.
		frappe.db.set_value(CONV, self.conv, "file_box", 1, update_modified=False)
		_bump_turn_count(self.conv)
		self.assertEqual(self._turn_count(), 0)

	def test_bump_never_raises_on_a_missing_conversation(self):
		# A settled turn whose conversation was deleted must not cost the turn its
		# terminal publish; the bump swallows and logs instead.
		_bump_turn_count("does-not-exist")


class TestSessionFeedbackStatus(_SessionFeedbackTestCase):
	def test_not_due_below_threshold(self):
		self._set_turns(SESSION_FEEDBACK_TURN_THRESHOLD - 1)
		self.assertFalse(session_feedback_status(self.conv)["due"])

	def test_due_at_threshold(self):
		self._set_turns(SESSION_FEEDBACK_TURN_THRESHOLD)
		self.assertTrue(session_feedback_status(self.conv)["due"])

	def test_still_due_above_threshold(self):
		self._set_turns(SESSION_FEEDBACK_TURN_THRESHOLD + 5)
		self.assertTrue(session_feedback_status(self.conv)["due"])

	def test_file_box_conversation_never_due(self):
		frappe.db.set_value(CONV, self.conv, "file_box", 1, update_modified=False)
		self._set_turns(999)
		self.assertFalse(session_feedback_status(self.conv)["due"])

	def test_rejects_another_users_conversation(self):
		frappe.set_user("Administrator")
		other = create_conversation()
		frappe.set_user(TEST_USER)
		try:
			with self.assertRaises(frappe.PermissionError):
				session_feedback_status(other)
		finally:
			frappe.set_user("Administrator")
			_delete_conv(other)
			frappe.set_user(TEST_USER)


class TestSubmitSessionFeedback(_SessionFeedbackTestCase):
	def setUp(self):
		super().setUp()
		self._set_turns(SESSION_FEEDBACK_TURN_THRESHOLD)

	def _item(self, push):
		push.assert_called_once()
		return push.call_args.args[0]

	def test_chip_forwards_derived_payload(self):
		with patch(_PUSH) as push:
			res = submit_session_feedback(self.conv, "Good")
		self.assertEqual(res, {"ok": True, "recorded": True})
		item = self._item(push)
		self.assertEqual(item["kind"], "Session")
		self.assertEqual(item["session_ref"], self.conv)
		self.assertEqual(item["chip_value"], "Good")
		self.assertEqual(item["user_ref"], TEST_USER)
		self.assertEqual(item["note"], "")

	def test_answering_stamps_asked_and_the_popup_never_fires_again(self):
		with patch(_PUSH):
			submit_session_feedback(self.conv, "Good")
		self.assertTrue(frappe.db.get_value(CONV, self.conv, "session_feedback_asked_at"))
		self.assertFalse(session_feedback_status(self.conv)["due"])

	def test_skip_stamps_asked_without_recording_or_forwarding(self):
		with patch(_PUSH) as push:
			res = submit_session_feedback(self.conv)
		self.assertEqual(res, {"ok": True, "recorded": False})
		push.assert_not_called()
		self.assertTrue(frappe.db.get_value(CONV, self.conv, "session_feedback_asked_at"))
		self.assertFalse(session_feedback_status(self.conv)["due"])

	def test_okay_or_worse_keeps_the_stripped_note(self):
		# "Okay" counts as low - the popup reveals the note field at "Okay or
		# worse", not only for the bottom two chips.
		for chip in ("Okay", "Not great", "Frustrating"):
			with self.subTest(chip=chip):
				frappe.db.set_value(CONV, self.conv, "session_feedback_asked_at", None, update_modified=False)
				with patch(_PUSH) as push:
					submit_session_feedback(self.conv, chip, note="  it lost the thread  ")
				self.assertEqual(self._item(push)["note"], "it lost the thread")

	def test_positive_chip_never_carries_a_note(self):
		for chip in ("Great", "Good"):
			with self.subTest(chip=chip):
				with patch(_PUSH) as push:
					submit_session_feedback(self.conv, chip, note="should be dropped")
				self.assertEqual(self._item(push)["note"], "")

	def test_note_is_bounded(self):
		with patch(_PUSH) as push:
			submit_session_feedback(self.conv, "Frustrating", note="x" * 5000)
		self.assertEqual(len(self._item(push)["note"]), 1000)

	def test_rejects_invalid_chip_value_without_burning_the_popup(self):
		with patch(_PUSH) as push:
			with self.assertRaises(frappe.ValidationError):
				submit_session_feedback(self.conv, "not-a-real-chip")
		push.assert_not_called()
		# A broken client must not consume the user's one chance to answer.
		self.assertFalse(frappe.db.get_value(CONV, self.conv, "session_feedback_asked_at"))
		self.assertTrue(session_feedback_status(self.conv)["due"])

	def test_a_failed_forward_never_surfaces(self):
		with patch(_PUSH, side_effect=RuntimeError("admin down")):
			res = submit_session_feedback(self.conv, "Great")
		self.assertEqual(res, {"ok": True, "recorded": True})

	def test_rejects_another_users_conversation(self):
		frappe.set_user("Administrator")
		other = create_conversation()
		frappe.set_user(TEST_USER)
		try:
			with patch(_PUSH) as push:
				with self.assertRaises(frappe.PermissionError):
					submit_session_feedback(other, "Good")
			push.assert_not_called()
			self.assertFalse(frappe.db.get_value(CONV, other, "session_feedback_asked_at"))
		finally:
			frappe.set_user("Administrator")
			_delete_conv(other)
			frappe.set_user(TEST_USER)
