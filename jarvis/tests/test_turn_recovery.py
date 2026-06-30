"""Tests for jarvis.chat.turn_recovery (scheduler-driven long-turn recovery)."""
import contextlib
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat import turn_recovery
from jarvis.chat.turn_recovery import MSG as MSG_DT


class TestTurnRecovery(FrappeTestCase):
	def setUp(self):
		# Clean slate so the scan only sees our row (neutralise any leftovers).
		frappe.db.sql(
			"UPDATE `tabJarvis Chat Message` SET streaming=0, recovering=0 "
			"WHERE streaming=1 OR recovering=1"
		)
		self.conv = frappe.get_doc({
			"doctype": "Jarvis Conversation", "title": "rec", "session_key": "sk_rec",
		}).insert(ignore_permissions=True)
		self.msg = frappe.get_doc({
			"doctype": "Jarvis Chat Message",
			"conversation": self.conv.name, "seq": 1, "role": "assistant",
			"content": "partial...", "streaming": 1, "recovering": 1,
			"recovery_started_at": frappe.utils.add_to_date(
				frappe.utils.now_datetime(), minutes=-10),
		}).insert(ignore_permissions=True)
		frappe.db.commit()

	def tearDown(self):
		frappe.db.delete(MSG_DT, {"conversation": self.conv.name})
		frappe.db.delete(turn_recovery.CONV, {"name": self.conv.name})
		frappe.db.commit()

	def _run(self, sess):
		@contextlib.contextmanager
		def fake_conn(_gateway_url):
			yield sess

		settings = MagicMock()
		settings.agent_url = "https://gw.example"
		with patch("jarvis.selfhost.is_self_hosted", return_value=False), \
			 patch("jarvis.chat.turn_recovery.frappe.get_single", return_value=settings), \
			 patch("jarvis.chat.turn_recovery._recovery_connection", fake_conn), \
			 patch("jarvis.chat.turn_recovery.publish_to_user") as pub:
			out = turn_recovery.recover_pending_turns()
		return out, pub

	def _row(self):
		return frappe.db.get_value(
			MSG_DT, self.msg.name,
			["content", "streaming", "recovering", "error"], as_dict=True,
		)

	def test_finalizes_when_run_done_with_text(self):
		sess = MagicMock()
		sess.is_run_active.return_value = False
		sess.get_history.return_value = {"messages": [
			{"role": "user", "content": "q", "__openclaw": {"seq": 1}},
			{"role": "assistant", "content": "the full answer", "__openclaw": {"seq": 2}},
		]}
		out, pub = self._run(sess)
		self.assertEqual(out.get("finalized"), 1)
		row = self._row()
		self.assertEqual(row.content, "the full answer")  # overwrite, not append
		self.assertEqual(row.streaming, 0)
		self.assertEqual(row.recovering, 0)
		self.assertFalse(row.error)
		kinds = [c.args[1]["kind"] for c in pub.call_args_list]
		self.assertIn("assistant:delta", kinds)
		self.assertIn("run:end", kinds)

	def test_leaves_active_run_untouched(self):
		sess = MagicMock()
		sess.is_run_active.return_value = True
		out, _ = self._run(sess)
		self.assertEqual(out.get("active"), 1)
		row = self._row()
		self.assertEqual(row.recovering, 1)
		self.assertEqual(row.streaming, 1)

	def test_errors_when_done_no_output_past_grace(self):
		sess = MagicMock()
		sess.is_run_active.return_value = False
		sess.get_history.return_value = {"messages": []}
		out, pub = self._run(sess)
		self.assertEqual(out.get("errored"), 1)
		row = self._row()
		self.assertEqual(row.streaming, 0)
		self.assertEqual(row.recovering, 0)
		self.assertTrue(row.error)
		self.assertIn("run:error", [c.args[1]["kind"] for c in pub.call_args_list])

	def test_extract_latest_assistant_text_handles_block_list(self):
		text = turn_recovery._latest_assistant_text([
			{"role": "assistant", "__openclaw": {"seq": 5},
			 "content": [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]},
		])
		self.assertEqual(text, "hello\nworld")
