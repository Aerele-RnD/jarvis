"""Tests for jarvis.chat.turn_recovery (scheduler-driven long-turn recovery).

Isolation note: the test conversation uses a UNIQUE session_key and the fake
gateway returns transcript content only for that key, so any unrelated
recovering rows on the test site are left in the waiting state untouched. No
destructive global cleanup is needed.
"""
import contextlib
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat import turn_recovery
from jarvis.chat.turn_recovery import MSG as MSG_DT

SK = "sk_rec_unique_test"


class TestTurnRecovery(FrappeTestCase):
	def setUp(self):
		self.conv = frappe.get_doc({
			"doctype": "Jarvis Conversation", "title": "rec", "session_key": SK,
		}).insert(ignore_permissions=True)
		self.msg = self._add_msg(seq=1, started_min=-10)
		frappe.db.commit()

	def tearDown(self):
		frappe.db.delete(MSG_DT, {"conversation": self.conv.name})
		frappe.db.delete(turn_recovery.CONV, {"name": self.conv.name})
		frappe.db.commit()

	def _add_msg(self, seq, started_min, content="partial..."):
		return frappe.get_doc({
			"doctype": "Jarvis Chat Message",
			"conversation": self.conv.name, "seq": seq, "role": "assistant",
			"content": content, "streaming": 1, "recovering": 1,
			"recovery_started_at": frappe.utils.add_to_date(
				frappe.utils.now_datetime(), minutes=started_min),
		}).insert(ignore_permissions=True)

	def _fake_sess(self, *, active=None, messages_by_key=None):
		active = active or set()
		messages_by_key = messages_by_key or {}
		sess = MagicMock()

		def _request(method, params, *, timeout_s):
			if method == "sessions.list":
				return {"payload": {"sessions": [
					{"key": k, "hasActiveRun": True} for k in active]}}
			return {"payload": {}}

		sess._request = _request
		sess.get_session_messages = lambda key, limit=50: messages_by_key.get(key, [])
		sess.is_run_active = lambda key, timeout_s=None: key in active
		return sess

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

	def _run_now(self, sess, conv_id=None):
		@contextlib.contextmanager
		def fake_conn(_gateway_url):
			yield sess

		settings = MagicMock()
		settings.agent_url = "https://gw.example"
		with patch("jarvis.selfhost.is_self_hosted", return_value=False), \
			 patch("jarvis.chat.turn_recovery.frappe.get_single", return_value=settings), \
			 patch("jarvis.chat.turn_recovery._recovery_connection", fake_conn), \
			 patch("jarvis.chat.turn_recovery.publish_to_user") as pub:
			out = turn_recovery.recover_now(conv_id or self.conv.name)
		return out, pub

	def _row(self, name=None):
		return frappe.db.get_value(
			MSG_DT, name or self.msg.name,
			["content", "streaming", "recovering", "error"], as_dict=True)

	# --- finalize from the RAW transcript (no truncation), overwrite ---------
	def test_finalizes_when_run_done_with_text(self):
		sess = self._fake_sess(messages_by_key={SK: [
			{"role": "user", "content": "q", "__openclaw": {"seq": 1}},
			{"role": "assistant", "content": "the full answer", "__openclaw": {"seq": 2}},
		]})
		_, pub = self._run(sess)
		row = self._row()
		self.assertEqual(row.content, "the full answer")  # overwrite, not append
		self.assertEqual(row.streaming, 0)
		self.assertEqual(row.recovering, 0)
		self.assertFalse(row.error)
		kinds = [c.args[1]["kind"] for c in pub.call_args_list]
		self.assertIn("assistant:delta", kinds)
		self.assertIn("run:end", kinds)

	def test_uses_raw_session_messages_not_truncating_history(self):
		# Content must come from get_session_messages (raw), never get_history (#1).
		sess = self._fake_sess(messages_by_key={SK: [
			{"role": "assistant", "content": "x", "__openclaw": {"seq": 1}}]})
		self._run(sess)
		sess.get_history.assert_not_called()

	def test_leaves_active_run_untouched(self):
		sess = self._fake_sess(active={SK}, messages_by_key={SK: [
			{"role": "assistant", "content": "x", "__openclaw": {"seq": 1}}]})
		self._run(sess)
		row = self._row()
		self.assertEqual(row.recovering, 1)
		self.assertEqual(row.streaming, 1)

	def test_waits_when_no_output_yet_does_not_error(self):
		# Not active, no transcript content -> wait (NOT errored before ceiling).
		sess = self._fake_sess(messages_by_key={SK: []})
		_, pub = self._run(sess)
		row = self._row()
		self.assertEqual(row.streaming, 1)
		self.assertEqual(row.recovering, 1)
		self.assertFalse(row.error)
		self.assertNotIn("run:error", [c.args[1]["kind"] for c in pub.call_args_list])

	# --- #3/#5: unconditional ceiling backstop, even when gateway is down ----
	def test_ceiling_errors_even_when_gateway_unreachable(self):
		old = self._add_msg(seq=2, started_min=-120)  # 2h, past the 60min ceiling
		frappe.db.commit()

		def boom(_url):
			raise RuntimeError("gateway down")

		settings = MagicMock()
		settings.agent_url = "https://gw.example"
		with patch("jarvis.selfhost.is_self_hosted", return_value=False), \
			 patch("jarvis.chat.turn_recovery.frappe.get_single", return_value=settings), \
			 patch("jarvis.chat.turn_recovery._recovery_connection", boom), \
			 patch("jarvis.chat.turn_recovery.publish_to_user"):
			turn_recovery.recover_pending_turns()
		row = self._row(old.name)
		self.assertEqual(row.streaming, 0)  # errored despite gateway down
		self.assertEqual(row.recovering, 0)
		self.assertTrue(row.error)

	# --- #2: no cross-row content bleed -------------------------------------
	def test_no_cross_row_bleed_only_latest_finalized(self):
		older = self.msg  # seq 1
		newer = self._add_msg(seq=2, started_min=-10, content="partial2")
		frappe.db.commit()
		sess = self._fake_sess(messages_by_key={SK: [
			{"role": "assistant", "content": "latest answer", "__openclaw": {"seq": 9}}]})
		self._run(sess)
		self.assertEqual(self._row(newer.name).content, "latest answer")
		older_row = self._row(older.name)
		self.assertNotEqual(older_row.content, "latest answer")  # no bleed
		self.assertEqual(older_row.streaming, 1)  # older rides the ceiling backstop

	# --- #8: conditional finalize is idempotent -----------------------------
	def test_conditional_finalize_no_op_on_already_cleared_row(self):
		frappe.db.set_value(MSG_DT, self.msg.name, {"streaming": 0, "recovering": 0})
		frappe.db.commit()
		pub = MagicMock()
		with patch("jarvis.chat.turn_recovery.publish_to_user", pub):
			turn_recovery._finalize(
				{"name": self.msg.name, "conversation": self.conv.name, "owner": "x"},
				"ignored")
		pub.assert_not_called()
		self.assertNotEqual(self._row().content, "ignored")

	# --- #10: type-guarded extraction ---------------------------------------
	def test_extract_latest_assistant_text_handles_block_list(self):
		text = turn_recovery._latest_assistant_text([
			{"role": "assistant", "__openclaw": {"seq": 5},
			 "content": [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]}])
		self.assertEqual(text, "hello\nworld")

	def test_extract_ignores_non_string_text(self):
		text = turn_recovery._latest_assistant_text([
			{"role": "assistant", "__openclaw": {"seq": 5},
			 "content": [{"type": "text", "text": {"unexpected": "dict"}}], "text": 123}])
		self.assertEqual(text, "")

	# --- recover_now: in-worker immediate recovery --------------------------
	def test_recover_now_finalizes_when_run_done_with_text(self):
		sess = self._fake_sess(messages_by_key={SK: [
			{"role": "assistant", "content": "the full answer", "__openclaw": {"seq": 2}},
		]})
		out, pub = self._run_now(sess)
		self.assertEqual(out, "finalized")
		row = self._row()
		self.assertEqual(row.content, "the full answer")
		self.assertEqual(row.streaming, 0)
		self.assertEqual(row.recovering, 0)
		self.assertFalse(row.error)
		kinds = [c.args[1]["kind"] for c in pub.call_args_list]
		self.assertIn("assistant:delta", kinds)
		self.assertIn("run:end", kinds)
		run_ids = {c.args[1].get("run_id") for c in pub.call_args_list}
		self.assertEqual(run_ids, {"recovered"})

	def test_recover_now_leaves_active_run_untouched(self):
		sess = self._fake_sess(active={SK}, messages_by_key={SK: [
			{"role": "assistant", "content": "x", "__openclaw": {"seq": 1}}]})
		out, pub = self._run_now(sess)
		self.assertEqual(out, "active")
		row = self._row()
		self.assertEqual(row.streaming, 1)
		self.assertEqual(row.recovering, 1)
		pub.assert_not_called()

	def test_recover_now_waits_when_transcript_empty(self):
		sess = self._fake_sess(messages_by_key={SK: []})
		out, pub = self._run_now(sess)
		self.assertEqual(out, "waiting")
		row = self._row()
		self.assertEqual(row.streaming, 1)
		self.assertEqual(row.recovering, 1)
		pub.assert_not_called()

	def test_recover_now_skipped_when_no_recovering_row(self):
		other = frappe.get_doc({
			"doctype": "Jarvis Conversation", "title": "rec-other",
			"session_key": "sk_rec_other_test",
		}).insert(ignore_permissions=True)
		frappe.db.commit()
		try:
			sess = self._fake_sess()
			out, pub = self._run_now(sess, conv_id=other.name)
			self.assertEqual(out, "skipped")
			pub.assert_not_called()
		finally:
			frappe.db.delete(turn_recovery.CONV, {"name": other.name})
			frappe.db.commit()

	def test_recover_now_skipped_when_self_hosted(self):
		with patch("jarvis.selfhost.is_self_hosted", return_value=True), \
			 patch("jarvis.chat.turn_recovery.publish_to_user") as pub:
			out = turn_recovery.recover_now(self.conv.name)
		self.assertEqual(out, "skipped")
		pub.assert_not_called()
		row = self._row()
		self.assertEqual(row.streaming, 1)
		self.assertEqual(row.recovering, 1)

	def test_recover_now_skipped_on_connect_failure(self):
		def boom(_url):
			raise RuntimeError("gateway down")

		settings = MagicMock()
		settings.agent_url = "https://gw.example"
		with patch("jarvis.selfhost.is_self_hosted", return_value=False), \
			 patch("jarvis.chat.turn_recovery.frappe.get_single", return_value=settings), \
			 patch("jarvis.chat.turn_recovery._recovery_connection", boom), \
			 patch("jarvis.chat.turn_recovery.publish_to_user") as pub:
			out = turn_recovery.recover_now(self.conv.name)
		self.assertEqual(out, "skipped")
		pub.assert_not_called()
		row = self._row()
		self.assertEqual(row.streaming, 1)
		self.assertEqual(row.recovering, 1)

	# --- macro chaining hook: finalize/error must advance a running macro ---
	def test_finalize_advances_macro_with_errored_false(self):
		sess = self._fake_sess(messages_by_key={SK: [
			{"role": "assistant", "content": "the full answer", "__openclaw": {"seq": 2}},
		]})
		with patch("jarvis.chat.macros.advance_after_turn") as advance:
			self._run(sess)
		advance.assert_called_once_with(self.conv.name, errored=False)

	def test_error_advances_macro_with_errored_true(self):
		old = self._add_msg(seq=2, started_min=-120)  # past the ceiling -> _error
		frappe.db.commit()

		def boom(_url):
			raise RuntimeError("gateway down")

		settings = MagicMock()
		settings.agent_url = "https://gw.example"
		with patch("jarvis.selfhost.is_self_hosted", return_value=False), \
			 patch("jarvis.chat.turn_recovery.frappe.get_single", return_value=settings), \
			 patch("jarvis.chat.turn_recovery._recovery_connection", boom), \
			 patch("jarvis.chat.turn_recovery.publish_to_user"), \
			 patch("jarvis.chat.macros.advance_after_turn") as advance:
			turn_recovery.recover_pending_turns()
		advance.assert_called_once_with(old.conversation, errored=True)

	def test_losing_conditional_clear_does_not_advance_macro(self):
		# Row already cleared by another cycle: _conditional_clear returns
		# False, so _finalize must return before ever touching the macro.
		frappe.db.set_value(MSG_DT, self.msg.name, {"streaming": 0, "recovering": 0})
		frappe.db.commit()
		with patch("jarvis.chat.turn_recovery.publish_to_user"), \
			 patch("jarvis.chat.macros.advance_after_turn") as advance:
			turn_recovery._finalize(
				{"name": self.msg.name, "conversation": self.conv.name, "owner": "x"},
				"ignored")
		advance.assert_not_called()

	def test_macro_advance_exception_is_swallowed_row_still_finalized(self):
		sess = self._fake_sess(messages_by_key={SK: [
			{"role": "assistant", "content": "the full answer", "__openclaw": {"seq": 2}},
		]})
		with patch(
			"jarvis.chat.macros.advance_after_turn",
			side_effect=RuntimeError("macro engine bug"),
		), patch("frappe.log_error") as log_err:
			_, pub = self._run(sess)
		# The macro exception was logged, not raised.
		log_err.assert_called()
		# The row still finalized and the publishes still happened.
		row = self._row()
		self.assertEqual(row.content, "the full answer")
		self.assertEqual(row.streaming, 0)
		self.assertEqual(row.recovering, 0)
		kinds = [c.args[1]["kind"] for c in pub.call_args_list]
		self.assertIn("assistant:delta", kinds)
		self.assertIn("run:end", kinds)

	def test_recover_now_idempotent_after_finalize_no_double_publish(self):
		sess = self._fake_sess(messages_by_key={SK: [
			{"role": "assistant", "content": "the full answer", "__openclaw": {"seq": 2}},
		]})
		out1, pub1 = self._run_now(sess)
		self.assertEqual(out1, "finalized")
		pub1.assert_called()

		sess2 = self._fake_sess(messages_by_key={SK: [
			{"role": "assistant", "content": "the full answer", "__openclaw": {"seq": 2}},
		]})
		out2, pub2 = self._run_now(sess2)
		self.assertEqual(out2, "skipped")
		pub2.assert_not_called()
