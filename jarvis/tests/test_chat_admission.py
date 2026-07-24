"""Tests for jarvis.chat.admission - Phase-0 durable admission control (WP-0).

Covers every acceptance check in the WP-0 direction brief:

* Two simultaneous sends at cap 1 -> exactly one dispatching, one queued
  (threaded, barrier-synchronized, real DB row locks).
* Promotion on terminal within the same request cycle (no sweep).
* Burst of 6 at cap 4 -> 4 dispatch / 2 queue; cancel renumbers positions.
* Continuation (confirm path) at cap queues, does NOT bypass admission (R-7).
* All four _dispatch_turn callers gated (send / retry / orphan / macro).
* Reservation expiry: a lost enqueue is returned to dispatchable by the sweep.
* Dual-signal coexistence: a legacy fresh-streaming Message counts as inflight.
* Flag OFF -> byte-identical legacy behavior (no Turn rows, no gating).
* Background floor: interactive holds at most ceiling-1 when background queued.

Tests run as a dedicated fixture user and clean up their own Turn / Pump /
Conversation rows. Cap is controlled by patching admission._max_inflight
(process-wide, so child threads see it too); real dispatch is stubbed by
patching jarvis.chat.api._dispatch_turn so no RQ jobs are enqueued.
"""

import threading
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat import admission, pump
from jarvis.chat import api as chat_api

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"
TURN = "Jarvis Chat Turn"
PUMP = "Jarvis Relay Pump"
TEST_USER = "jarvis-admission-test@example.com"


def _ensure_test_user(user: str = TEST_USER) -> None:
	if frappe.db.exists("User", user):
		return
	doc = frappe.get_doc(
		{
			"doctype": "User",
			"email": user,
			"first_name": "Admission",
			"last_name": "Test",
			"enabled": 1,
			"send_welcome_email": 0,
			"user_type": "System User",
		}
	)
	doc.insert(ignore_permissions=True)
	doc.add_roles("System Manager", "Jarvis User")
	frappe.db.commit()


def _cleanup(user: str = TEST_USER) -> None:
	for name in frappe.get_all(CONV, filters={"owner": user}, pluck="name"):
		frappe.db.delete(TURN, {"conversation": name})
		frappe.db.delete(MSG, {"conversation": name})
		frappe.delete_doc(CONV, name, ignore_permissions=True, force=True)
	# Phase-0 admission is a SITE-WIDE single-shard mechanism, so its counts see
	# ALL non-terminal Turn rows and ALL fresh-streaming placeholders on the whole
	# site - not just this test user's. A stray abandoned `dispatching` row from
	# real dev traffic, or a fresh-streaming placeholder left by another test
	# module within the 180s window, would inflate _shard_inflight /
	# _shard_queued_depth (and the sweep summaries) and make the cap-sensitive
	# tests flaky (turns that should dispatch stay queued). Establish a clean shard
	# baseline: drop stray non-terminal Turn rows and age stray fresh-streaming
	# placeholders out of the freshness window. Safe on the dedicated test site -
	# these are abandoned rows the sweep would settle anyway; no conversation or
	# message CONTENT is touched (only a streaming placeholder's `modified` stamp).
	frappe.db.delete(TURN, {"state": ["in", ("queued", "dispatching")]})
	stale = frappe.utils.add_to_date(None, seconds=-(admission._INFLIGHT_FRESH_SECONDS + 600))
	frappe.db.sql(
		"""UPDATE `tabJarvis Chat Message`
		SET modified=%(old)s
		WHERE role='assistant' AND streaming=1 AND recovering=0 AND modified > %(fresh)s""",
		{"old": stale, "fresh": admission._fresh_cutoff()},
	)
	frappe.db.commit()


class _AdmissionTestCase(FrappeTestCase):
	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup()
		# Force the flag ON for THIS suite regardless of the site's setting, so
		# the ON-behavior tests are deterministic even when run on a flag-OFF site.
		self._flag_patch = patch.dict(frappe.local.conf, {admission.FLAG: 1})
		self._flag_patch.start()
		self.assertTrue(admission.admission_enabled())
		# Pin the Relay Pump OFF at the FUNCTION seam for the whole Phase-0 suite. Since
		# the default-ON pump inversion, an ABSENT `jarvis_pump_enabled` means the pump
		# OWNS dispatch (accept_or_queue takes the pump branch — turns stay `queued`,
		# promote/sweep step back), which would break these legacy-admission assertions.
		# We patch the flag FUNCTIONS (module-level, so the value is visible in the
		# worker THREADS the concurrency tests spawn — a patch.dict on the thread-local
		# `frappe.local.conf` would not be), not the conf key.
		self._pump_off_patches = [
			patch.object(pump, "pump_mode_active", return_value=False),
			patch.object(pump, "pump_configured", return_value=False),
			patch.object(pump, "pump_draining", return_value=False),
		]
		for p in self._pump_off_patches:
			p.start()
		admission._ensure_control_row(admission.DEFAULT_RELAY_TARGET)

	def tearDown(self):
		for p in self._pump_off_patches:
			p.stop()
		self._flag_patch.stop()
		_cleanup()
		frappe.set_user(self._orig_user)

	# ---- helpers ----------------------------------------------------------- #

	def _mk_conv(self) -> str:
		doc = frappe.get_doc({"doctype": CONV, "title": "New chat", "status": "Active"})
		doc.flags.ignore_permissions = True
		doc.insert()
		frappe.db.commit()
		return doc.name

	def _mk_msg(self, conv: str, seq: int, role: str = "user", content: str = "hi", **extra) -> str:
		doc = frappe.get_doc(
			{"doctype": MSG, "conversation": conv, "seq": seq, "role": role, "content": content, **extra}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		frappe.db.commit()
		return doc.name

	def _accept(self, conv: str, run_id: str, seed: str, turn_class: str = "interactive", calls=None):
		return admission.accept_or_queue(
			conversation=conv,
			run_id=run_id,
			seed_message=seed,
			turn_class=turn_class,
			dispatch=(lambda: calls.append(run_id)) if calls is not None else (lambda: None),
		)

	def _state(self, run_id: str) -> str:
		return frappe.db.get_value(TURN, run_id, "state")

	def _insert_turn(self, conv: str, run_id: str, seed: str, state: str, **extra) -> None:
		row = {
			"doctype": TURN,
			"run_id": run_id,
			"conversation": conv,
			"relay_target_id": admission.DEFAULT_RELAY_TARGET,
			"turn_class": "interactive",
			"state": state,
			"version": 1 if state != "queued" else 0,
			"seed_message": seed,
			"enqueued_at": frappe.utils.now(),
		}
		row.update(extra)
		frappe.get_doc(row).insert(ignore_permissions=True)
		frappe.db.commit()


# --------------------------------------------------------------------------- #


class TestAcceptOrQueueBasics(_AdmissionTestCase):
	def test_single_send_dispatches(self):
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1)
		calls = []
		with patch.object(admission, "_max_inflight", return_value=4):
			res = self._accept(conv, "run1", seed, calls=calls)
		self.assertTrue(res["ok"])
		self.assertTrue(res["dispatched"])
		self.assertEqual(self._state("run1"), "dispatching")
		self.assertEqual(calls, ["run1"])  # dispatch fired exactly once
		row = frappe.db.get_value(TURN, "run1", ["reserved", "seed_message"], as_dict=True)
		self.assertEqual(row["reserved"], 1)
		self.assertEqual(row["seed_message"], seed)

	def test_second_send_same_conversation_queues(self):
		conv = self._mk_conv()
		s1 = self._mk_msg(conv, 1)
		s2 = self._mk_msg(conv, 2)
		with patch.object(admission, "_max_inflight", return_value=4):
			self._accept(conv, "run1", s1)
			res = self._accept(conv, "run2", s2)
		# Single-flight: even with shard capacity, a second turn on the SAME
		# conversation queues behind the first.
		self.assertFalse(res["dispatched"])
		self.assertEqual(self._state("run2"), "queued")
		self.assertEqual(res["queued_position"], 1)

	def test_duplicate_run_id_is_idempotent(self):
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1)
		with patch.object(admission, "_max_inflight", return_value=4):
			self._accept(conv, "dup", seed)
			res = self._accept(conv, "dup", seed)
		self.assertTrue(res.get("duplicate"))
		self.assertEqual(frappe.db.count(TURN, {"run_id": "dup"}), 1)


