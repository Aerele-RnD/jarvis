"""Tests for jarvis.chat.session_lifecycle (retention expiry + orphan sweep).

The daily cron archives conversations idle past the configurable retention
window (Jarvis Settings.conversation_retention_days), freeing their openclaw
session; starred and in-flight chats are exempt, and an already user-archived
chat is session-freed only. The gateway is reached only through
OpenclawSession.connect (a dedicated connection, never the pool), so tests
patch ``connect`` with a fake session exposing list_sessions/delete_session/
close. Conversations and messages are real rows on the test site.
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
SETTINGS = "Jarvis Settings"
RETENTION_FIELD = "conversation_retention_days"

NOW_MS = int(time.time() * 1000)
OLD_MS = NOW_MS - (session_lifecycle.ORPHAN_GRACE_HOURS + 2) * 3600 * 1000


def _fake_sess(entries=None):
	sess = MagicMock()
	sess.list_sessions.return_value = entries or []
	return sess


class TestSessionLifecycle(FrappeTestCase):
	def setUp(self):
		self._made = []
		# The sweep is site-global. Neutralize every pre-existing candidate so
		# only THIS test's fixtures are eligible: null all session_keys AND bump
		# all conversations to "just active" (the archive path now also selects
		# session-less idle Active chats, so parking keys alone is not enough).
		frappe.db.sql("UPDATE `tabJarvis Conversation` SET session_key = NULL")
		frappe.db.sql(
			"UPDATE `tabJarvis Conversation` SET last_active_at = %s",
			(frappe.utils.now_datetime(),),
		)
		# Residue from aborted earlier runs would 1062 on re-insert.
		frappe.db.delete(CHAT_SESSION, {"session_key": ["like", "test-lc-%"]})
		# The sweep bails without an agent_url; pin one for the run.
		self._orig_agent_url = frappe.db.get_single_value(SETTINGS, "agent_url")
		frappe.db.set_single_value(SETTINGS, "agent_url", "http://gw.test:18789")
		# Default retention (unset -> 30); tests override where needed.
		frappe.db.set_single_value(SETTINGS, RETENTION_FIELD, None)
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		frappe.db.commit()
		# Realtime is a best-effort nudge; mock it so tests are hermetic and can
		# assert the conversation:expired push.
		patcher = patch("jarvis.chat.events.publish_to_user")
		self.pub = patcher.start()
		self.addCleanup(patcher.stop)

	def tearDown(self):
		for name in self._made:
			frappe.db.delete(MSG, {"conversation": name})
			frappe.db.delete(CONV, {"name": name})
		frappe.db.delete(CHAT_SESSION, {"session_key": ["like", "test-lc-%"]})
		frappe.db.set_single_value(SETTINGS, "agent_url", self._orig_agent_url or "")
		frappe.db.set_single_value(SETTINGS, RETENTION_FIELD, None)
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		frappe.db.commit()

	def _conv(self, *, session_key=None, idle_days, streaming=False,
	          starred=0, status="Active"):
		doc = frappe.get_doc({
			"doctype": CONV, "title": f"lc-{session_key or idle_days}",
			"starred": starred, "status": status,
		}).insert(ignore_permissions=True)
		self._made.append(doc.name)
		fields = {"last_active_at": frappe.utils.add_to_date(
			frappe.utils.now_datetime(), days=-idle_days)}
		if session_key:
			fields["session_key"] = session_key
		frappe.db.set_value(CONV, doc.name, fields)
		if streaming:
			frappe.get_doc({
				"doctype": MSG, "conversation": doc.name, "seq": 1,
				"role": "assistant", "content": "", "streaming": 1,
			}).insert(ignore_permissions=True)
		if session_key:
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

	def _get(self, name, field):
		return frappe.db.get_value(CONV, name, field)

	# ---- retention window reader ------------------------------------

	def test_retention_days_unset_defaults_to_30(self):
		frappe.db.set_single_value(SETTINGS, RETENTION_FIELD, None)
		self.assertEqual(session_lifecycle._retention_days(), 30)

	def test_retention_days_zero_disables(self):
		frappe.db.set_single_value(SETTINGS, RETENTION_FIELD, 0)
		self.assertEqual(session_lifecycle._retention_days(), 0)

	def test_retention_days_below_floor_clamped(self):
		frappe.db.set_single_value(SETTINGS, RETENTION_FIELD, 3)
		self.assertEqual(session_lifecycle._retention_days(), 7)

	# ---- retention expiry (archive) ---------------------------------

	def test_dormant_active_with_session_is_archived_and_freed(self):
		name = self._conv(session_key="test-lc-dormant", idle_days=40)
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["archived"], 1)
		self.assertEqual(summary["sessions_freed"], 1)
		sess.delete_session.assert_any_call("test-lc-dormant")
		self.assertEqual(self._get(name, "status"), "Archived")
		self.assertEqual(self._get(name, "auto_expired"), 1)
		self.assertTrue(self._get(name, "expired_at"))
		self.assertFalse(self._get(name, "session_key"))
		self.assertFalse(frappe.db.exists(CHAT_SESSION, {"session_key": "test-lc-dormant"}))
		# The owner gets a conversation:expired nudge so an open tab drops the row.
		self.pub.assert_called_once()
		self.assertEqual(self.pub.call_args[0][1]["kind"], "conversation:expired")
		self.assertEqual(self.pub.call_args[0][1]["conversation_id"], name)

	def test_dormant_active_without_session_is_archived(self):
		name = self._conv(idle_days=40)  # never had an agent turn
		summary = self._run(_fake_sess())
		self.assertEqual(summary["archived"], 1)
		self.assertEqual(summary["sessions_freed"], 0)
		self.assertEqual(self._get(name, "status"), "Archived")
		self.assertEqual(self._get(name, "auto_expired"), 1)
		self.pub.assert_called_once()

	def test_starred_is_exempt(self):
		name = self._conv(session_key="test-lc-star", idle_days=40, starred=1)
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["archived"], 0)
		sess.delete_session.assert_not_called()
		self.assertEqual(self._get(name, "status"), "Active")
		self.assertEqual(self._get(name, "session_key"), "test-lc-star")  # kept, session and all
		self.pub.assert_not_called()

	def test_user_archived_with_session_is_freed_only(self):
		name = self._conv(session_key="test-lc-uarch", idle_days=40, status="Archived")
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["sessions_freed"], 1)
		self.assertEqual(summary["archived"], 0)          # already archived - not re-counted
		sess.delete_session.assert_any_call("test-lc-uarch")
		self.assertEqual(self._get(name, "status"), "Archived")
		self.assertFalse(self._get(name, "session_key"))  # session reclaimed
		self.assertEqual(self._get(name, "auto_expired"), 0)  # NOT a retention expiry
		self.pub.assert_not_called()

	def test_two_expiries_in_one_run_no_unique_collision(self):
		"""Regression: session_key is UNIQUE; clearing to '' (instead of NULL)
		collided on the SECOND expiry of a run (1062)."""
		a = self._conv(session_key="test-lc-two-a", idle_days=40)
		b = self._conv(session_key="test-lc-two-b", idle_days=41)
		summary = self._run(_fake_sess())
		self.assertEqual(summary["archived"], 2)
		self.assertFalse(self._get(a, "session_key"))
		self.assertFalse(self._get(b, "session_key"))

	def test_fresh_conversation_untouched(self):
		name = self._conv(session_key="test-lc-fresh", idle_days=2)
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["archived"], 0)
		sess.delete_session.assert_not_called()
		self.assertEqual(self._get(name, "status"), "Active")
		self.assertEqual(self._get(name, "session_key"), "test-lc-fresh")

	def test_dormant_with_inflight_row_skipped(self):
		name = self._conv(session_key="test-lc-busy", idle_days=40, streaming=True)
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["archived"], 0)
		sess.delete_session.assert_not_called()
		self.assertEqual(self._get(name, "status"), "Active")

	def test_retention_disabled_is_noop(self):
		frappe.db.set_single_value(SETTINGS, RETENTION_FIELD, 0)
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		frappe.db.commit()
		name = self._conv(session_key="test-lc-dis", idle_days=99)
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["archived"], 0)
		sess.delete_session.assert_not_called()
		self.assertEqual(self._get(name, "status"), "Active")
		self.assertEqual(self._get(name, "session_key"), "test-lc-dis")

	def test_gateway_delete_failure_keeps_row_intact(self):
		"""A failed sessions.delete must leave the conversation Active with its
		session_key + lookup row so the next run retries - archiving it would
		hide it from the only sweep that re-selects it."""
		name = self._conv(session_key="test-lc-fail", idle_days=40)
		sess = _fake_sess()
		sess.delete_session.side_effect = RuntimeError("gateway said no")
		with patch("frappe.log_error"):
			summary = self._run(sess)
		self.assertEqual(summary["archived"], 0)
		self.assertEqual(summary["errors"], 1)
		self.assertEqual(self._get(name, "status"), "Active")
		self.assertEqual(self._get(name, "session_key"), "test-lc-fail")
		self.assertTrue(frappe.db.exists(CHAT_SESSION, {"session_key": "test-lc-fail"}))
		self.pub.assert_not_called()

	def test_not_found_delete_treated_as_success(self):
		"""Idempotent cleanup: a session already gone (a prior run crashed
		between the gateway delete and the local commit) counts as deleted, so
		the chat still archives instead of retry-failing forever."""
		name = self._conv(session_key="test-lc-gone", idle_days=40)
		sess = _fake_sess()
		sess.delete_session.side_effect = RuntimeError(
			"gateway error: session not found: test-lc-gone")
		summary = self._run(sess)
		self.assertEqual(summary["archived"], 1)
		self.assertEqual(summary["errors"], 0)
		self.assertEqual(self._get(name, "status"), "Archived")
		self.assertFalse(self._get(name, "session_key"))

	def test_one_bad_row_does_not_abort_the_batch(self):
		"""Per-row isolation (turn_recovery's loop pattern): a bench-side write
		failure on row 1 logs and continues to row 2."""
		a = self._conv(session_key="test-lc-bad", idle_days=41)
		b = self._conv(session_key="test-lc-good", idle_days=40)
		sess = _fake_sess()
		real_set_value = frappe.db.set_value

		def flaky_set_value(dt, name, *args, **kwargs):
			if name == a:
				raise RuntimeError("simulated deadlock")
			return real_set_value(dt, name, *args, **kwargs)

		with patch("frappe.db.set_value", side_effect=flaky_set_value), \
		     patch("frappe.log_error") as log_err:
			summary = self._run(sess)
		self.assertEqual(summary["archived"], 1)
		self.assertEqual(summary["errors"], 1)
		log_err.assert_called()
		self.assertEqual(self._get(b, "status"), "Archived")
		self.assertFalse(self._get(b, "session_key"))

	def test_secondary_delete_failure_rolls_back_partial_archive(self):
		"""If the CHAT_SESSION lookup delete fails AFTER the conversation update
		(same uncommitted row), the except rolls back so no half-archived state
		(status=Archived + nulled key) rides to the next row's commit."""
		name = self._conv(session_key="test-lc-partial", idle_days=40)
		sess = _fake_sess()
		real_delete = frappe.db.delete

		def flaky_delete(doctype, *a, **k):
			if doctype == CHAT_SESSION:
				raise RuntimeError("lookup delete boom")
			return real_delete(doctype, *a, **k)

		with patch("frappe.db.delete", side_effect=flaky_delete), \
		     patch("frappe.log_error"):
			summary = self._run(sess)
		self.assertEqual(summary["errors"], 1)
		self.assertEqual(summary["archived"], 0)
		# Rolled back: conversation stays Active with its key, not half-archived.
		self.assertEqual(self._get(name, "status"), "Active")
		self.assertEqual(self._get(name, "session_key"), "test-lc-partial")
		self.pub.assert_not_called()

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
		# 3 expiries + only 1 orphan fit in the budget of 4.
		self.assertEqual(summary["archived"], 3)
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


class TestRetentionSettingValidation(FrappeTestCase):
	"""The floor lives in the Jarvis Settings controller so a fumbled tiny value
	can't be saved and mass-archive on the next cron. 0 (never) and unset are
	always allowed; anything 1-6 is rejected."""

	def _validate(self, val):
		s = frappe.get_single(SETTINGS)
		s.conversation_retention_days = val
		s._validate_conversation_retention()

	def test_floor_rejects_below_7(self):
		with self.assertRaises(frappe.ValidationError):
			self._validate(3)

	def test_zero_is_allowed(self):
		self._validate(0)  # never-delete sentinel

	def test_seven_is_allowed(self):
		self._validate(7)

	def test_unset_is_allowed(self):
		self._validate(None)
