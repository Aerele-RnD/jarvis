"""Tests for jarvis.chat.session_lifecycle (idle-session reclaim + empty-chat
+ orphan sweeps).

The daily cron (1) frees the openclaw session of conversations idle past the
configurable retention window (Jarvis Settings.conversation_retention_days) -
leaving the conversation Active and visible, only reclaiming its working memory;
(2) hard-deletes Active, non-starred, zero-message chats idle past
EMPTY_GRACE_DAYS (the abandoned "New Chat" ghost); and (3) reaps orphaned
throwaway gateway sessions. The gateway is reached only through
OpenclawSession.connect (a dedicated connection, never the pool), so tests patch
``connect`` with a fake session exposing list_sessions/delete_session/close.
Conversations and messages are real rows on the test site.
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
		# only THIS test's fixtures are eligible: null all session_keys (so no
		# pre-existing row is session-freed) AND bump all last_active_at to now
		# (so no pre-existing row is session-freed OR empty-reaped for idleness).
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
	          starred=0, status="Active", has_message=False, file_box=0):
		"""Insert a real conversation fixture.

		``has_message`` gives it a normal completed message (so it is NOT an
		empty-reap candidate - mirrors any real chat with history); ``streaming``
		gives it an in-flight message; ``file_box`` marks it a File-Box drop; the
		default is a truly empty 0-message chat.
		"""
		doc = frappe.get_doc({
			"doctype": CONV, "title": f"lc-{session_key or idle_days}",
			"starred": starred, "status": status, "file_box": file_box,
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
		elif has_message:
			frappe.get_doc({
				"doctype": MSG, "conversation": doc.name, "seq": 1,
				"role": "user", "content": "hi",
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

	# ---- free idle sessions -----------------------------------------

	def test_idle_session_freed_not_archived(self):
		name = self._conv(session_key="test-lc-dormant", idle_days=40, has_message=True)
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["sessions_freed"], 1)
		sess.delete_session.assert_any_call("test-lc-dormant")
		# The conversation stays Active and visible - only the session is freed.
		self.assertEqual(self._get(name, "status"), "Active")
		self.assertFalse(self._get(name, "session_key"))
		self.assertFalse(frappe.db.exists(CHAT_SESSION, {"session_key": "test-lc-dormant"}))
		self.assertTrue(frappe.db.exists(CONV, name))  # not deleted, not archived

	def test_starred_idle_session_freed_too(self):
		# Starred chats are NO LONGER exempt: starring pins the chat, it does not
		# keep an idle session alive for a month.
		name = self._conv(session_key="test-lc-star", idle_days=40, starred=1, has_message=True)
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["sessions_freed"], 1)
		sess.delete_session.assert_any_call("test-lc-star")
		self.assertEqual(self._get(name, "status"), "Active")
		self.assertFalse(self._get(name, "session_key"))

	def test_idle_chat_without_session_untouched(self):
		# No session to free + it has history -> the sweep leaves it entirely alone
		# (visible, unchanged). This is the case that USED to be archived.
		name = self._conv(idle_days=40, has_message=True)
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["sessions_freed"], 0)
		self.assertEqual(summary["empty_reaped"], 0)
		sess.delete_session.assert_not_called()
		self.assertEqual(self._get(name, "status"), "Active")
		self.assertTrue(frappe.db.exists(CONV, name))

	def test_fresh_session_untouched(self):
		name = self._conv(session_key="test-lc-fresh", idle_days=2, has_message=True)
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["sessions_freed"], 0)
		sess.delete_session.assert_not_called()
		self.assertEqual(self._get(name, "session_key"), "test-lc-fresh")

	def test_inflight_session_skipped(self):
		name = self._conv(session_key="test-lc-busy", idle_days=40, streaming=True)
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["sessions_freed"], 0)
		sess.delete_session.assert_not_called()
		self.assertEqual(self._get(name, "session_key"), "test-lc-busy")

	def test_retention_disabled_is_noop(self):
		frappe.db.set_single_value(SETTINGS, RETENTION_FIELD, 0)
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		frappe.db.commit()
		# A chat that would be BOTH session-freed and empty-reaped under retention:
		# disabled means neither runs.
		with_sess = self._conv(session_key="test-lc-dis", idle_days=99, has_message=True)
		empty = self._conv(idle_days=99)
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["sessions_freed"], 0)
		self.assertEqual(summary["empty_reaped"], 0)
		sess.delete_session.assert_not_called()
		self.assertEqual(self._get(with_sess, "session_key"), "test-lc-dis")
		self.assertTrue(frappe.db.exists(CONV, empty))

	def test_two_frees_in_one_run_no_unique_collision(self):
		"""Regression: session_key is UNIQUE; clearing to '' (instead of NULL)
		collided on the SECOND free of a run (1062)."""
		a = self._conv(session_key="test-lc-two-a", idle_days=40, has_message=True)
		b = self._conv(session_key="test-lc-two-b", idle_days=41, has_message=True)
		summary = self._run(_fake_sess())
		self.assertEqual(summary["sessions_freed"], 2)
		self.assertFalse(self._get(a, "session_key"))
		self.assertFalse(self._get(b, "session_key"))

	def test_gateway_delete_failure_keeps_row_intact(self):
		"""A failed sessions.delete must leave the conversation with its
		session_key + lookup row so the next run retries."""
		name = self._conv(session_key="test-lc-fail", idle_days=40, has_message=True)
		sess = _fake_sess()
		sess.delete_session.side_effect = RuntimeError("gateway said no")
		with patch("frappe.log_error"):
			summary = self._run(sess)
		self.assertEqual(summary["sessions_freed"], 0)
		self.assertEqual(summary["errors"], 1)
		self.assertEqual(self._get(name, "session_key"), "test-lc-fail")
		self.assertTrue(frappe.db.exists(CHAT_SESSION, {"session_key": "test-lc-fail"}))

	def test_not_found_delete_treated_as_success(self):
		"""Idempotent cleanup: a session already gone (a prior run crashed
		between the gateway delete and the local commit) counts as freed, so the
		bench pointers finally clear instead of retry-failing forever."""
		name = self._conv(session_key="test-lc-gone", idle_days=40, has_message=True)
		sess = _fake_sess()
		sess.delete_session.side_effect = RuntimeError(
			"gateway error: session not found: test-lc-gone")
		summary = self._run(sess)
		self.assertEqual(summary["sessions_freed"], 1)
		self.assertEqual(summary["errors"], 0)
		self.assertFalse(self._get(name, "session_key"))

	def test_one_bad_row_does_not_abort_the_batch(self):
		"""Per-row isolation (turn_recovery's loop pattern): a bench-side write
		failure on row 1 logs and continues to row 2."""
		a = self._conv(session_key="test-lc-bad", idle_days=41, has_message=True)
		b = self._conv(session_key="test-lc-good", idle_days=40, has_message=True)
		sess = _fake_sess()
		real_set_value = frappe.db.set_value

		def flaky_set_value(dt, name, *args, **kwargs):
			if name == a:
				raise RuntimeError("simulated deadlock")
			return real_set_value(dt, name, *args, **kwargs)

		with patch("frappe.db.set_value", side_effect=flaky_set_value), \
		     patch("frappe.log_error") as log_err:
			summary = self._run(sess)
		self.assertEqual(summary["sessions_freed"], 1)
		self.assertEqual(summary["errors"], 1)
		log_err.assert_called()
		self.assertFalse(self._get(b, "session_key"))

	def test_secondary_delete_failure_rolls_back_partial_free(self):
		"""If the CHAT_SESSION lookup delete fails AFTER the conversation update
		(same uncommitted row), the except rolls back so no half-freed state
		(nulled key with a live gateway session) rides to the next row's commit."""
		name = self._conv(session_key="test-lc-partial", idle_days=40, has_message=True)
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
		self.assertEqual(summary["sessions_freed"], 0)
		# Rolled back: the conversation keeps its key, not half-freed.
		self.assertEqual(self._get(name, "session_key"), "test-lc-partial")

	# ---- reap empty chats -------------------------------------------

	def test_empty_idle_chat_reaped(self):
		name = self._conv(idle_days=10)  # 0 messages, idle > EMPTY_GRACE_DAYS
		summary = self._run(_fake_sess())
		self.assertEqual(summary["empty_reaped"], 1)
		self.assertFalse(frappe.db.exists(CONV, name))

	def test_empty_recent_chat_kept(self):
		name = self._conv(idle_days=2)  # inside the grace window
		summary = self._run(_fake_sess())
		self.assertEqual(summary["empty_reaped"], 0)
		self.assertTrue(frappe.db.exists(CONV, name))

	def test_empty_starred_chat_kept(self):
		name = self._conv(idle_days=10, starred=1)
		summary = self._run(_fake_sess())
		self.assertEqual(summary["empty_reaped"], 0)
		self.assertTrue(frappe.db.exists(CONV, name))

	def test_nonempty_idle_chat_not_reaped(self):
		name = self._conv(idle_days=10, has_message=True)
		summary = self._run(_fake_sess())
		self.assertEqual(summary["empty_reaped"], 0)
		self.assertTrue(frappe.db.exists(CONV, name))

	def test_empty_chat_with_stray_session_freed_then_reaped(self):
		"""Defensive: a 0-message chat carrying a session (idle within the 30-day
		session window but past the 7-day empty window) has its stray session
		freed, then the row is reaped."""
		name = self._conv(session_key="test-lc-stray", idle_days=10)  # < 30, > 7
		sess = _fake_sess()
		summary = self._run(sess)
		self.assertEqual(summary["sessions_freed"], 0)   # 10 days < 30-day session window
		self.assertEqual(summary["empty_reaped"], 1)
		sess.delete_session.assert_any_call("test-lc-stray")
		self.assertFalse(frappe.db.exists(CONV, name))
		self.assertFalse(frappe.db.exists(CHAT_SESSION, {"session_key": "test-lc-stray"}))

	def test_streaming_chat_not_reaped_as_empty(self):
		# There is no separate in-flight guard: a streaming row is still a MESSAGE,
		# so the any-message EXISTS filter makes the chat non-empty and safe.
		name = self._conv(idle_days=10, streaming=True)
		summary = self._run(_fake_sess())
		self.assertEqual(summary["empty_reaped"], 0)
		self.assertTrue(frappe.db.exists(CONV, name))

	def test_empty_filebox_drop_not_reaped(self):
		# A File-Box drop that failed to send leaves a 0-message file_box chat with
		# the user's uploaded File attached - reaping it would delete their file.
		name = self._conv(idle_days=10, file_box=1)
		summary = self._run(_fake_sess())
		self.assertEqual(summary["empty_reaped"], 0)
		self.assertTrue(frappe.db.exists(CONV, name))

	def test_empty_chat_with_attached_file_not_reaped(self):
		# Belt-and-suspenders for delete_doc's cascade to attached Files: any chat
		# with an attached File is spared regardless of the file_box flag.
		name = self._conv(idle_days=10)
		f = frappe.get_doc({
			"doctype": "File", "file_name": "lc-attach.txt",
			"attached_to_doctype": CONV, "attached_to_name": name,
			"content": "x", "is_private": 1,
		}).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("File", f.name, force=True, ignore_permissions=True))
		frappe.db.commit()
		summary = self._run(_fake_sess())
		self.assertEqual(summary["empty_reaped"], 0)
		self.assertTrue(frappe.db.exists(CONV, name))

	def test_empty_reap_rechecks_messages_before_delete(self):
		"""TOCTOU guard: a first message landing between the SELECT and the delete
		spares the row (the fresh message + live turn are not destroyed)."""
		name = self._conv(idle_days=10)
		real_exists = frappe.db.exists

		def exists_with_race(dt, filt=None, *a, **k):
			# Simulate a message committed for this conv after it was selected.
			if dt == MSG and isinstance(filt, dict) and filt.get("conversation") == name:
				return "MSG-raced"
			return real_exists(dt, filt, *a, **k)

		with patch("frappe.db.exists", side_effect=exists_with_race):
			summary = self._run(_fake_sess())
		self.assertEqual(summary["empty_reaped"], 0)
		self.assertTrue(frappe.db.exists(CONV, name))

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
		self._conv(session_key="test-lc-ref:dashboard:live-1", idle_days=2, has_message=True)
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
			self._conv(session_key=f"test-lc-batch-{i}", idle_days=40, has_message=True)
		entries = [{
			"key": f"test-lc-orph:dashboard:b{i}",
			"hasActiveRun": False, "updatedAt": OLD_MS,
		} for i in range(3)]
		sess = _fake_sess(entries=entries)
		with patch.object(session_lifecycle, "BATCH_MAX", 4):
			summary = self._run(sess)
		# 3 session frees + only 1 orphan fit in the budget of 4.
		self.assertEqual(summary["sessions_freed"], 3)
		self.assertEqual(summary["empty_reaped"], 0)
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
		self._conv(session_key="test-lc-x", idle_days=40, has_message=True)
		with patch(
			"jarvis.chat.openclaw_client.OpenclawSession.connect",
			side_effect=RuntimeError("refused"),
		), patch("jarvis.selfhost.is_self_hosted", return_value=False), \
		     patch("frappe.log_error"):
			summary = session_lifecycle.rotate_dormant_sessions()
		self.assertEqual(summary, {"skipped": "connect failed"})


class TestRetentionSettingValidation(FrappeTestCase):
	"""The floor lives in the Jarvis Settings controller so a fumbled tiny value
	can't be saved and mass-free on the next cron. 0 (never) and unset are
	always allowed; anything 1-6 is rejected."""

	def _validate(self, val):
		s = frappe.get_single(SETTINGS)
		s.conversation_retention_days = val
		s._validate_conversation_retention()

	def test_floor_rejects_below_7(self):
		with self.assertRaises(frappe.ValidationError):
			self._validate(3)

	def test_zero_is_allowed(self):
		self._validate(0)  # never-free sentinel

	def test_seven_is_allowed(self):
		self._validate(7)

	def test_unset_is_allowed(self):
		self._validate(None)