class TestSimultaneousSendsCASRace(_AdmissionTestCase):
	def test_two_simultaneous_sends_cap_one(self):
		"""Barrier-synchronized threads, real separate DB connections, cap 1:
		exactly one dispatching + one queued position 1 (no double-admit)."""
		conv = self._mk_conv()
		s1 = self._mk_msg(conv, 1)
		s2 = self._mk_msg(conv, 2)
		site = frappe.local.site
		barrier = threading.Barrier(2)
		results: dict[str, dict] = {}
		errors: list = []

		def worker(run_id: str, seed: str):
			frappe.init(site=site)
			frappe.connect()
			frappe.set_user(TEST_USER)
			try:
				barrier.wait(timeout=10)
				results[run_id] = admission.accept_or_queue(
					conversation=conv,
					run_id=run_id,
					seed_message=seed,
					turn_class="interactive",
					dispatch=lambda: None,
				)
			except Exception as e:
				errors.append(e)
			finally:
				try:
					frappe.db.commit()
				finally:
					frappe.destroy()

		with patch.object(admission, "_max_inflight", return_value=1):
			t1 = threading.Thread(target=worker, args=("A", s1))
			t2 = threading.Thread(target=worker, args=("B", s2))
			t1.start()
			t2.start()
			t1.join(timeout=20)
			t2.join(timeout=20)

		self.assertEqual(errors, [], f"worker error: {errors}")
		states = sorted(frappe.db.get_value(TURN, r, "state") for r in ("A", "B"))
		self.assertEqual(states, ["dispatching", "queued"], "exactly one dispatching, one queued")
		# The queued one reports position 1.
		queued = next(r for r in ("A", "B") if frappe.db.get_value(TURN, r, "state") == "queued")
		self.assertEqual(admission._position_of(queued, admission.DEFAULT_RELAY_TARGET), 1)


class TestPromotionOnTerminal(_AdmissionTestCase):
	def test_terminal_promotes_next_in_same_cycle(self):
		conv_a = self._mk_conv()
		conv_b = self._mk_conv()
		sa = self._mk_msg(conv_a, 1)
		sb = self._mk_msg(conv_b, 1)
		dispatched = []
		with (
			patch.object(admission, "_max_inflight", return_value=1),
			patch.object(
				chat_api, "_dispatch_turn", side_effect=lambda *a, **k: dispatched.append(a[0]["run_id"])
			),
		):
			self._accept(conv_a, "A", sa)  # dispatches (cap 1)
			res_b = self._accept(conv_b, "B", sb)  # queues (shard full)
			self.assertFalse(res_b["dispatched"])
			self.assertEqual(self._state("B"), "queued")
			# Terminal on A -> B promoted within THIS call (no sweep).
			admission.settle_turn("A", "done")
		self.assertEqual(self._state("A"), "done")
		self.assertEqual(self._state("B"), "dispatching")
		self.assertIn("B", dispatched)


class TestBurstAndCancel(_AdmissionTestCase):
	def test_burst_six_at_cap_four_positions_and_cancel(self):
		convs = [self._mk_conv() for _ in range(6)]
		seeds = [self._mk_msg(c, 1) for c in convs]
		runs = [f"r{i}" for i in range(6)]
		with patch.object(admission, "_max_inflight", return_value=4):
			results = [self._accept(convs[i], runs[i], seeds[i]) for i in range(6)]
		dispatched = [runs[i] for i in range(6) if results[i]["dispatched"]]
		queued = [runs[i] for i in range(6) if not results[i]["dispatched"]]
		self.assertEqual(len(dispatched), 4, "4 dispatch at cap 4")
		self.assertEqual(len(queued), 2, "2 queue")
		# Positions 1 and 2 (FIFO).
		self.assertEqual(results[4]["queued_position"], 1)
		self.assertEqual(results[5]["queued_position"], 2)
		# Cancel the position-1 queued turn -> the other becomes position 1.
		with patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None):
			out = admission.cancel_queued_turn(runs[4])
		self.assertTrue(out["ok"])
		self.assertEqual(self._state(runs[4]), "cancelled")
		self.assertEqual(admission._position_of(runs[5], admission.DEFAULT_RELAY_TARGET), 1)


class TestContinuationNoBypass(_AdmissionTestCase):
	def test_continuation_queues_at_cap_and_does_not_bypass(self):
		"""R-7: enqueue_continuation routes through admission. At cap, the
		continuation becomes a durable queued turn instead of a privileged
		bypass that runs concurrently."""
		conv = self._mk_conv()
		s1 = self._mk_msg(conv, 1)
		dispatched = []
		with (
			patch.object(admission, "_max_inflight", return_value=1),
			patch.object(
				chat_api, "_dispatch_turn", side_effect=lambda *a, **k: dispatched.append(a[0]["run_id"])
			),
		):
			# Occupy the single credit with a live turn on this conversation.
			self._accept(conv, "live", s1)
			self.assertEqual(self._state("live"), "dispatching")
			# A confirm continuation now must queue (not bypass).
			out = chat_api.enqueue_continuation(conv, "created ORD-001")
		run_id = out["run_id"]
		self.assertEqual(self._state(run_id), "queued")
		# It never dispatched while the live turn holds the credit.
		self.assertNotIn(run_id, dispatched)


