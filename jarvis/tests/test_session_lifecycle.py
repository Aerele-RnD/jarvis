"""Tests for jarvis.chat.session_lifecycle (Phase 1: dormant rotation +
orphan sweep).

The sweep talks to the gateway only through OpenclawSession.connect (a
dedicated connection, never the pool), so tests patch ``connect`` with a
fake session exposing list_sessions/delete_session/close. Conversations
and messages are real rows on the test site.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat import session_lifecycle

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"
CHAT_SESSION = "Jarvis Chat Session"

NOW_MS = int(time.time() * 1000)
OLD_MS = NOW_MS - (session_lifecycle.ORPHAN_GRACE_HOURS + 2) * 3600 * 1000


def _fake_sess(entries=None):
	sess = MagicMock()
	sess.list_sessions.return_value = entries or []
	return sess


class TestSessionLifecycle(FrappeTestCase):
	def setUp(self):
		self._made = []
		# The sweep is site-global: park every pre-existing candidate so
		# only THIS test's fixtures are eligible (mirrors the recovery
		# rate-watch tests' residue-neutralizing setUp).
		frappe.db.sql(
			"UPDATE `tabJarvis Conversation` SET session_key = NULL "
			"WHERE session_key IS NOT NULL"
		)
		# Residue from aborted earlier runs would 1062 on re-insert.
		frappe.db.delete(CHAT_SESSION, {"session_key": ["like", "test-lc-%"]})
		# The sweep bails without an agent_url; pin one for the run.
		self._orig_agent_url = frappe.db.get_single_value(
			"Jarvis Settings", "agent_url")
		frappe.db.set_single_value(
			"Jarvis Settings", "agent_url", "http://gw.test:18789")
		frappe.clear_document_cache("Jarvis Settings", "Jarvis Settings")
		frappe.db.commit()

	def tearDown(self):
		for name in self._made:
			frappe.db.delete(MSG, {"conversation": name})
			frappe.db.delete(CONV, {"name": name})
		frappe.db.delete(CHAT_SESSION, {"session_key": ["like", "test-lc-%"]})
		frappe.db.set_single_value(
			"Jarvis Settings", "agent_url", self._orig_agent_url or "")
		frappe.clear_document_cache("Jarvis Settings", "Jarvis Settings")
		frappe.db.commit()

	def _conv(self, *, session_key: str, idle_days: int, streaming: bool = False):
		doc = frappe.get_doc({
			"doctype": CONV, "title": f"lc-{session_key}",
		}).insert(ignore_permissions=True)
		self._made.append(doc.name)
		frappe.db.set_value(CONV, doc.name, {
			"session_key": session_key,
			"last_active_at": frappe.utils.add_to_date(
				frappe.utils.now_datetime(), days=-idle_days),
		})
		if streaming:
			frappe.get_doc({
				"doctype": MSG, "conversation": doc.name, "seq": 1,
				"role": "assistant", "content": "", "streaming": 1,
			}).insert(ignore_permissions=True)
		frappe.get_doc({
			"doctype": CHAT_SESSION, "session_key": session_key,
			"user": "Administrator", "chat_device_id": "d1",
		}).insert(ignore_permissions=True)
		frappe.db.commit()
		return doc.name

	def _run(self, sess):
		with patch(
			"jarvis.chat.openclaw_client.OpenclawSession.connect",
			return_value=sess,
		), patch("jarvis.selfhost.is_self_hosted", return_value=False):
			return session_lifecycle.rotate_dormant_sessions()

	# ---- dormant rotation -------------------------------------------

	def test_dormant_conversation_rotated(self):
		name = self._conv(session_key="test-lc-dormant", idle_days=40)
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["dormant_rotated"], 1)
		sess.delete_session.assert_any_call("test-lc-dormant")
		self.assertFalse(frappe.db.get_value(CONV, name, "session_key"))
		self.assertFalse(
			frappe.db.exists(CHAT_SESSION, {"session_key": "test-lc-dormant"})
		)

	def test_fresh_conversation_untouched(self):
		name = self._conv(session_key="test-lc-fresh", idle_days=2)
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["dormant_rotated"], 0)
		sess.delete_session.assert_not_called()
		self.assertEqual(
			frappe.db.get_value(CONV, name, "session_key"), "test-lc-fresh"
		)

	def test_dormant_with_inflight_row_skipped(self):
		name = self._conv(
			session_key="test-lc-busy", idle_days=40, streaming=True)
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["dormant_rotated"], 0)
		sess.delete_session.assert_not_called()
		self.assertEqual(
			frappe.db.get_value(CONV, name, "session_key"), "test-lc-busy"
		)

	def test_gateway_delete_failure_keeps_bench_pointers(self):
		"""A failed sessions.delete must leave session_key and the lookup
		row intact so the next run retries."""
		name = self._conv(session_key="test-lc-fail", idle_days=40)
		sess = _fake_sess()
		sess.delete_session.side_effect = RuntimeError("gateway said no")
		with patch("frappe.log_error"):
			summary = self._run(sess)
		self.assertEqual(summary["dormant_rotated"], 0)
		self.assertEqual(summary["errors"], 1)
		self.assertEqual(
			frappe.db.get_value(CONV, name, "session_key"), "test-lc-fail"
		)
		self.assertTrue(
			frappe.db.exists(CHAT_SESSION, {"session_key": "test-lc-fail"})
		)

	# ---- orphan sweep -----------------------------------------------

	def test_orphan_throwaway_reaped(self):
		sess = _fake_sess(entries=[{
			"key": "test-lc-orph:dashboard:o1",
			"hasActiveRun": False, "updatedAt": OLD_MS,
		}])
		summary = self._run(sess)
		self.assertEqual(summary["orphans_reaped"], 1)
		sess.delete_session.assert_any_call("test-lc-orph:dashboard:o1")

	def test_referenced_session_never_reaped(self):
		self._conv(session_key="test-lc-ref:dashboard:live-1", idle_days=2)
		sess = _fake_sess(entries=[{
			"key": "test-lc-ref:dashboard:live-1",
			"hasActiveRun": False, "updatedAt": OLD_MS,
		}])
		summary = self._run(sess)
		self.assertEqual(summary["orphans_reaped"], 0)
		sess.delete_session.assert_not_called()

	def test_recent_or_active_or_foreign_orphans_skipped(self):
		sess = _fake_sess(entries=[
			# Inside grace: may be an in-flight title/prewarm throwaway.
			{"key": "test-lc-orph:dashboard:young", "hasActiveRun": False,
			 "updatedAt": NOW_MS},
			# Active run: never touch.
			{"key": "test-lc-orph:dashboard:running", "hasActiveRun": True,
			 "updatedAt": OLD_MS},
			# No usable timestamp: conservative skip.
			{"key": "test-lc-orph:dashboard:nots", "hasActiveRun": False},
			# Outside the chat namespace: not ours to manage.
			{"key": "agent:main:main", "hasActiveRun": False,
			 "updatedAt": OLD_MS},
		])
		summary = self._run(sess)
		self.assertEqual(summary["orphans_reaped"], 0)
		sess.delete_session.assert_not_called()

	def test_batch_cap_bounds_total_work(self):
		for i in range(3):
			self._conv(session_key=f"test-lc-batch-{i}", idle_days=40)
		entries = [{
			"key": f"test-lc-orph:dashboard:b{i}",
			"hasActiveRun": False, "updatedAt": OLD_MS,
		} for i in range(3)]
		sess = _fake_sess(entries=entries)
		with patch.object(session_lifecycle, "BATCH_MAX", 4):
			summary = self._run(sess)
		# 3 dormant + only 1 orphan fit in the budget of 4.
		self.assertEqual(summary["dormant_rotated"], 3)
		self.assertEqual(summary["orphans_reaped"], 1)
		self.assertEqual(sess.delete_session.call_count, 4)

	# ---- gating ------------------------------------------------------

	def test_self_hosted_early_return(self):
		with patch("jarvis.selfhost.is_self_hosted", return_value=True), \
		     patch(
			"jarvis.chat.openclaw_client.OpenclawSession.connect",
		) as connect:
			summary = session_lifecycle.rotate_dormant_sessions()
		self.assertEqual(summary, {"skipped": "self-hosted"})
		connect.assert_not_called()

	def test_connect_failure_is_a_clean_skip(self):
		self._conv(session_key="test-lc-x", idle_days=40)
		with patch(
			"jarvis.chat.openclaw_client.OpenclawSession.connect",
			side_effect=RuntimeError("refused"),
		), patch("jarvis.selfhost.is_self_hosted", return_value=False), \
		     patch("frappe.log_error"):
			summary = session_lifecycle.rotate_dormant_sessions()
		self.assertEqual(summary, {"skipped": "connect failed"})
