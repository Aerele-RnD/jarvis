"""Tests for jarvis.chat.stale_scan.scan_and_mark_errored.

Runs as the fixture user ``TEST_USER`` so it never wipes Administrator's
chat history on a dev site.
"""

from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from jarvis.chat.api import create_conversation
from jarvis.chat.stale_scan import scan_and_mark_errored
from jarvis.tests.test_chat_api import (
	TEST_USER,
	_cleanup_user_conversations,
	_ensure_test_user,
)

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"


class TestScanAndMarkErrored(FrappeTestCase):
	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()
		self.conv = create_conversation()

	def tearDown(self):
		_cleanup_user_conversations()
		frappe.set_user(self._orig_user)

	def _insert_stale_streaming_message(self, age_seconds: int) -> str:
		"""Insert an assistant message with streaming=1 and the given age."""
		doc = frappe.get_doc({
			"doctype": MSG,
			"conversation": self.conv,
			"seq": 1,
			"role": "assistant",
			"content": "partial",
			"streaming": 1,
		})
		doc.insert(ignore_permissions=True)
		# Forcibly age the creation timestamp (use Frappe's local-time helper
		# to match how scan_and_mark_errored computes the cutoff)
		old = now_datetime() - timedelta(seconds=age_seconds)
		frappe.db.sql(
			"UPDATE `tabJarvis Chat Message` SET creation = %s WHERE name = %s",
			(old, doc.name),
		)
		frappe.db.commit()
		return doc.name

	def test_marks_old_streaming_messages_errored(self):
		name = self._insert_stale_streaming_message(age_seconds=300)
		with patch("jarvis.chat.stale_scan.publish_to_user") as pub:
			scan_and_mark_errored()
		doc = frappe.get_doc(MSG, name)
		self.assertEqual(doc.streaming, 0)
		self.assertIn("abandoned", doc.error.lower())
		pub.assert_called_once()
		self.assertEqual(pub.call_args.args[1]["kind"], "run:error")

	def test_leaves_fresh_streaming_messages_alone(self):
		name = self._insert_stale_streaming_message(age_seconds=30)
		scan_and_mark_errored()
		doc = frappe.get_doc(MSG, name)
		self.assertEqual(doc.streaming, 1)
		self.assertIsNone(doc.error)

	def test_leaves_completed_messages_alone(self):
		doc = frappe.get_doc({
			"doctype": MSG,
			"conversation": self.conv,
			"seq": 1,
			"role": "assistant",
			"content": "done",
			"streaming": 0,
		})
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		scan_and_mark_errored()
		doc.reload()
		self.assertEqual(doc.streaming, 0)
		self.assertIsNone(doc.error)

	def test_promotes_managed_streaming_to_recovering(self):
		# A stale streaming row whose conversation has a gateway session_key is
		# recoverable: promoted to recovering (handed to turn_recovery), NOT
		# errored. Covers a worker hard-killed before it could mark recovering.
		# Past the 720s managed cap so it is definitely orphaned, not live.
		frappe.db.set_value(CONV, self.conv, "session_key", "sk_managed")
		frappe.db.commit()
		name = self._insert_stale_streaming_message(age_seconds=800)
		with patch("jarvis.selfhost.is_self_hosted", return_value=False), \
			 patch("jarvis.chat.stale_scan.publish_to_user") as pub:
			scan_and_mark_errored()
		doc = frappe.get_doc(MSG, name)
		self.assertEqual(doc.streaming, 1)   # spinner stays up
		self.assertEqual(doc.recovering, 1)  # handed to turn_recovery
		self.assertIsNone(doc.error)
		pub.assert_not_called()              # no false run:error