class TestFourCallersGated(_AdmissionTestCase):
	def test_send_message_creates_turn(self):
		conv = self._mk_conv()
		with patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None):
			res = chat_api.send_message(conversation=conv, message="hello there")
		self.assertTrue(res["ok"])
		self.assertTrue(frappe.db.exists(TURN, res["run_id"]))
		self.assertEqual(frappe.db.get_value(TURN, res["run_id"], "turn_class"), "interactive")

	def test_retry_message_creates_turn_reusing_seed(self):
		conv = self._mk_conv()
		u = self._mk_msg(conv, 1, role="user", content="do it")
		a = self._mk_msg(conv, 2, role="assistant", content="", error="boom")
		with patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None):
			res = chat_api.retry_message(a)
		self.assertTrue(res["ok"])
		self.assertTrue(frappe.db.exists(TURN, res["run_id"]))
		# OAR-3: retry reuses the EXISTING user message; no new user row.
		self.assertEqual(frappe.db.get_value(TURN, res["run_id"], "seed_message"), u)
		self.assertEqual(frappe.db.count(MSG, {"conversation": conv, "role": "user"}), 1)

	def test_redispatch_orphan_creates_background_turn(self):
		conv = self._mk_conv()
		u = self._mk_msg(conv, 1)
		with patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None):
			chat_api._redispatch_orphan(conv, u)
		row = frappe.db.get_value(
			TURN, {"conversation": conv, "seed_message": u}, ["turn_class", "state"], as_dict=True
		)
		self.assertIsNotNone(row)
		self.assertEqual(row["turn_class"], "background")

	def test_enqueue_turn_macro_caller_creates_turn(self):
		conv = self._mk_conv()
		with patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None):
			out = chat_api._enqueue_turn(conv, "macro step", hidden=True)
		self.assertTrue(frappe.db.exists(TURN, out["run_id"]))


class TestReservationExpiry(_AdmissionTestCase):
	def _mk_dispatching_turn(self, conv, seed, run_id, *, reservation_at, **extra):
		row = {
			"doctype": TURN,
			"run_id": run_id,
			"conversation": conv,
			"relay_target_id": admission.DEFAULT_RELAY_TARGET,
			"turn_class": "interactive",
			"state": "dispatching",
			"version": 1,
			"seed_message": seed,
			"reserved": 1,
			"reservation_expires_at": reservation_at,
			"dispatching_at": reservation_at,
			"enqueued_at": reservation_at,
		}
		row.update(extra)
		frappe.get_doc(row).insert(ignore_permissions=True)
		frappe.db.commit()

	def test_sweep_reclaims_lost_dispatch(self):
		"""A turn dispatched (reserved) whose enqueue was lost - no assistant
		activity OF ITS OWN, reservation expired - is returned to queued by the
		sweep. OARI-1: this now uses a NON-first-turn conversation (a PRIOR turn
		settled before it) - the reviewer showed the old first-turn-only fixture
		hid the reconcile/reclaim scoping bug (a first turn has no prior assistant
		so `if not latest: continue` masked it)."""
		conv = self._mk_conv()
		# Prior turn 1: settled (user seq1 + assistant seq2, no error).
		self._mk_msg(conv, 1, role="user", content="first")
		self._mk_msg(conv, 2, role="assistant", content="reply one", streaming=0)
		# Turn 2: this turn's seed (user seq3); its enqueue was lost - NO assistant
		# row of its OWN (nothing with seq > 3).
		seed = self._mk_msg(conv, 3, role="user", content="second")
		past = frappe.utils.add_to_date(None, seconds=-60)
		self._mk_dispatching_turn(conv, seed, "lost", reservation_at=past)
		with patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None):
			summary = admission.sweep()
		self.assertGreaterEqual(summary["reclaimed"], 1)
		# It must be RECLAIMED (queued, or re-promoted to dispatching by the same
		# sweep) - NEVER closed 'done' on the strength of turn 1's assistant row.
		self.assertIn(self._state("lost"), ("queued", "dispatching"))
		self.assertNotEqual(self._state("lost"), "done")
		self.assertEqual(summary["reconciled"], 0, "must reclaim, not reconcile-close")
		row = frappe.db.get_value(TURN, "lost", ["was_recovered"], as_dict=True)
		self.assertEqual(row["was_recovered"], 1)

	def test_sweep_does_not_close_turn_on_prior_settled_assistant(self):
		"""OARI-1 narrow-window / probe B: a dispatching turn whose latest assistant
		on the conversation is a PRIOR settled turn - and whose OWN placeholder has
		not been written yet - must NOT be reconcile-closed 'done' (silent turn
		loss + over-promotion). With a FRESH reservation it also isn't reclaimed:
		it stays dispatching, untouched, waiting for its worker."""
		conv = self._mk_conv()
		self._mk_msg(conv, 1, role="user", content="first")
		self._mk_msg(conv, 2, role="assistant", content="reply one", streaming=0)
		seed = self._mk_msg(conv, 3, role="user", content="second")
		future = frappe.utils.add_to_date(None, seconds=admission.RESERVE_TTL_S)
		self._mk_dispatching_turn(conv, seed, "live2", reservation_at=future)
		with patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None):
			summary = admission.sweep()
		self.assertEqual(self._state("live2"), "dispatching", "live turn must not be closed")
		self.assertEqual(summary["reconciled"], 0)
		self.assertEqual(summary["reclaimed"], 0)

	def test_sweep_closes_orphaned_stale_streaming_turn(self):
		"""OARI-3: a dispatching turn whose OWN placeholder is a stale streaming
		row past a lost worker (reservation expired >> the worker cap) is closed
		errored so a post-deploy orphan frees its shard credit instead of pinning
		it. A live turn (fresh) is covered by the sibling test below."""
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1, role="user", content="q")
		# This turn's OWN placeholder: streaming, but stale (modified far in the
		# past, past the freshness window).
		stale = frappe.utils.add_to_date(None, seconds=-(admission._INFLIGHT_FRESH_SECONDS + 120))
		amsg = self._mk_msg(conv, 2, role="assistant", content="", streaming=1, recovering=0)
		frappe.db.set_value(MSG, amsg, "modified", stale, update_modified=False)
		frappe.db.commit()
		self._mk_dispatching_turn(
			conv, seed, "orphan", reservation_at=frappe.utils.add_to_date(None, seconds=-60)
		)
		with patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None):
			summary = admission.sweep()
		self.assertGreaterEqual(summary["reconciled"], 1)
		self.assertEqual(self._state("orphan"), "errored")

	def test_sweep_leaves_live_streaming_turn(self):
		"""OARI-3 safety: a dispatching turn whose OWN placeholder is FRESH
		streaming (worker actively producing) is NEVER closed - closing it would
		free the credit and promote a second turn onto the same live session."""
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1, role="user", content="q")
		self._mk_msg(conv, 2, role="assistant", content="thinking", streaming=1, recovering=0)
		# Even with an expired reservation, a FRESH placeholder means live.
		self._mk_dispatching_turn(
			conv, seed, "livestream", reservation_at=frappe.utils.add_to_date(None, seconds=-60)
		)
		with patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None):
			admission.sweep()
		self.assertEqual(self._state("livestream"), "dispatching")

	def test_sweep_reservation_honors_cancel_requested(self):
		"""OARI-6: a stopped turn (cancel_requested) whose worker died before a
		placeholder must be CANCELLED by the reclaim sweep, never re-dispatched."""
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1, role="user", content="q")
		past = frappe.utils.add_to_date(None, seconds=-60)
		self._mk_dispatching_turn(conv, seed, "stopped", reservation_at=past, cancel_requested=1)
		with patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None):
			admission.sweep()
		self.assertEqual(self._state("stopped"), "cancelled")


