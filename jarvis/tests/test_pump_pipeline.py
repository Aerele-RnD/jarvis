"""WP-1d — end-to-end pump-pipeline tests (accept -> prepare -> dispatch ->
settle -> finalize) + the PANEL matrix rows WP-1d owns.

These drive the REAL prepare / settlement / finalize jobs in-process against the
real ``turn_state`` CAS library + WP-1b's transport double (only the gateway
socket + the openclaw pool checkout are faked). The two enrichment side effects
that do real HTTP/gateway work (rich outputs, usage poll) are mocked at their
boundary so the LEDGER machinery (claim/complete/force-done/finalize_done) runs
for real.

Coverage:
  * full pipeline: accept(pump) -> promote+prepare(REAL) -> ready -> pump dispatch
    -> frames -> terminal -> REAL settlement -> REAL finalize -> done, asserting
    every D1 spot-check owner ran its effect exactly once;
  * PANEL 4 (retry/orphan through the chokepoint: no duplicate user row, seq
    monotonic under the conv lock);
  * PANEL 5 (kill during preparing -> recovering -> queued -> fresh prepare;
    session at-most-once, OAR-4);
  * PANEL 8 (unfinishable enrichment -> force-done at 3 -> turn reaches done ->
    watchdog stops);
  * PANEL 10 (draining coexistence: new turns go legacy, dual-signal sees pump
    in-flight, promote/sweep step back);
  * two-writer settlement (pump terminal + racing recovery, both orders, side
    effects exactly once);
  * SUX-11 error-payload contract preserved through Turn.error/terminal_payload;
  * usage (turn_id) idempotency under finalize replay.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import frappe

from jarvis.chat import admission, finalize, prepare, pump, settlement
from jarvis.chat import turn_state as ts
from jarvis.tests.test_pump import TEST_USER, _PumpTestCase, _Recorder

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"
TURN = "Jarvis Chat Turn"
EFFECT = "Jarvis Turn Effect"
SESSION = "Jarvis Chat Session"


class _FakeSess:
	"""In-process stand-in for a pooled OpenclawSession — the bootstrap RPCs
	(prepare) + the usage poll (finalize) with NO real socket."""

	def __init__(self):
		self._key = None
		self.model_patches: list = []
		self.created = 0

	def create_session(self, label: str = "x") -> str:
		self.created += 1
		self._key = "sess-" + frappe.generate_hash(length=8)
		return self._key

	def set_session_model(self, key, ref):
		self.model_patches.append((key, ref))

	def get_session_messages(self, key, limit=5):
		return []

	def list_sessions(self):
		return [
			{
				"key": self._key,
				"totalTokensFresh": True,
				"inputTokens": 120,
				"outputTokens": 30,
				"totalTokens": 900,
				"model": "test-model",
			}
		]

	def close(self):
		pass


class _PipelineCase(_PumpTestCase):
	def setUp(self):
		super().setUp()
		self._pubs: list = []
		# Capture every fenced publish (turn_state routes them through
		# events.publish_to_user, imported into turn_state at module load).
		self._pub_patch = patch.object(
			ts, "publish_to_user", lambda user, payload: self._pubs.append(payload)
		)
		self._pub_patch.start()

	def tearDown(self):
		self._pub_patch.stop()
		# Clean the Jarvis Chat Session rows prepare created for this test's convs
		# (owned by TEST_USER — the seed-message sender / chat_user).
		try:
			frappe.db.delete(SESSION, {"user": TEST_USER})
		except Exception:
			pass
		super().tearDown()

	def _acquire_fresh(self, holder="pipe"):
		"""Force the shard lease vacant, then acquire — so repeated acquires within
		one test (subtests) never fail on a still-live 30s lease."""
		frappe.db.set_value(
			"Jarvis Relay Pump",
			self._target,
			"lease_expires_at",
			frappe.utils.add_to_date(None, seconds=-5),
			update_modified=False,
		)
		frappe.db.commit()
		won, epoch = ts.lease_acquire(self._target, holder)
		self.assertTrue(won, "fresh lease acquire failed")
		return epoch

	# ---- pump-on context + gateway mock ---------------------------------- #

	@contextmanager
	def _pump_on(self, *, ensure=None):
		"""Force pump-mode active + configured and stub the wake so accept/prepare
		never enqueue a real hop."""
		with (
			patch.object(pump, "pump_mode_active", return_value=True),
			patch.object(pump, "pump_configured", return_value=True),
			patch.object(pump, "ensure_pump", ensure or (lambda *a, **k: {"enqueued": False})),
			patch.object(pump, "lpush_wake", lambda *a, **k: None),
		):
			yield

	@contextmanager
	def _gateway(self, fake: _FakeSess):
		@contextmanager
		def _co(url):
			yield fake

		with patch("jarvis.chat.openclaw_session_pool.checkout", _co):
			yield

	@contextmanager
	def _mock_enrichment(self):
		"""Mock the enrichment effect BOUNDARIES (real HTTP/gateway/macro) with
		recorders; the finalize ledger loop itself stays real."""
		recs = {
			"rich": _Recorder(),
			"macro": _Recorder(),
			"applearn": _Recorder(),
			"title": _Recorder(),
			"usage": _Recorder(),
		}
		with (
			patch("jarvis.chat.turn_handler.persist_rich_outputs", recs["rich"]),
			patch("jarvis.chat.macros.advance_after_turn", recs["macro"]),
			patch("jarvis.learning.app_analysis.on_turn_end", recs["applearn"]),
			patch("jarvis.chat.title.enqueue_autotitle", recs["title"]),
			patch("jarvis.chat.usage.record_turn_usage", recs["usage"]),
			patch("jarvis.chat.wiki.wiki_enabled", return_value=False),
		):
			yield recs

	def _effects(self, run_id):
		return {
			r["effect_name"]: r["status"]
			for r in frappe.get_all(EFFECT, filters={"turn": run_id}, fields=["effect_name", "status"])
		}

	def _pub_kinds(self):
		return [p.get("kind") for p in self._pubs]


# --------------------------------------------------------------------------- #
# 1. Full pipeline end-to-end
# --------------------------------------------------------------------------- #


class TestPumpPipelineE2E(_PipelineCase):
	def test_full_pipeline_accept_prepare_dispatch_settle_finalize_done(self):
		conv = self._mk_conv()  # no session_key
		seed = self._mk_msg(conv, content="hello")
		rid = "pmp_pipe"
		fake = _FakeSess()
		double = self._double()

		# 1. ACCEPT (pump mode): the send routes to the pump; the turn is queued,
		#    no legacy dispatch. (No user row inserted — seed already exists.)
		ensure_rec = _Recorder()
		with (
			self._pump_on(ensure=ensure_rec),
			patch.object(admission, "relay_target_id", lambda conversation=None: self._target),
		):
			adm = admission.accept_or_queue(
				conversation=conv, run_id=rid, seed_message=seed, dispatch=lambda: None
			)
		self.assertTrue(adm.get("pump"))
		self.assertEqual(self._state(rid), "queued")
		self.assertGreaterEqual(ensure_rec.count, 1, "accept woke the pump (§8-E PRIMARY)")

		# 2. PROMOTE (reserve credit under the shard lock) + PREPARE (REAL job).
		#    dispatch_prepare runs prepare.run_prepare in-process; the gateway pool
		#    checkout is faked so session bootstrap/model-patch/watermark are real DB
		#    writes without a socket.
		def real_prepare(run_id, target):
			with self._gateway(fake), self._pump_on():
				prepare.run_prepare(run_id, target)

		deps = self._deps(double=double, prepare=real_prepare)
		ctx = self._make_ctx(deps)
		pump._promote_queued(ctx)

		# prepare drove queued->preparing->ready; R-1: it inserted the assistant
		# placeholder and linked it; #22: it created the session (at-most-once).
		self.assertEqual(self._state(rid), "ready")
		amsg = self._val(rid, "assistant_message")
		self.assertIsNotNone(amsg, "R-1: prepare inserted+linked the assistant placeholder")
		self.assertEqual(int(frappe.db.get_value(MSG, amsg, "streaming")), 1)
		self.assertEqual(fake.created, 1, "session created exactly once")
		self.assertTrue(frappe.db.get_value(CONV, conv, "session_key"))
		dp = json.loads(self._val(rid, "dispatch_payload"))
		self.assertTrue(dp["session_key"] and dp["message"], "prepare->pump handoff payload written")

		# 3. DISPATCH + STREAM + TERMINAL + REAL SETTLEMENT.
		double.arm(rid, "success")
		self._pump_until(ctx, lambda: self._state(rid) in ("finalizing", "done"))
		self.assertEqual(self._state(rid), "finalizing", "REAL settlement released the slot")
		self.assertEqual(int(self._val(rid, "reserved")), 0)
		self.assertIsNotNone(self._val(rid, "gateway_run_id"))
		# The pump published the fenced run:start (R-1) and the settlement run:end.
		self.assertIn("run:start", self._pub_kinds())
		self.assertIn("run:end", self._pub_kinds())
		# Settlement fixed the owed-enrichment set (OAR-9).
		eff = self._effects(rid)
		self.assertEqual(set(eff), set(settlement.FINAL_EFFECTS))
		self.assertTrue(all(v == "pending" for v in eff.values()))

		# 4. REAL finalize off the ledger -> done + message:enriched (SUX-7).
		with self._gateway(fake), self._mock_enrichment() as recs:
			out = finalize.run_finalize(rid, self._target)
		self.assertTrue(out["done"])
		self.assertEqual(self._state(rid), "done")
		self.assertIn("message:enriched", self._pub_kinds())
		# Every owed effect reached done exactly once (D1 spot-check).
		self.assertTrue(all(v == "done" for v in self._effects(rid).values()))
		self.assertEqual(recs["rich"].count, 1, "rich_outputs owner ran once")
		self.assertEqual(recs["macro"].count, 1, "macro_advance owner ran once")
		self.assertEqual(recs["title"].count, 1, "auto_title owner ran once")
		self.assertEqual(recs["usage"].count, 1, "usage recorded once")
		self.assertEqual(int(self._val(rid, "usage_recorded")), 1, "R-4 (turn_id) guard set")

		# 5. Re-running finalize is a total no-op (idempotent).
		with self._gateway(fake), self._mock_enrichment() as recs2:
			out2 = finalize.run_finalize(rid, self._target)
		self.assertTrue(out2.get("already_done"))
		self.assertEqual(recs2["usage"].count, 0, "no effect re-runs after done")


# --------------------------------------------------------------------------- #
# 2. PANEL 4 — retry/orphan through the chokepoint (no dup user row, monotonic seq)
# --------------------------------------------------------------------------- #


class TestPanel4Chokepoint(_PipelineCase):
	def test_retry_and_orphan_reuse_seed_no_dup_user_row(self):
		conv = self._mk_conv()
		seed = self._mk_msg(conv, content="first")
		before = frappe.db.count(MSG, {"conversation": conv, "role": "user"})
		with self._pump_on():
			# retry reuses the EXISTING user message (OAR-3) — no new user row.
			admission.accept_or_queue(
				conversation=conv, run_id="pmp_p4_retry", seed_message=seed, dispatch=lambda: None
			)
			# orphan re-dispatch (background) reuses it too.
			admission.accept_or_queue(
				conversation=conv,
				run_id="pmp_p4_orphan",
				seed_message=seed,
				turn_class="background",
				dispatch=lambda: None,
			)
		after = frappe.db.count(MSG, {"conversation": conv, "role": "user"})
		self.assertEqual(after, before, "retry/orphan inserted NO duplicate user row")

	def test_placeholder_seq_monotonic_under_conv_lock(self):
		conv = self._mk_conv()
		# A tool receipt sits at some seq; prepare's placeholder must not collide.
		self._mk_msg(conv, role="user", content="u1")
		self._mk_msg(conv, role="tool", content="t1")
		p1 = prepare._create_placeholder_locked(conv)
		self._mk_msg(conv, role="tool", content="t2")
		p2 = prepare._create_placeholder_locked(conv)
		seqs = [frappe.db.get_value(MSG, m, "seq") for m in (p1, p2)]
		self.assertTrue(seqs[0] < seqs[1], f"placeholder seq monotonic: {seqs}")
		# Unique + gap-free against everything on the conversation.
		all_seqs = frappe.get_all(MSG, filters={"conversation": conv}, pluck="seq")
		self.assertEqual(len(all_seqs), len(set(all_seqs)), "no seq collision")


# --------------------------------------------------------------------------- #
# 3. PANEL 5 — kill during preparing -> recovering -> queued -> fresh prepare
# --------------------------------------------------------------------------- #


class TestPanel5PrepareKill(_PipelineCase):
	def test_kill_during_preparing_recovers_and_session_at_most_once(self):
		conv = self._mk_conv()
		seed = self._mk_msg(conv, content="hi")
		rid = "pmp_p5"
		self._mk_turn(conv, rid, seed, "queued", version=1, reserved=1)
		fake = _FakeSess()

		# First prepare runs (creates the session, sets conv.session_key), then the
		# pump "dies" — we simulate by parking the preparing turn to recovering and
		# recovering it back to queued for a FRESH prepare (OAR-4).
		with self._gateway(fake), self._pump_on():
			prepare.run_prepare(rid, self._target)
		self.assertEqual(self._state(rid), "ready")
		self.assertEqual(fake.created, 1)
		first_key = frappe.db.get_value(CONV, conv, "session_key")
		self.assertTrue(first_key)
		self.assertEqual(frappe.db.count(SESSION, {"session_key": first_key}), 1)

		# Simulate the kill: watchdog parks -> recovering, then recovers PRE-dispatch
		# (dispatching_at IS NULL) back to queued, dropping stale prepare refs.
		v = int(self._val(rid, "version"))
		self.assertTrue(ts.mark_recovering(rid, v))
		frappe.db.commit()
		self.assertTrue(ts.recover_to_queued(rid, v + 1))
		frappe.db.commit()
		self.assertEqual(self._state(rid), "queued")
		self.assertIsNone(self._val(rid, "assistant_message"), "stale prepare refs dropped")
		# recover_to_queued released the credit; re-grant it (the pump's promote does).
		self.assertTrue(ts.reserve_credit(rid))
		frappe.db.commit()

		# FRESH prepare — session at-most-once: it must REUSE the existing session,
		# never create a second (OAR-4 "session at-most-once absorbs the leak").
		with self._gateway(fake), self._pump_on():
			prepare.run_prepare(rid, self._target)
		self.assertEqual(self._state(rid), "ready")
		self.assertEqual(fake.created, 1, "no second session created on re-prepare")
		self.assertEqual(frappe.db.get_value(CONV, conv, "session_key"), first_key)
		self.assertEqual(frappe.db.count(SESSION, {"user": TEST_USER}), 1)


# --------------------------------------------------------------------------- #
# 4. PANEL 8 — unfinishable enrichment -> force-done at 3 -> turn reaches done
# --------------------------------------------------------------------------- #


class TestPanel8ForceDone(_PipelineCase):
	def test_unfinishable_effect_force_done_turn_reaches_done(self):
		conv = self._mk_conv()
		seed = self._mk_msg(conv)
		amsg = self._mk_msg(conv, role="assistant", content="ans", streaming=0)
		rid = "pmp_p8"
		# A settled (finalizing) turn owing exactly two effects: one that always
		# FAILS (macro_advance) + one that succeeds (telemetry_flush).
		self._mk_turn(conv, rid, seed, "finalizing", version=5, assistant_message=amsg)
		ts.insert_required_effects(rid, ("macro_advance", "telemetry_flush"))
		frappe.db.commit()

		calls = {"n": 0}

		def boom(*a, **k):
			calls["n"] += 1
			raise RuntimeError("enrichment permanently broken")

		# Drive finalize repeatedly (the watchdog's re-enqueue cadence). The failing
		# effect force-dones after FINALIZE_MAX_ATTEMPTS=3 so the turn ALWAYS reaches
		# done — a permanently-broken enrichment can never strand a settled turn.
		with patch("jarvis.chat.macros.advance_after_turn", boom):
			for _ in range(ts.FINALIZE_MAX_ATTEMPTS + 2):
				if self._state(rid) == "done":
					break
				finalize.run_finalize(rid, self._target)

		self.assertEqual(self._state(rid), "done", "turn reached done despite a broken effect")
		self.assertEqual(calls["n"], ts.FINALIZE_MAX_ATTEMPTS, "the effect was attempted exactly the budget")
		eff = self._effects(rid)
		self.assertEqual(eff["macro_advance"], "done", "force-done after the budget")
		self.assertEqual(eff["telemetry_flush"], "done")
		# Watchdog now STOPS re-enqueuing (state is terminal, not finalizing).
		fin_rec = _Recorder()
		wd_deps = pump.PumpDeps()
		wd_deps.enqueue_finalize = fin_rec
		wd_deps.enqueue_pump_job = _Recorder()
		pump.watchdog(deps=wd_deps)
		self.assertEqual(fin_rec.count, 0, "no finalize re-enqueue for a done turn")


# --------------------------------------------------------------------------- #
# 5. PANEL 10 — draining coexistence
# --------------------------------------------------------------------------- #


class TestPanel10Draining(_PipelineCase):
	def test_draining_new_turns_legacy_dual_signal_sees_pump(self):
		conv = self._mk_conv()
		seed = self._mk_msg(conv)
		amsg = self._mk_msg(conv, role="assistant", content="", streaming=1)
		rid = "pmp_p10"
		# An in-flight PUMP turn (streaming) that is draining.
		self._mk_turn(
			conv, rid, seed, "streaming", version=4, pump_epoch=1, reserved=1, assistant_message=amsg
		)
		frappe.db.commit()

		with (
			patch.object(pump, "pump_mode_active", return_value=False),
			patch.object(pump, "pump_draining", return_value=True),
			patch.object(pump, "pump_configured", return_value=True),
			patch.object(admission, "admission_enabled", return_value=True),
		):
			# 1. No NEW pump admissions: new turns fall through to the LEGACY path.
			self.assertFalse(
				admission.turn_machine_enabled(),
				"draining routes NEW turns to legacy (no Turn row)",
			)
			# 2. Dual-signal (OAR-11) COVERS pump-mode: the draining pump's streaming
			#    turn counts as shard inflight AND as a busy conversation, so a new
			#    legacy send can't double-admit onto it.
			self.assertGreaterEqual(
				admission._shard_inflight(self._target), 1, "pump streaming counts as inflight"
			)
			self.assertTrue(
				admission._conv_has_other_active_turn(conv, "other"),
				"pump streaming turn makes the conversation busy",
			)
			# 3. Phase-0 promote/sweep STEP BACK (they must never touch pump rows).
			with patch("jarvis.chat.admission._dispatch_promoted") as disp:
				self.assertEqual(admission.promote_next(self._target), 0)
				disp.assert_not_called()
			self.assertEqual(
				admission.sweep(), {"reclaimed": 0, "reconciled": 0, "aged_out": 0, "promoted": 0}
			)
			# The pump turn was NOT touched by Phase-0.
			self.assertEqual(self._state(rid), "streaming")


# --------------------------------------------------------------------------- #
# 6. Two-writer settlement — exactly-once under a racing recovery (both orders)
# --------------------------------------------------------------------------- #


class TestTwoWriterSettlement(_PipelineCase):
	def _seed_terminal_observed(self, conv, rid, epoch):
		seed = self._mk_msg(conv)
		amsg = self._mk_msg(conv, role="assistant", content="partial", streaming=1)
		self._mk_turn(
			conv,
			rid,
			seed,
			"terminal_observed",
			version=6,
			pump_epoch=epoch,
			reserved=1,
			assistant_message=amsg,
			terminal_kind="relay:final",
			terminal_payload=json.dumps({"text": "final answer"}),
			terminal_observed_at=frappe.utils.now(),
			dispatching_at=frappe.utils.now(),
		)
		return amsg

	def _settle(self, rid, conv, epoch, deps):
		settlement.invoke_settlement(
			rid,
			relay_target_id=self._target,
			epoch=epoch,
			version=7,
			terminal_kind="relay:final",
			terminal_payload={"text": "final answer"},
			assistant_message=None,
			owner=self._orig_user,
			conversation=conv,
			deps=deps,
		)

	def test_two_settlement_writers_side_effects_exactly_once(self):
		# Two invocations of settlement race on the SAME terminal_observed turn (the
		# pump's on_terminal AND the reconcile/recovery path). The epoch+version CAS
		# + the state guard make exactly ONE win; the loser is a no-op. Side effects
		# (final projection, slot release, effect-ledger rows, run:end) apply once.
		for order in ("terminal_first", "recovery_first"):
			with self.subTest(order=order):
				_cleanup_rid = f"pmp_2w_{order}"
				conv = self._mk_conv()
				epoch = self._acquire_fresh("twowriter")
				amsg = self._seed_terminal_observed(conv, _cleanup_rid, epoch)
				fin_rec = _Recorder()
				deps = pump.PumpDeps()
				deps.enqueue_finalize = fin_rec
				self._pubs.clear()

				self._settle(_cleanup_rid, conv, epoch, deps)  # winner
				# Second writer (either order maps to the same idempotent call).
				try:
					self._settle(_cleanup_rid, conv, epoch, deps)  # loser -> no-op
				except ts.LeaseLostExit:
					pass

				self.assertEqual(self._state(_cleanup_rid), "finalizing")
				self.assertEqual(int(self._val(_cleanup_rid, "reserved")), 0)
				# final projection written once.
				self.assertEqual(frappe.db.get_value(MSG, amsg, "content"), "final answer")
				# effect rows inserted exactly once (composite PK idempotent).
				self.assertEqual(len(self._effects(_cleanup_rid)), len(settlement.FINAL_EFFECTS))
				# exactly one run:end published, one finalize enqueued.
				self.assertEqual(self._pub_kinds().count("run:end"), 1)
				self.assertEqual(fin_rec.count, 1)


# --------------------------------------------------------------------------- #
# 7. SUX-11 — error-payload contract preserved
# --------------------------------------------------------------------------- #


class TestSux11ErrorContract(_PipelineCase):
	def test_error_terminal_preserves_classification(self):
		conv = self._mk_conv()
		seed = self._mk_msg(conv)
		amsg = self._mk_msg(conv, role="assistant", content="streamed so far", streaming=1)
		rid = "pmp_sux11"
		won, epoch = ts.lease_acquire(self._target, "sux11")
		self._mk_turn(
			conv,
			rid,
			seed,
			"terminal_observed",
			version=3,
			pump_epoch=epoch,
			reserved=1,
			assistant_message=amsg,
			terminal_kind="relay:error",
			terminal_payload=json.dumps({"state": "error", "error": "provider quota exceeded"}),
			terminal_observed_at=frappe.utils.now(),
		)
		fin_rec = _Recorder()
		deps = pump.PumpDeps()
		deps.enqueue_finalize = fin_rec
		self._pubs.clear()

		settlement.invoke_settlement(
			rid,
			relay_target_id=self._target,
			epoch=epoch,
			version=4,
			terminal_kind="relay:error",
			terminal_payload={"state": "error", "error": "provider quota exceeded"},
			assistant_message=None,
			owner=self._orig_user,
			conversation=conv,
			deps=deps,
		)
		self.assertEqual(self._state(rid), "errored")
		# The Message.error is set + streaming cleared; the streamed content is
		# PRESERVED (not overwritten with the error), matching legacy _mark_errored.
		row = frappe.db.get_value(MSG, amsg, ["error", "streaming", "content"], as_dict=True)
		self.assertEqual(row["error"], "provider quota exceeded")
		self.assertEqual(int(row["streaming"]), 0)
		self.assertEqual(row["content"], "streamed so far")
		# The run:error event carries today's classification code (SUX-11).
		err_pub = next(p for p in self._pubs if p.get("kind") == "run:error")
		self.assertEqual(err_pub["error"], "provider quota exceeded")
		self.assertEqual(err_pub["code"], "provider", "quota -> 'provider' headline (ERROR_HEADLINES)")
		# Turn.error mirrors it too.
		self.assertEqual(self._val(rid, "error"), "provider quota exceeded")


# --------------------------------------------------------------------------- #
# 8. Usage (turn_id) idempotency under finalize replay
# --------------------------------------------------------------------------- #


class TestUsageIdempotency(_PipelineCase):
	def test_usage_recorded_once_under_replay(self):
		conv = self._mk_conv()
		seed = self._mk_msg(conv)
		amsg = self._mk_msg(conv, role="assistant", content="ans", streaming=0)
		rid = "pmp_usage"
		frappe.db.set_value(CONV, conv, "session_key", "sess-usage-x")
		self._mk_turn(conv, rid, seed, "finalizing", version=5, assistant_message=amsg)
		ts.insert_required_effects(rid, ("usage",))
		frappe.db.commit()
		fake = _FakeSess()
		fake._key = "sess-usage-x"
		rec = _Recorder()

		# Two finalize passes (a replay) — record_turn_usage must fire AT MOST ONCE
		# (the usage_recorded (turn_id) CAS guard, R-4). The soft cap is never
		# double-counted.
		with self._gateway(fake), patch("jarvis.chat.usage.record_turn_usage", rec):
			finalize.run_finalize(rid, self._target)
			finalize.run_finalize(rid, self._target)

		self.assertEqual(rec.count, 1, "usage recorded exactly once across the replay")
		self.assertEqual(int(self._val(rid, "usage_recorded")), 1)
		self.assertEqual(self._state(rid), "done")

	def test_usage_guard_rolls_back_on_poll_failure_and_retries(self):
		conv = self._mk_conv()
		seed = self._mk_msg(conv)
		amsg = self._mk_msg(conv, role="assistant", content="ans", streaming=0)
		rid = "pmp_usage_fail"
		frappe.db.set_value(CONV, conv, "session_key", "sess-usage-y")
		self._mk_turn(conv, rid, seed, "finalizing", version=5, assistant_message=amsg)
		ts.insert_required_effects(rid, ("usage",))
		frappe.db.commit()
		fake = _FakeSess()
		fake._key = "sess-usage-y"

		# A transient poll failure must ROLL BACK the guard so usage retries next
		# cycle (never a silent permanent loss on a hiccup).
		with (
			self._gateway(fake),
			patch("jarvis.chat.usage.fetch_fresh_session_row", side_effect=RuntimeError("gateway hiccup")),
		):
			finalize.run_finalize(rid, self._target)
		self.assertEqual(int(self._val(rid, "usage_recorded")), 0, "guard rolled back on failure")
		self.assertEqual(self._effects(rid)["usage"], "pending", "usage effect stays pending for retry")

		# The retry succeeds and records once.
		rec = _Recorder()
		with self._gateway(fake), patch("jarvis.chat.usage.record_turn_usage", rec):
			finalize.run_finalize(rid, self._target)
		self.assertEqual(rec.count, 1)
		self.assertEqual(self._state(rid), "done")