class TestTurnMessageReconcile(_AdmissionTestCase):
	def test_sweep_closes_dispatching_turn_when_message_settled(self):
		"""Message truth wins: an assistant Message already settled but the Turn
		still dispatching (missed terminal hook / flag flipped off mid-turn) is
		closed by the reconcile sweep."""
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1)
		self._mk_msg(conv, 2, role="assistant", content="done", streaming=0)
		frappe.get_doc(
			{
				"doctype": TURN,
				"run_id": "stuck",
				"conversation": conv,
				"relay_target_id": admission.DEFAULT_RELAY_TARGET,
				"turn_class": "interactive",
				"state": "dispatching",
				"version": 1,
				"seed_message": seed,
				"reserved": 1,
				"dispatching_at": frappe.utils.now(),
				"enqueued_at": frappe.utils.now(),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		with patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None):
			summary = admission.sweep()
		self.assertGreaterEqual(summary["reconciled"], 1)
		self.assertEqual(self._state("stuck"), "done")


class TestDualSignalCoexistence(_AdmissionTestCase):
	def test_legacy_streaming_counts_as_inflight(self):
		"""OAR-11: a legacy fresh-streaming assistant Message with no owning
		Turn row counts toward shard inflight, so a new send at cap 1 queues."""
		legacy_conv = self._mk_conv()
		self._mk_msg(legacy_conv, 1, role="user")
		# Fresh streaming assistant, no Turn row -> the legacy signal.
		self._mk_msg(legacy_conv, 2, role="assistant", content="...", streaming=1, recovering=0)
		self.assertGreaterEqual(admission._legacy_streaming_count(admission.DEFAULT_RELAY_TARGET), 1)

		other = self._mk_conv()
		seed = self._mk_msg(other, 1)
		with patch.object(admission, "_max_inflight", return_value=1):
			res = self._accept(other, "newrun", seed)
		self.assertFalse(res["dispatched"], "legacy inflight fills cap 1 -> new send queues")
		self.assertEqual(self._state("newrun"), "queued")


class TestBackgroundFloor(_AdmissionTestCase):
	def test_background_gets_floor_when_interactive_would_take_last_credit(self):
		"""SUX-4a: with background queued, interactive holds at most cap-1
		credits - promote_next gives the last credit to background."""
		# cap 2. Fill one credit with an interactive dispatching turn, then queue
		# one interactive + one background; promotion of the last credit must go
		# to background (interactive capped at cap-1 = 1).
		c_live = self._mk_conv()
		c_int = self._mk_conv()
		c_bg = self._mk_conv()
		s_live = self._mk_msg(c_live, 1)
		s_int = self._mk_msg(c_int, 1)
		s_bg = self._mk_msg(c_bg, 1)
		dispatched = []
		with (
			patch.object(admission, "_max_inflight", return_value=2),
			patch.object(
				chat_api, "_dispatch_turn", side_effect=lambda *a, **k: dispatched.append(a[0]["run_id"])
			),
		):
			self._accept(c_live, "live", s_live, turn_class="interactive")  # dispatches (1/2)
			# Force both to queue by accepting while a credit is free but making
			# them queue via direct insert at queued, then promote.
			self._accept(c_int, "qi", s_int, turn_class="interactive")  # dispatches (2/2)
			self._accept(c_bg, "qb", s_bg, turn_class="background")  # queues (full)
			self.assertEqual(self._state("qb"), "queued")
			# Free one credit; the queued background turn should win it over any
			# future interactive because interactive already holds cap-1.
			admission.settle_turn("qi", "done")
		# qb (background) promoted into the freed credit.
		self.assertEqual(self._state("qb"), "dispatching")


class TestFlagOffByteIdentical(_AdmissionTestCase):
	def test_flag_off_creates_no_turn_rows_and_dispatches_legacy(self):
		conv = self._mk_conv()
		dispatched = []
		with (
			patch.dict(frappe.local.conf, {admission.FLAG: 0}),
			patch.object(
				chat_api, "_dispatch_turn", side_effect=lambda *a, **k: dispatched.append(a[0]["run_id"])
			),
		):
			self.assertFalse(admission.admission_enabled())
			res = chat_api.send_message(conversation=conv, message="hi there")
		self.assertTrue(res["ok"])
		# No Turn row written, and NOT queued: byte-identical legacy dispatch.
		self.assertNotIn("queued", res)
		self.assertEqual(frappe.db.count(TURN, {"conversation": conv}), 0)
		self.assertEqual(dispatched, [res["run_id"]])


class TestLegacyCoexistenceGuard(_AdmissionTestCase):
	def test_same_conversation_legacy_stream_blocks_new_send(self):
		"""OARI-2 / OAR-11: a legacy fresh-streaming turn (no Turn row, dispatched
		before the flag flipped on) on conversation X must block a NEW send on the
		SAME X from dispatching - it queues instead. The old _conv_legacy_busy was
		dead (run_id='' sentinel counted the caller's own just-inserted row), so
		this double-admitted onto one openclaw session."""
		conv = self._mk_conv()
		self._mk_msg(conv, 1, role="user")
		# Legacy fresh streaming assistant, NO owning Turn row.
		self._mk_msg(conv, 2, role="assistant", content="...", streaming=1, recovering=0)
		# The legacy-busy signal must now FIRE for this conversation.
		self.assertTrue(admission._conv_legacy_busy(conv))
		seed = self._mk_msg(conv, 3, role="user")
		with patch.object(admission, "_max_inflight", return_value=4):
			res = self._accept(conv, "newrun", seed)
		self.assertFalse(res["dispatched"], "must not double-admit onto the legacy session")
		self.assertEqual(self._state("newrun"), "queued")

	def test_queued_row_does_not_hide_legacy_from_shard_count(self):
		"""OARI-2 shard undercount: a merely QUEUED Turn row on a conversation must
		not zero out that conversation's coexisting legacy stream in
		_legacy_streaming_count (the NOT EXISTS now matches only 'dispatching')."""
		conv = self._mk_conv()
		self._mk_msg(conv, 1, role="user")
		self._mk_msg(conv, 2, role="assistant", content="...", streaming=1, recovering=0)
		self._insert_turn(conv, "q_on_legacy", self._mk_msg(conv, 3, role="user"), "queued")
		self.assertGreaterEqual(
			admission._legacy_streaming_count(admission.DEFAULT_RELAY_TARGET),
			1,
			"a queued row must not hide the legacy stream from the shard count",
		)


class TestFlagOffDrainInertia(_AdmissionTestCase):
	def test_flag_off_sweep_drains_existing_but_dispatches_nothing(self):
		"""OARI-4: with the flag OFF and residual rows present, the sweep may still
		SETTLE/reconcile existing rows (drain-to-empty) but must dispatch NOTHING
		new (promote_next is flag-gated), and accept_or_queue never runs."""
		# A dispatching turn whose OWN message settled -> reconcile drains it.
		conv_a = self._mk_conv()
		seed_a = self._mk_msg(conv_a, 1, role="user")
		self._mk_msg(conv_a, 2, role="assistant", content="done", streaming=0)
		self._insert_turn(
			conv_a, "resid", seed_a, "dispatching", reserved=1, dispatching_at=frappe.utils.now()
		)
		# A queued turn on another conversation -> must NOT be promoted/dispatched.
		conv_b = self._mk_conv()
		seed_b = self._mk_msg(conv_b, 1, role="user")
		self._insert_turn(conv_b, "qidle", seed_b, "queued")
		dispatched = []
		with (
			patch.dict(frappe.local.conf, {admission.FLAG: 0}),
			patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: dispatched.append(1)),
		):
			self.assertFalse(admission.admission_enabled())
			summary = admission.sweep()
		self.assertEqual(dispatched, [], "flag OFF issues NO fresh dispatch")
		self.assertEqual(summary["promoted"], 0)
		# Existing rows drain: the settled dispatching turn reconciles to done...
		self.assertEqual(self._state("resid"), "done")
		# ...the queued turn is NOT promoted (stays queued).
		self.assertEqual(self._state("qidle"), "queued")


class TestOverloadSeedCleanup(_AdmissionTestCase):
	def test_send_overload_after_commit_deletes_seed(self):
		"""OARI-7 / SUXI-5: when the cheap pre-check passes but the authoritative
		locked check rejects on overload, the already-committed user Message is
		DELETED - no dangling unanswered send reappears on reload."""
		conv_fill = self._mk_conv()
		self._insert_turn(conv_fill, "fill", self._mk_msg(conv_fill, 1, role="user"), "queued")
		conv = self._mk_conv()
		with (
			patch.object(admission, "MAX_QUEUE_DEPTH", 1),
			patch.object(admission, "shard_overloaded", return_value=False),
			patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None),
		):
			res = chat_api.send_message(conversation=conv, message="hello there")
		self.assertFalse(res["ok"])
		self.assertIn("busy", res["reason"].lower())
		# The orphan user Message was cleaned up, and no Turn row leaked.
		self.assertEqual(frappe.db.count(MSG, {"conversation": conv, "role": "user"}), 0)
		self.assertEqual(frappe.db.count(TURN, {"conversation": conv}), 0)


class TestCapOneFairness(_AdmissionTestCase):
	def test_cap_one_interactive_not_starved_by_background(self):
		"""OARI-8: at cap 1 the sole credit must go to a waiting INTERACTIVE turn,
		not always to background. The old floor 'int_inflight >= cap-1' degenerated
		to '>= 0' (always true) and handed the single credit to background."""
		c_int = self._mk_conv()
		c_bg = self._mk_conv()
		self._insert_turn(c_int, "i1", self._mk_msg(c_int, 1), "queued", turn_class="interactive")
		self._insert_turn(c_bg, "b1", self._mk_msg(c_bg, 1), "queued", turn_class="background")
		with (
			patch.object(admission, "_max_inflight", return_value=1),
			patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None),
		):
			admission.promote_next(admission.DEFAULT_RELAY_TARGET)
		self.assertEqual(self._state("i1"), "dispatching", "interactive wins the sole credit")
		self.assertEqual(self._state("b1"), "queued")


class TestActiveTurnResync(_AdmissionTestCase):
	def test_active_turn_returns_queued(self):
		"""SUXI-1: the resync endpoint returns the conversation's own queued turn
		(run_id + position) so a client that lost the chip rebuilds it."""
		conv = self._mk_conv()
		s1 = self._mk_msg(conv, 1)
		s2 = self._mk_msg(conv, 2)
		with patch.object(admission, "_max_inflight", return_value=4):
			self._accept(conv, "live", s1)  # dispatches
			self._accept(conv, "q1", s2)  # queues (single-flight)
		out = admission.active_turn_for_conversation(conv)
		self.assertTrue(out["ok"])
		self.assertIsNotNone(out["active"])
		self.assertEqual(out["active"]["run_id"], "q1")
		self.assertEqual(out["active"]["state"], "queued")
		self.assertEqual(out["active"]["position"], 1)
		self.assertEqual(out["active"]["message_id"], s2)

	def test_active_turn_none_when_idle(self):
		conv = self._mk_conv()
		out = admission.active_turn_for_conversation(conv)
		self.assertTrue(out["ok"])
		self.assertIsNone(out["active"])


class TestContinuationChip(_AdmissionTestCase):
	def test_continuation_queues_at_cap_returns_position(self):
		"""SUXI-2: a confirm continuation that queues at cap RETURNS its queued
		position so apply_action/confirm_tool can render the chip (not silence)."""
		conv = self._mk_conv()
		s1 = self._mk_msg(conv, 1)
		with (
			patch.object(admission, "_max_inflight", return_value=1),
			patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None),
		):
			self._accept(conv, "live", s1)  # occupies the single credit
			out = chat_api.enqueue_continuation(conv, "created ORD-001")
		self.assertTrue(out.get("queued"))
		self.assertEqual(out.get("queued_position"), 1)
		self.assertEqual(self._state(out["run_id"]), "queued")

	def test_continuation_exempt_from_overload(self):
		"""SUXI-2 ruling: a continuation is EXEMPT from the depth-25 overload
		rejection - it ALWAYS queues (never silently dropped), even when the shard
		queue is at/over the cap. A fresh send at that depth would be rejected."""
		# Fill the shard queue to the (patched) cap on OTHER conversations so the
		# overload guard WOULD reject a fresh send.
		fill_conv = self._mk_conv()
		self._insert_turn(fill_conv, "fillA", self._mk_msg(fill_conv, 1, role="user"), "queued")
		# Occupy the continuation's own conversation with a live turn so it
		# single-flights (queues rather than dispatching into a free credit).
		conv = self._mk_conv()
		self._insert_turn(
			conv,
			"convlive",
			self._mk_msg(conv, 1, role="user"),
			"dispatching",
			reserved=1,
			dispatching_at=frappe.utils.now(),
		)
		with (
			patch.object(admission, "MAX_QUEUE_DEPTH", 1),
			patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None),
		):
			out = chat_api.enqueue_continuation(conv, "created ORD-002")
		# Not rejected (a fresh send at this depth would be): a durable queued Turn
		# row exists for the continuation.
		self.assertTrue(frappe.db.exists(TURN, out["run_id"]))
		self.assertEqual(self._state(out["run_id"]), "queued")
		self.assertTrue(out.get("queued"))


class TestCancelDurableMarker(_AdmissionTestCase):
	def test_user_cancel_writes_durable_marker(self):
		"""SUXI-4: cancelling a queued turn leaves a durable assistant marker
		(error-card pattern) so a later reload shows the send was cancelled - not
		indistinguishable from a silently dropped message."""
		conv = self._mk_conv()
		s1 = self._mk_msg(conv, 1)
		s2 = self._mk_msg(conv, 2)
		with (
			patch.object(admission, "_max_inflight", return_value=1),
			patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None),
		):
			self._accept(conv, "live", s1)
			self._accept(conv, "q1", s2)
			self.assertEqual(self._state("q1"), "queued")
			admission.cancel_queued_turn("q1")
		self.assertEqual(self._state("q1"), "cancelled")
		markers = frappe.get_all(
			MSG,
			filters={"conversation": conv, "role": "assistant", "error": admission.USER_CANCEL_REASON},
			pluck="name",
		)
		self.assertEqual(len(markers), 1, "one durable cancel marker on the transcript")

	def test_age_out_writes_durable_marker(self):
		"""SUXI-4 + SUX-5: a system age-out records its reason both on the Turn row
		and as a durable transcript marker."""
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1)
		self._insert_turn(conv, "old", seed, "queued")
		# Age the queued row past the max-age threshold.
		past = frappe.utils.add_to_date(None, seconds=-(admission.QUEUED_MAX_AGE_S + 120))
		frappe.db.set_value(TURN, "old", "enqueued_at", past, update_modified=False)
		frappe.db.commit()
		with patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None):
			summary = admission.sweep()
		self.assertGreaterEqual(summary["aged_out"], 1)
		self.assertEqual(self._state("old"), "cancelled")
		markers = frappe.get_all(
			MSG,
			filters={"conversation": conv, "role": "assistant", "error": admission.AGE_OUT_REASON},
			pluck="name",
		)
		self.assertEqual(len(markers), 1, "age-out leaves a durable transcript marker")


# --------------------------------------------------------------------------- #
# CDX-8 — cancel routes by state, clears the reserved credit
# --------------------------------------------------------------------------- #


class TestCancelCreditLeak(_AdmissionTestCase):
	def test_reserved_queued_cancel_frees_credit_immediately(self):
		# CDX-8: a reserved-but-unclaimed queued turn cancelled must CLEAR reserved +
		# expiry atomically, freeing the shard credit at once (not leaking it until the
		# ~900s reservation TTL).
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1)
		rid = "adm_cancel_rsv"
		self._insert_turn(
			conv,
			rid,
			seed,
			"queued",
			version=0,
			reserved=1,
			reservation_expires_at=frappe.utils.add_to_date(None, seconds=900),
		)
		target = admission.DEFAULT_RELAY_TARGET
		self.assertEqual(pump._pump_local_reservations(target), 1, "credit reserved before cancel")
		res = admission.cancel_queued_turn(rid)
		self.assertTrue(res["ok"])
		self.assertEqual(res["path"], "queued")
		self.assertEqual(self._state(rid), "cancelled")
		self.assertEqual(int(frappe.db.get_value(TURN, rid, "reserved")), 0, "reserved cleared")
		self.assertIsNone(frappe.db.get_value(TURN, rid, "reservation_expires_at"), "expiry cleared")
		self.assertEqual(pump._pump_local_reservations(target), 0, "credit freed immediately")

	def test_preparing_cancel_end_to_end(self):
		# CDX-8: a preparing/ready turn cancel routes to cancel_preparing_or_ready
		# (release credit) + cleans the assistant placeholder (no stuck spinner).
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1)
		amsg = self._mk_msg(conv, 2, role="assistant", content="", streaming=1)
		rid = "adm_cancel_prep"
		self._insert_turn(
			conv,
			rid,
			seed,
			"preparing",
			version=2,
			reserved=1,
			assistant_message=amsg,
			reservation_expires_at=None,
		)
		res = admission.cancel_queued_turn(rid)
		self.assertTrue(res["ok"])
		self.assertEqual(res["path"], "preparing_ready")
		self.assertEqual(self._state(rid), "cancelled")
		self.assertEqual(int(frappe.db.get_value(TURN, rid, "reserved")), 0, "credit released")
		self.assertEqual(int(frappe.db.get_value(MSG, amsg, "streaming")), 0, "placeholder cleaned")

	def test_cancel_dispatched_turn_reports_not_cancelled(self):
		# A turn that already advanced past preparing/ready cannot be cancelled here —
		# the endpoint returns ok=False so the UI keeps its chip.
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1)
		rid = "adm_cancel_disp"
		self._insert_turn(conv, rid, seed, "dispatching", version=3, reserved=1)
		res = admission.cancel_queued_turn(rid)
		self.assertFalse(res["ok"])
		self.assertEqual(self._state(rid), "dispatching", "dispatched turn untouched")


# --------------------------------------------------------------------------- #
# CDX-9 — enqueue-failure compensation (both admit + promote paths)
# --------------------------------------------------------------------------- #


class TestEnqueueCompensation(_AdmissionTestCase):
	def test_accept_enqueue_failure_compensates_to_queued(self):
		# CDX-9: dispatch() (the RQ enqueue) fails AFTER the admission commit — the
		# credit must not strand; compensate CAS dispatching->queued + release.
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1)
		rid = "adm_enq_fail"

		def boom():
			raise RuntimeError("redis down")

		with patch.object(admission, "_max_inflight", return_value=4):
			res = admission.accept_or_queue(
				conversation=conv, run_id=rid, seed_message=seed, turn_class="interactive", dispatch=boom
			)
		self.assertTrue(res["ok"])
		self.assertFalse(res["dispatched"], "not a false 'dispatched' on enqueue failure")
		self.assertTrue(res.get("dispatch_failed"))
		self.assertEqual(self._state(rid), "queued", "compensated back to queued")
		self.assertEqual(int(frappe.db.get_value(TURN, rid, "reserved")), 0, "reservation released")
		self.assertIsNone(frappe.db.get_value(TURN, rid, "reservation_expires_at"))

	def test_promote_enqueue_failure_compensates_to_queued(self):
		# CDX-9: the same compensation for the promotion path (_dispatch_promoted raises).
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1)
		rid = "adm_promote_fail"
		self._insert_turn(conv, rid, seed, "queued", version=0)
		target = admission.DEFAULT_RELAY_TARGET
		with (
			patch.object(admission, "_max_inflight", return_value=4),
			patch.object(admission, "_dispatch_promoted", side_effect=RuntimeError("redis down")),
		):
			admission.promote_next(target)
		self.assertEqual(self._state(rid), "queued", "compensated back to queued after failed promote")
		self.assertEqual(int(frappe.db.get_value(TURN, rid, "reserved")), 0)
		self.assertIsNone(frappe.db.get_value(TURN, rid, "reservation_expires_at"))


# --------------------------------------------------------------------------- #
# CDX-10 — cutover preflight (legacy-overlap detector)
# --------------------------------------------------------------------------- #


class TestCutoverPreflight(_AdmissionTestCase):
	class _FakeReg:
		def __init__(self, *a, **k):
			pass

		def get_job_ids(self):
			return []

	def test_detects_legacy_turn_job(self):
		site = frappe.local.site
		legacy_id = f"{site}||jarvis-turn|msgX|a0"

		class _FakeQ:
			def get_job_ids(self_inner):
				return [legacy_id, f"{site}||other|job"]

		with (
			patch("frappe.utils.background_jobs.get_queues", return_value=[_FakeQ()]),
			patch("rq.registry.StartedJobRegistry", self._FakeReg),
		):
			n, ids, scan_ok = admission._legacy_turn_jobs()
		self.assertEqual(n, 1, "only the jarvis-turn::* job matched")
		self.assertIn(legacy_id, ids)
		self.assertTrue(scan_ok, "a clean scan reports scan_ok=True")

	def test_preflight_verdict_drain_first_with_legacy_job(self):
		legacy_id = f"{frappe.local.site}||jarvis-turn|msgY|a0"

		class _FakeQ:
			def get_job_ids(self_inner):
				return [legacy_id]

		with (
			patch("frappe.utils.background_jobs.get_queues", return_value=[_FakeQ()]),
			patch("rq.registry.StartedJobRegistry", self._FakeReg),
			patch.object(admission, "_legacy_streaming_count", return_value=0),
		):
			res = admission.pump_cutover_preflight()
		self.assertFalse(res["clear"])
		self.assertEqual(res["verdict"], "drain_first")
		self.assertEqual(res["legacy_jobs"], 1)

	def test_preflight_clear_when_no_legacy_activity(self):
		with (
			patch("frappe.utils.background_jobs.get_queues", return_value=[]),
			patch("rq.registry.StartedJobRegistry", self._FakeReg),
			patch.object(admission, "_legacy_streaming_count", return_value=0),
		):
			res = admission.pump_cutover_preflight()
		self.assertTrue(res["clear"])
		self.assertEqual(res["verdict"], "clear")
		self.assertEqual(res["legacy_jobs"], 0)

	def test_preflight_fails_closed_on_scan_exception(self):
		# CDX-10: a queue/registry probe exception must NOT be swallowed into clear=True.
		# The scan is incomplete => scan_ok=False => verdict "scan_failed", clear=False.
		def _boom():
			raise RuntimeError("redis down")

		with (
			patch("frappe.utils.background_jobs.get_queues", side_effect=_boom),
			patch.object(admission, "_legacy_streaming_count", return_value=0),
		):
			res = admission.pump_cutover_preflight()
		self.assertFalse(res["clear"], "a faulted scan can NEVER report clear")
		self.assertEqual(res["verdict"], "scan_failed")
		self.assertFalse(res["scan_ok"])
		self.assertIn("error", res)

	def test_cutover_execute_recheck_catches_straggler(self):
		# CDX-10: pump_cutover_execute is ONE pass — preflight clear -> remove the kill
		# switch -> IMMEDIATE re-check. A legacy job that raced into that window flips the
		# re-check to drain_first, so execute RE-SETS the explicit 0 and reports RETRY.
		clear = {"clear": True, "verdict": "clear", "scan_ok": True, "legacy_jobs": 0, "legacy_streaming": 0}
		straggler = {
			"clear": False,
			"verdict": "drain_first",
			"scan_ok": True,
			"legacy_jobs": 1,
			"legacy_streaming": 0,
		}
		cfg_writes = []
		with (
			patch.object(admission, "pump_cutover_preflight", side_effect=[dict(clear), dict(straggler)]),
			patch(
				"frappe.installer.update_site_config",
				side_effect=lambda k, v, *a, **kw: cfg_writes.append((k, v)),
			),
		):
			res = admission.pump_cutover_execute()
		self.assertFalse(res["done"], "a straggler in the window blocks the cutover")
		self.assertEqual(res["verdict"], "retry")
		self.assertEqual(res["action"], "reverted")
		# It removed the key (absent = ON), then RE-SET the explicit 0 kill switch.
		self.assertEqual(cfg_writes, [("jarvis_pump_enabled", "None"), ("jarvis_pump_enabled", 0)])

	def test_cutover_execute_commits_when_recheck_still_clear(self):
		# CDX-10: both passes clear => remove the key ONCE, no revert, done=True.
		clear = {"clear": True, "verdict": "clear", "scan_ok": True, "legacy_jobs": 0, "legacy_streaming": 0}
		cfg_writes = []
		with (
			patch.object(admission, "pump_cutover_preflight", side_effect=[dict(clear), dict(clear)]),
			patch(
				"frappe.installer.update_site_config",
				side_effect=lambda k, v, *a, **kw: cfg_writes.append((k, v)),
			),
		):
			res = admission.pump_cutover_execute()
		self.assertTrue(res["done"])
		self.assertEqual(res["action"], "cutover")
		self.assertEqual(cfg_writes, [("jarvis_pump_enabled", "None")], "key removed once, no revert")

	def test_legacy_gate_reroutes_instead_of_enqueue_when_pump_flipped(self):
		# CDX-10 (forward, deterministic): a PURE-LEGACY sender reaches the enqueue boundary
		# and its under-lock gate re-check observes pump-ON (the cutover flipped it). It must
		# NOT enqueue an invisible legacy job — it reroutes to the pump accept path.
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1)
		run_id = "cutover_gate_logic"
		kwargs = {"conversation_id": conv, "message_id": seed, "run_id": run_id, "enqueued_at_ms": 1}
		enqueued, rerouted = [], []
		with (
			patch.object(admission, "turn_machine_enabled", return_value=True),  # flipped to pump-ON
			patch("frappe.enqueue", side_effect=lambda *a, **k: enqueued.append(k.get("job_id"))),
			patch.object(
				admission,
				"accept_or_queue",
				side_effect=lambda **k: rerouted.append(k["run_id"])
				or {"ok": True, "dispatched": False, "run_id": k["run_id"]},
			),
		):
			chat_api._dispatch_turn(kwargs, cutover_gate=True)
		self.assertEqual(enqueued, [], "CDX-10: no legacy RQ job enqueued after the flip")
		self.assertEqual(rerouted, [run_id], "the turn rerouted to the pump accept path")

	def test_legacy_gate_still_enqueues_when_site_stays_legacy(self):
		# CDX-10: the gate is transparent on a genuinely-legacy site — under the held lock it
		# re-checks, sees legacy, and enqueues exactly as before (no behavior change off the
		# cutover window).
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1)
		run_id = "cutover_gate_legacy"
		kwargs = {"conversation_id": conv, "message_id": seed, "run_id": run_id, "enqueued_at_ms": 1}
		enqueued, rerouted = [], []
		with (
			patch.object(admission, "turn_machine_enabled", return_value=False),  # still legacy
			patch.dict(frappe.local.conf, {"socketio_backend": ""}),  # node backend -> the RQ path
			patch("frappe.enqueue", side_effect=lambda *a, **k: enqueued.append(k.get("job_id"))),
			patch.object(admission, "accept_or_queue", side_effect=lambda **k: rerouted.append(k["run_id"])),
		):
			chat_api._dispatch_turn(kwargs, cutover_gate=True)
		self.assertEqual(len(enqueued), 1, "still-legacy: the RQ job enqueues under the held lock")
		self.assertEqual(rerouted, [], "no reroute when the site stays legacy")

	def test_accept_reads_pump_mode_under_the_shard_lock(self):
		# CDX-10 (reverse direction): accept_or_queue reads pump-vs-legacy mode AFTER acquiring
		# the shard lock (the cutover gate), so a flip-back cutover_execute commits under that
		# lock cannot interleave between the branch decision and the durable insert — a pump
		# sender never strands a pump-style Turn the draining pump won't promote.
		order = []
		real_lock = admission._lock_shard

		def rec_lock(t):
			order.append("lock")
			return real_lock(t)

		def rec_mode():
			order.append("mode")
			return False  # legacy branch — avoids pump ensure/wake side effects

		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1)
		with (
			patch.object(admission, "_lock_shard", side_effect=rec_lock),
			patch.object(pump, "pump_mode_active", side_effect=rec_mode),
			patch.object(chat_api, "_dispatch_turn", side_effect=lambda *a, **k: None),
		):
			admission.accept_or_queue(
				conversation=conv, run_id="rev_mode", seed_message=seed, dispatch=lambda: None
			)
		self.assertEqual(order[:1], ["lock"], "the shard lock is taken FIRST")
		self.assertIn("mode", order, "pump mode is read")
		self.assertLess(order.index("lock"), order.index("mode"), "pump mode read UNDER the shard lock")

	def test_paused_legacy_sender_lands_no_job_after_cutover_done(self):
		# CDX-10 (concurrent — codex's required test): a REAL legacy sender is paused at the
		# enqueue boundary (between turn_machine_enabled()==False and frappe.enqueue) while a
		# REAL pump_cutover_execute runs to done=True on a SEPARATE DB connection; when the
		# sender is released it acquires the (now-free) shard control-row lock, re-checks under
		# it, sees pump-ON and PROVES no legacy job lands (it reroutes instead). The shard
		# control row FOR UPDATE that both paths take is the serialization point.
		conv = self._mk_conv()
		seed = self._mk_msg(conv, 1)
		run_id = "cutover_race_S"
		site = frappe.local.site
		state = {"pump_on": False}
		c_done = threading.Event()
		enqueued, rerouted, errors = [], [], []

		def fake_scan(*a, **k):  # both cutover passes report clear (RQ scan stubbed)
			return {
				"clear": True,
				"verdict": "clear",
				"scan_ok": True,
				"legacy_jobs": 0,
				"legacy_streaming": 0,
			}

		def fake_flip(key, value, *a, **kw):  # cutover's flip toggles the shared, cross-thread holder
			if key == "jarvis_pump_enabled":
				state["pump_on"] = value == "None"

		def cutover_worker():
			frappe.init(site=site)
			frappe.connect()
			frappe.set_user(TEST_USER)
			try:
				with (
					patch.object(admission, "pump_cutover_preflight", side_effect=fake_scan),
					patch("frappe.installer.update_site_config", side_effect=fake_flip),
				):
					res = admission.pump_cutover_execute()
					if not res.get("done"):
						errors.append(("C", res))
			except Exception as e:
				errors.append(("C", e))
			finally:
				try:
					frappe.db.commit()
				finally:
					c_done.set()
					frappe.destroy()

		def sender_worker():
			frappe.init(site=site)
			frappe.connect()
			frappe.set_user(TEST_USER)
			try:
				# Paused at the enqueue boundary until the cutover has committed done=True.
				c_done.wait(timeout=20)
				kwargs = {
					"conversation_id": conv,
					"message_id": seed,
					"run_id": run_id,
					"enqueued_at_ms": 1,
				}
				with (
					patch.object(admission, "turn_machine_enabled", side_effect=lambda: state["pump_on"]),
					patch("frappe.enqueue", side_effect=lambda *a, **k: enqueued.append(k.get("job_id"))),
					patch.object(
						admission,
						"accept_or_queue",
						side_effect=lambda **k: rerouted.append(k["run_id"])
						or {"ok": True, "dispatched": False, "run_id": k["run_id"]},
					),
				):
					chat_api._dispatch_turn(kwargs, cutover_gate=True)
			except Exception as e:
				errors.append(("S", e))
			finally:
				try:
					frappe.db.commit()
				finally:
					frappe.destroy()

		tC = threading.Thread(target=cutover_worker)
		tS = threading.Thread(target=sender_worker)
		tC.start()
		tS.start()
		tC.join(timeout=30)
		tS.join(timeout=30)
		self.assertEqual(errors, [], f"worker error: {errors}")
		self.assertTrue(state["pump_on"], "cutover reached done=True and flipped to pump-ON")
		self.assertEqual(enqueued, [], "CDX-10: NO legacy job landed after the cutover committed")
		self.assertEqual(rerouted, [run_id], "the paused legacy sender rerouted to the pump accept path")
