"""WP-1c — tests for jarvis.chat.pump (the Relay Pump reactor).

The pump is driven against the REAL ``turn_state`` CAS library on the real DB
(patterntest) plus WP-1b's transport double (``test_relay_mux._DoubleGateway``,
which replays the WP-2 harness transcripts frame-for-frame at the exact
``_recv``/``_send`` seam). Only the socket is doubled; every millisecond of the
mux reader-loop demux and every turn CAS is real. The two WP-1d seams (prepare
dispatcher + settlement/finalize invoker) and the internal enqueue seam are
injected so nothing hits RQ and each hand-off is asserted at the args level.

Coverage (the WP-1c acceptance set):
  * cold-start full lifecycle (queued -> prepare-stub -> ready -> dispatched ->
    streamed -> terminal_observed -> settlement invoked) over fake frames;
  * idle-exit vs concurrent-send race — BOTH D6 §2 orderings;
  * hop handoff (fresh job id, timeout=180, queue=long — asserted, successor NOT
    run);
  * takeover fencing (a second acquire re-stamps the epoch; the old context's
    write affects 0 rows);
  * watchdog per-state matrix (queued age-out, stale-preparing past 300s ->
    fresh prepare, finalizing re-enqueue-only, ensure_pump revive);
  * ack-timeout park vs DEFINITE-rejection errored (PANEL test 7);
  * WS drop w/ outstanding ack -> immediate sentinel -> park (PANEL test 9);
  * cancel flow end-to-end;
  * DB-disconnect bounded backoff -> park recovering -> exit hop;
  * credit lifecycle across promote/dispatch/settle under the shard lock
    (PANEL tests 2/3), and cross-conversation over-admit at promote (PANEL 1);
  * the raw-redis wake bus round-trip.

Each test uses a UNIQUE per-test ``relay_target_id`` so it never touches the
site-wide "default" admission shard the WP-0 suite counts.
"""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat import pump
from jarvis.chat import turn_state as ts
from jarvis.chat.relay_mux import RelayMux
from jarvis.tests.test_relay_mux import _DoubleGateway

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"
TURN = "Jarvis Chat Turn"
PUMP = "Jarvis Relay Pump"
EFFECT = "Jarvis Turn Effect"
TEST_USER = "jarvis-pump-test@example.com"
TARGET_PREFIX = "pmpx_"


def _ensure_test_user(user: str = TEST_USER) -> None:
	if frappe.db.exists("User", user):
		return
	doc = frappe.get_doc(
		{
			"doctype": "User",
			"email": user,
			"first_name": "Pump",
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
	conv_names = frappe.get_all(CONV, filters={"owner": user}, pluck="name")
	for name in conv_names:
		turn_names = frappe.get_all(TURN, filters={"conversation": name}, pluck="name")
		if turn_names:
			frappe.db.delete(EFFECT, {"turn": ["in", turn_names]})
		frappe.db.delete(TURN, {"conversation": name})
		frappe.db.delete(MSG, {"conversation": name})
		frappe.delete_doc(CONV, name, ignore_permissions=True, force=True)
	frappe.db.delete(PUMP, {"relay_target_id": ["like", f"{TARGET_PREFIX}%"]})
	frappe.db.commit()


# --------------------------------------------------------------------------- #
# Enqueue / seam recorders
# --------------------------------------------------------------------------- #


class _Recorder:
	def __init__(self):
		self.calls: list = []

	def __call__(self, *args, **kwargs):
		self.calls.append((args, kwargs))

	@property
	def count(self):
		return len(self.calls)


class _PumpTestCase(FrappeTestCase):
	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup()
		self._target = f"{TARGET_PREFIX}{frappe.generate_hash(length=10)}"
		ts._ensure_control_row(self._target)
		ts.reset_lock_tracking()
		self._muxes: list[RelayMux] = []
		self._doubles: list[_DoubleGateway] = []
		# Remove real waits from the DB-disconnect backoff path.
		self._sleep_patch = patch.object(pump, "_sleep", lambda *_a, **_k: None)
		self._sleep_patch.start()
		# OARF-9: activate the canonical lock-order assertion for the whole pump
		# suite so an inversion (control->conversation->turn->message) FAILS a test
		# instead of silently log_error-ing. patterntest sets neither developer_mode
		# nor this flag, so without it assert_lock_order is a no-op everywhere.
		self._lock_assert_prev = frappe.local.conf.get("jarvis_pump_lock_assert")
		frappe.local.conf["jarvis_pump_lock_assert"] = 1

	def tearDown(self):
		if self._lock_assert_prev is None:
			frappe.local.conf.pop("jarvis_pump_lock_assert", None)
		else:
			frappe.local.conf["jarvis_pump_lock_assert"] = self._lock_assert_prev
		self._sleep_patch.stop()
		for mux in self._muxes:
			try:
				mux.stop(timeout=3)
			except Exception:
				pass
		for d in self._doubles:
			try:
				d.stop()
			except Exception:
				pass
		ts.reset_lock_tracking()
		_cleanup()
		frappe.set_user(self._orig_user)

	# ---- fixtures --------------------------------------------------------- #

	def _mk_conv(self) -> str:
		doc = frappe.get_doc({"doctype": CONV, "title": "New chat", "status": "Active"})
		doc.flags.ignore_permissions = True
		doc.insert()
		frappe.db.commit()
		return doc.name

	def _next_seq(self, conv: str) -> int:
		return (
			frappe.db.sql(f"SELECT MAX(seq) FROM `tab{MSG}` WHERE conversation=%(c)s", {"c": conv})[0][0] or 0
		) + 1

	def _mk_msg(self, conv: str, role: str = "user", content: str = "hi", **extra) -> str:
		doc = frappe.get_doc(
			{
				"doctype": MSG,
				"conversation": conv,
				"seq": self._next_seq(conv),
				"role": role,
				"content": content,
				**extra,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		frappe.db.commit()
		return doc.name

	def _mk_turn(self, conv, run_id, seed, state, *, version=1, pump_epoch=0, reserved=0, **extra) -> None:
		row = {
			"doctype": TURN,
			"run_id": run_id,
			"conversation": conv,
			"relay_target_id": self._target,
			"turn_class": "interactive",
			"state": state,
			"version": version,
			"pump_epoch": pump_epoch,
			"seed_message": seed,
			"reserved": reserved,
			"enqueued_at": frappe.utils.now(),
		}
		row.update(extra)
		frappe.get_doc(row).insert(ignore_permissions=True)
		frappe.db.commit()

	def _state(self, run_id) -> str:
		return frappe.db.get_value(TURN, run_id, "state")

	def _val(self, run_id, field):
		return frappe.db.get_value(TURN, run_id, field)

	# ---- deps + ctx helpers ---------------------------------------------- #

	def _double(self) -> _DoubleGateway:
		d = _DoubleGateway()
		self._doubles.append(d)
		return d

	def _deps(self, *, double=None, prepare=None, settlement=None, snapshot=None) -> pump.PumpDeps:
		d = pump.PumpDeps()
		d.dispatch_prepare = prepare or _Recorder()
		d.enqueue_finalize = _Recorder()
		d.enqueue_pump_job = _Recorder()
		d.apply_tool = _Recorder()
		d.snapshot = snapshot or (lambda ctx: {"gateway_active": 0, "active_session_keys": None})
		if settlement is not None:
			d.invoke_settlement = settlement
		if double is not None:
			d.make_mux = self._make_mux_factory(double)
		return d

	def _make_mux_factory(self, double):
		def factory(target, epoch):
			mux = RelayMux(double, target).start()
			self._muxes.append(mux)
			return mux

		return factory

	def _make_ctx(self, deps, *, holder="hop-test", hop_counter=0, with_mux=True) -> pump.PumpContext:
		won, epoch = ts.lease_acquire(self._target, holder, hop_counter=hop_counter)
		self.assertTrue(won, "test ctx failed to acquire the lease")
		ctx = pump.PumpContext(
			relay_target_id=self._target,
			epoch=epoch,
			holder=holder,
			hop_counter=hop_counter,
			site=frappe.local.site,
			deps=deps,
		)
		now = pump._monotonic()
		ctx.soft_deadline = now + 999
		ctx.hard_deadline = now + 999
		ctx.last_heartbeat = now
		if with_mux:
			ctx.mux = deps.make_mux(self._target, epoch)
		return ctx

	def _prepare_stub(self, conv, double, transcript="success"):
		"""Synchronous prepare stub: queued -> preparing -> ready, writes the
		prepare->pump handoff payload (session_key + message) and arms the double.
		Stands in for WP-1d's prepare job."""

		def prep(run_id, target):
			row = ts.read_turn(run_id)
			v = int(row["version"])
			amsg = self._mk_msg(conv, role="assistant", content="", streaming=1)
			self.assertTrue(ts.claim_preparing(run_id, v, assistant_message=amsg))
			frappe.db.commit()
			v += 1
			frappe.db.set_value(
				TURN,
				run_id,
				"dispatch_payload",
				json.dumps({"session_key": f"sess-{run_id}", "message": "hi"}),
				update_modified=False,
			)
			frappe.db.commit()
			self.assertTrue(ts.mark_ready(run_id, v))
			frappe.db.commit()
			double.arm(run_id, transcript)

		return prep

	def _pump_until(self, ctx, predicate, *, max_slices=60):
		for _ in range(max_slices):
			outcome = pump.drain_slice(ctx)
			if predicate():
				return outcome
			if outcome == "idle_exit":
				return outcome
		return "timeout"


# --------------------------------------------------------------------------- #
# 1. Cold start — full lifecycle over fake frames
# --------------------------------------------------------------------------- #


class TestColdStart(_PumpTestCase):
	def test_cold_start_full_lifecycle(self):
		conv = self._mk_conv()
		seed = self._mk_msg(conv, content="hello")
		rid = "pmp_cold"
		# A cold queued turn (loser / no held credit) — the pump grants the credit.
		self._mk_turn(conv, rid, seed, "queued", version=0, reserved=0)

		double = self._double()
		settle_calls = []

		def settlement(run_id, **kw):
			settle_calls.append((run_id, dict(kw)))
			pump._default_invoke_settlement(run_id, **kw)

		deps = self._deps(
			double=double, prepare=self._prepare_stub(conv, double, "success"), settlement=settlement
		)
		ctx = self._make_ctx(deps)

		self._pump_until(ctx, lambda: bool(settle_calls))

		self.assertEqual(len(settle_calls), 1, "settlement seam invoked exactly once")
		self.assertEqual(settle_calls[0][0], rid)
		self.assertEqual(settle_calls[0][1]["epoch"], ctx.epoch)
		# The machine ran all the way: reserved -> preparing -> ready -> dispatching
		# -> streaming -> terminal_observed -> finalizing (slot released).
		self.assertEqual(self._state(rid), "finalizing")
		self.assertEqual(int(self._val(rid, "reserved")), 0, "slot released at settlement")
		self.assertIsNotNone(self._val(rid, "gateway_run_id"))
		self.assertIsNotNone(self._val(rid, "terminal_observed_at"))
		# Deltas were applied to the assistant placeholder (cumulative mirror).
		amsg = self._val(rid, "assistant_message")
		self.assertTrue((frappe.db.get_value(MSG, amsg, "content") or "").strip())
		# finalize was enqueued by settlement (D3 S6).
		self.assertGreaterEqual(deps.enqueue_finalize.count, 1)


# --------------------------------------------------------------------------- #
# 2. Idle-exit vs concurrent-send race — both D6 §2 orderings
# --------------------------------------------------------------------------- #


class TestIdleExitRace(_PumpTestCase):
	def test_commit_before_release_keeps_lease_and_continues(self):
		"""Ordering A: a queued turn committed before the conditional release makes
		it affect 0 rows -> the pump KEEPS the lease and CONTINUES (OAR-12)."""
		conv = self._mk_conv()
		seed = self._mk_msg(conv)
		ctx = self._make_ctx(self._deps(), with_mux=False)
		self._mk_turn(conv, "pmp_idleA", seed, "queued", version=0)
		self.assertFalse(pump._idle_exit(ctx), "must NOT release while a queued turn exists")
		# lease still held by this epoch.
		self.assertTrue(ts.lease_renew(self._target, ctx.epoch))

	def test_release_before_commit_then_ensure_pump_revives(self):
		"""Ordering B: no work -> the conditional release commits (lease vacant) ->
		a later sender's ensure_pump sees the vacant lease (MariaDB-authoritative)
		and enqueues a fresh hop."""
		ctx = self._make_ctx(self._deps(), with_mux=False)
		self.assertTrue(pump._idle_exit(ctx), "must release when the shard is idle")
		# Now a sender commits a new turn and calls ensure_pump.
		conv = self._mk_conv()
		seed = self._mk_msg(conv)
		self._mk_turn(conv, "pmp_idleB", seed, "queued", version=0)
		rec = _Recorder()
		deps = pump.PumpDeps()
		deps.enqueue_pump_job = rec
		# ensure_pump is gated on pump_configured (OARF-1) — it only revives when the
		# pump is enabled/draining.
		with patch.object(pump, "pump_configured", return_value=True):
			res = pump.ensure_pump(self._target, deps=deps)
		self.assertTrue(res["enqueued"])
		self.assertEqual(rec.count, 1)
		_, kwargs = rec.calls[0]
		self.assertEqual(kwargs["queue"], "long")
		self.assertEqual(kwargs["timeout"], 180)
		self.assertEqual(kwargs["relay_target_id"], self._target)
		self.assertIn("hop", kwargs["job_id"])

	def test_ensure_pump_noop_when_lease_live(self):
		# A live lease -> ensure_pump is a MariaDB-authoritative NO-OP.
		won, epoch = ts.lease_acquire(self._target, "live-holder")
		self.assertTrue(won)
		pump._clear_lease_mirror(self._target)  # force the DB path, not the fast mirror
		rec = _Recorder()
		deps = pump.PumpDeps()
		deps.enqueue_pump_job = rec
		with patch.object(pump, "pump_configured", return_value=True):
			res = pump.ensure_pump(self._target, deps=deps)
		self.assertFalse(res["enqueued"])
		self.assertEqual(res["reason"], "lease_live")
		self.assertEqual(rec.count, 0)


# --------------------------------------------------------------------------- #
# 3. Hop handoff — fresh job id, timeout=180, queue=long (assert args)
# --------------------------------------------------------------------------- #


class TestHopHandoff(_PumpTestCase):
	def test_handoff_enqueues_fresh_successor(self):
		rec = _Recorder()
		deps = pump.PumpDeps()
		deps.enqueue_pump_job = rec
		ctx = self._make_ctx(deps, hop_counter=4, with_mux=False)
		pump._handoff(ctx)
		self.assertEqual(rec.count, 1, "exactly one successor enqueued (not run)")
		_, kwargs = rec.calls[0]
		self.assertEqual(kwargs["method"], "jarvis.chat.pump.run_pump_hop")
		self.assertEqual(kwargs["queue"], "long")  # §10.4: ALWAYS long
		self.assertEqual(kwargs["timeout"], 180)  # explicit hop timeout
		self.assertEqual(kwargs["hop_counter"], 5)  # incremented
		self.assertEqual(kwargs["job_id"], f"jarvis-pump::{frappe.local.site}::{self._target}::hop5")
		# control row hop_counter bumped so the next hop mints a fresh id.
		self.assertEqual(int(frappe.db.get_value(PUMP, self._target, "hop_counter")), 5)


# --------------------------------------------------------------------------- #
# 4. Takeover fencing — the old context's write affects 0 rows
# --------------------------------------------------------------------------- #


class TestTakeoverFencing(_PumpTestCase):
	def test_old_epoch_write_affects_zero_rows(self):
		conv = self._mk_conv()
		seed = self._mk_msg(conv)
		amsg = self._mk_msg(conv, role="assistant", content="", streaming=1)
		rid = "pmp_fence"
		# A streaming turn owned by epoch 1.
		frappe.db.set_value(PUMP, self._target, "pump_epoch", 1, update_modified=False)
		frappe.db.set_value(
			PUMP,
			self._target,
			"lease_expires_at",
			frappe.utils.add_to_date(None, seconds=-5),
			update_modified=False,
		)
		frappe.db.commit()
		self._mk_turn(
			conv,
			rid,
			seed,
			"streaming",
			version=5,
			pump_epoch=1,
			reserved=1,
			assistant_message=amsg,
			dispatching_at=frappe.utils.now(),
		)
		old_ctx = pump.PumpContext(
			relay_target_id=self._target,
			epoch=1,
			holder="old",
			hop_counter=0,
			site=frappe.local.site,
			deps=self._deps(),
		)

		# A second hop takes over (mini-takeover): epoch -> 2, re-stamps the turn.
		won, new_epoch = ts.lease_acquire(self._target, "new-hop")
		self.assertTrue(won)
		self.assertEqual(new_epoch, 2)
		self.assertEqual(int(self._val(rid, "pump_epoch")), 2, "adopted turn re-stamped to E+1")

		# The OLD context's epoch-fenced write now affects 0 rows.
		self.assertFalse(
			ts.apply_delta(rid, version=6, epoch=1, event_seq=1, assistant_message=amsg, content="stale"),
			"stale-epoch delta must affect 0 rows",
		)
		self.assertTrue(pump._epoch_lost(old_ctx, rid), "the pump recognises the epoch loss")
		# The new epoch owns it and can still write.
		self.assertTrue(
			ts.apply_delta(
				rid,
				version=int(self._val(rid, "version")),
				epoch=2,
				event_seq=1,
				assistant_message=amsg,
				content="fresh",
			)
		)

	def test_dual_acquire_exactly_one_wins_threaded(self):
		"""Reuse WP-1a's threaded dual-acquire shape at the pump layer: two racers,
		exactly one becomes the leader, the epoch advances once."""
		frappe.db.set_value(
			PUMP,
			self._target,
			"lease_expires_at",
			frappe.utils.add_to_date(None, seconds=-5),
			update_modified=False,
		)
		frappe.db.set_value(PUMP, self._target, "pump_epoch", 0, update_modified=False)
		frappe.db.commit()
		site = frappe.local.site
		target = self._target
		barrier = threading.Barrier(2)
		results: dict[str, tuple] = {}
		errors: list = []

		def worker(name):
			frappe.init(site=site)
			frappe.connect()
			frappe.set_user(TEST_USER)
			try:
				barrier.wait(timeout=10)
				results[name] = ts.lease_acquire(target, f"hop-{name}")
			except Exception as e:  # pragma: no cover
				errors.append(e)
			finally:
				try:
					frappe.db.commit()
				finally:
					frappe.destroy()

		threads = [threading.Thread(target=worker, args=(n,)) for n in ("A", "B")]
		for t in threads:
			t.start()
		for t in threads:
			t.join(timeout=20)
		self.assertEqual(errors, [])
		wins = [n for n, (won, _e) in results.items() if won]
		self.assertEqual(len(wins), 1, f"exactly one leader: {results}")
		self.assertEqual(int(frappe.db.get_value(PUMP, target, "pump_epoch")), 1)


# --------------------------------------------------------------------------- #
# 5. Watchdog per-state matrix
# --------------------------------------------------------------------------- #


class TestWatchdog(_PumpTestCase):
	def test_per_state_actions(self):
		conv = self._mk_conv()
		# queued age-out (older than QUEUED_MAX_AGE_S).
		s1 = self._mk_msg(conv)
		self._mk_turn(conv, "pmp_wd_queued", s1, "queued", version=0)
		frappe.db.set_value(
			TURN,
			"pmp_wd_queued",
			"enqueued_at",
			frappe.utils.add_to_date(None, seconds=-(ts.QUEUED_MAX_AGE_S + 60)),
			update_modified=False,
		)
		# stale preparing (past PREPARE_DEADLINE_S) -> fresh prepare (queued).
		s2 = self._mk_msg(conv)
		self._mk_turn(conv, "pmp_wd_prep", s2, "preparing", version=1, reserved=1)
		frappe.db.set_value(
			TURN,
			"pmp_wd_prep",
			"preparing_at",
			frappe.utils.add_to_date(None, seconds=-(ts.PREPARE_DEADLINE_S + 60)),
			update_modified=False,
		)
		# finalizing -> re-enqueue finalize ONLY (R-13), never recovering.
		s3 = self._mk_msg(conv)
		self._mk_turn(conv, "pmp_wd_fin", s3, "finalizing", version=3)
		frappe.db.commit()

		fin_rec = _Recorder()
		pump_rec = _Recorder()
		deps = pump.PumpDeps()
		deps.enqueue_finalize = fin_rec
		deps.enqueue_pump_job = pump_rec

		# OARF-1: the watchdog is gated on pump_configured — it only runs when the
		# pump is enabled/draining. (The queued age-out row here is UNRESERVED, so
		# OARF-4's reserved-reclaim does not pre-empt the age-out.)
		with patch.object(pump, "pump_configured", return_value=True):
			summary = pump.watchdog(deps=deps)

		self.assertEqual(self._state("pmp_wd_queued"), "cancelled", "queued age-out")
		self.assertEqual(summary["aged_out"], 1)
		self.assertEqual(self._state("pmp_wd_prep"), "queued", "stale preparing -> fresh prepare")
		self.assertEqual(
			int(self._val("pmp_wd_prep", "reserved")), 0, "credit released on fresh-prepare park"
		)
		self.assertGreaterEqual(summary["reclaimed"], 1)
		# finalizing untouched (R-13) but its finalize was re-enqueued.
		self.assertEqual(self._state("pmp_wd_fin"), "finalizing")
		self.assertEqual(fin_rec.count, 1)
		self.assertEqual(summary["finalize_requeued"], 1)
		# live work remained (the re-queued turn) -> ensure_pump revived the shard.
		self.assertGreaterEqual(pump_rec.count, 1)


# --------------------------------------------------------------------------- #
# 6. Ack-timeout park vs definite-rejection errored (PANEL 7) + WS drop (PANEL 9)
# --------------------------------------------------------------------------- #


class _RejectGateway:
	"""Minimal transport double whose chat.send is DEFINITIVELY rejected (ok:false
	with a concrete code) — the OAR-8 dispatching->errored path."""

	def __init__(self, code="policy_denied"):
		self._lock = threading.Lock()
		self._code = code
		import queue as _q

		self._q = _q.Queue()
		self._ws = _RejectWs(self._on_send)
		self._closed = threading.Event()

	def _recv(self, timeout_s):
		if timeout_s <= 0:
			return None
		try:
			return self._q.get(timeout=timeout_s)
		except Exception:
			return None

	def close(self):
		self._closed.set()

	def stop(self):
		self._closed.set()

	def _on_send(self, payload):
		frame = json.loads(payload)
		self._q.put(
			{
				"type": "res",
				"id": frame.get("id"),
				"ok": False,
				"error": {"code": self._code, "message": "nope"},
			}
		)


class _RejectWs:
	def __init__(self, on_send):
		self._on_send = on_send
		self.connected = True

	def send(self, payload):
		self._on_send(payload)


class TestDispatchOutcomes(_PumpTestCase):
	def _seed_ready(self, conv, rid):
		seed = self._mk_msg(conv)
		amsg = self._mk_msg(conv, role="assistant", content="", streaming=1)
		self._mk_turn(
			conv,
			rid,
			seed,
			"ready",
			version=2,
			reserved=1,
			assistant_message=amsg,
			ready_at=frappe.utils.now(),
			dispatch_payload=json.dumps({"session_key": f"sess-{rid}", "message": "hi"}),
		)
		return amsg

	def test_ack_timeout_parks_recovering(self):
		conv = self._mk_conv()
		rid = "pmp_ackto"
		self._seed_ready(conv, rid)
		double = self._double()
		double.arm(rid, "ack-timeout")  # gateway holds the ack past the window
		deps = self._deps(double=double)
		ctx = self._make_ctx(deps)
		# OARF-5: dispatch ISSUES the ack (non-blocking) + parks it; the ack-timeout
		# fires on a LATER poll when our slice-level deadline passes (not a blocking
		# .result()). Drive slices until the park lands.
		with patch.object(pump, "ACK_TIMEOUT_S", 0.3):
			t0 = time.monotonic()
			pump._dispatch_ready(ctx)
			self.assertLess(time.monotonic() - t0, 1.0, "dispatch did NOT block on the ack (OARF-5)")
			self._pump_until(ctx, lambda: self._state(rid) == "recovering")
		# Ambiguous outcome -> parked recovering (NOT errored).
		self.assertEqual(self._state(rid), "recovering")
		self.assertEqual(int(self._val(rid, "recovering")), 1)
		# SUXF-1: the park mirrored the Message row so a reload reconstructs the banner.
		amsg = self._val(rid, "assistant_message")
		self.assertEqual(int(frappe.db.get_value(MSG, amsg, "recovering") or 0), 1)

	def test_ws_drop_outstanding_ack_immediate_sentinel_parks(self):
		"""PANEL 9: a WS drop while a chat.send ack is outstanding fails the future
		immediately (OAR-10 sentinel) -> the pump parks recovering, no dead-wait."""
		conv = self._mk_conv()
		rid = "pmp_wsdrop"
		self._seed_ready(conv, rid)
		double = self._double()
		double.arm(rid, "success", ack_behavior="drop")
		deps = self._deps(double=double)
		ctx = self._make_ctx(deps)
		t0 = time.monotonic()
		pump._dispatch_ready(ctx)  # OARF-5: non-blocking issue
		# The Closing sentinel fails the pending future immediately; a poll resolves it.
		self._pump_until(ctx, lambda: self._state(rid) == "recovering")
		self.assertLess(time.monotonic() - t0, 5.0, "did not dead-wait the ack")
		self.assertEqual(self._state(rid), "recovering")

	def test_definite_rejection_errors_and_releases_credit(self):
		"""PANEL 7: a DEFINITE ok:false rejection -> dispatching->errored + credit
		release (OAR-8), distinct from the ack-timeout park."""
		conv = self._mk_conv()
		rid = "pmp_reject"
		self._seed_ready(conv, rid)
		double = _RejectGateway()
		self._doubles.append(double)
		deps = self._deps(double=double)
		ctx = self._make_ctx(deps)
		pump._dispatch_ready(ctx)  # OARF-5: non-blocking issue
		self._pump_until(ctx, lambda: self._state(rid) in ("errored", "recovering"))
		self.assertEqual(self._state(rid), "errored")
		self.assertEqual(int(self._val(rid, "reserved")), 0, "credit released on definite rejection")
		self.assertTrue(self._val(rid, "error") or "")


# --------------------------------------------------------------------------- #
# 7. Cancel flow end-to-end
# --------------------------------------------------------------------------- #


class TestCancelFlow(_PumpTestCase):
	def test_cancel_requested_aborts_and_settles_cancelled(self):
		conv = self._mk_conv()
		rid = "pmp_cancel"
		seed = self._mk_msg(conv)
		amsg = self._mk_msg(conv, role="assistant", content="partial", streaming=1)
		double = self._double()
		deps = self._deps(double=double)
		ctx = self._make_ctx(deps)
		# A streaming turn owned by THIS pump's epoch (so the abort CAS is fenced).
		self._mk_turn(
			conv,
			rid,
			seed,
			"streaming",
			version=4,
			pump_epoch=ctx.epoch,
			reserved=1,
			assistant_message=amsg,
			gateway_run_id=rid,
			dispatching_at=frappe.utils.now(),
			dispatch_payload=json.dumps({"session_key": f"sess-{rid}", "message": "hi"}),
		)
		# The web sender requests cancellation (D2 row 17).
		self.assertTrue(ts.request_cancel(rid, 4))
		frappe.db.commit()

		swept = pump._cancel_sweep(ctx)
		self.assertEqual(swept, 1)
		self.assertEqual(self._state(rid), "cancelled")
		self.assertEqual(int(self._val(rid, "reserved")), 0, "slot released on cancel")


# --------------------------------------------------------------------------- #
# 8. DB-disconnect -> bounded backoff -> park recovering -> exit hop
# --------------------------------------------------------------------------- #


class TestDBDisconnect(_PumpTestCase):
	def test_db_disconnect_parks_and_exits(self):
		conv = self._mk_conv()
		rid = "pmp_dbdrop"
		seed = self._mk_msg(conv)
		amsg = self._mk_msg(conv, role="assistant", content="", streaming=1)
		self._mk_turn(
			conv,
			rid,
			seed,
			"ready",
			version=2,
			reserved=1,
			assistant_message=amsg,
			ready_at=frappe.utils.now(),
			dispatch_payload=json.dumps({"session_key": f"sess-{rid}", "message": "hi"}),
		)
		double = self._double()
		deps = self._deps(double=double)

		op_error = frappe.db.OperationalError("(2013, 'Lost connection to MySQL server')")
		# The dispatch CAS raises a DB operational error persistently; the pump
		# must bound the backoff, park the affected turn, and exit (never spin).
		with (
			patch.object(ts, "confirm_dispatching", side_effect=op_error),
			patch.object(pump, "_backoff_reconnect", lambda *_a, **_k: None),
		):
			res = pump.run_pump_hop(self._target, deps=deps, soft_budget_s=999)

		self.assertEqual(res["exit"], "db_disconnect")
		self.assertEqual(self._state(rid), "recovering", "affected turn parked recovering")


# --------------------------------------------------------------------------- #
# 9. Credit lifecycle (PANEL 2/3) + cross-conversation over-admit (PANEL 1)
# --------------------------------------------------------------------------- #


class TestCreditLifecycle(_PumpTestCase):
	def test_promote_dispatch_settle_credit(self):
		conv = self._mk_conv()
		rid = "pmp_credit"
		seed = self._mk_msg(conv)
		amsg = self._mk_msg(conv, role="assistant", content="", streaming=1)
		self._mk_turn(conv, rid, seed, "queued", version=0, reserved=0)
		prep_rec = _Recorder()
		deps = self._deps(prepare=prep_rec)
		ctx = self._make_ctx(deps, with_mux=False)

		self.assertEqual(pump._pump_local_reservations(self._target), 0)
		# PROMOTE: reserve credit under the shard lock -> local_res = 1.
		self.assertEqual(pump._promote_queued(ctx), 1)
		self.assertEqual(int(self._val(rid, "reserved")), 1)
		self.assertEqual(pump._pump_local_reservations(self._target), 1)
		self.assertEqual(prep_rec.count, 1, "prepare dispatched after the shard-lock commit")

		# DISPATCH (drive the prepare + dispatch transitions with turn_state) —
		# a dispatching/streaming turn keeps consuming the credit.
		v = int(self._val(rid, "version"))
		self.assertTrue(ts.claim_preparing(rid, v, assistant_message=amsg))
		self.assertTrue(ts.mark_ready(rid, v + 1))
		frappe.db.commit()
		self.assertTrue(ts.confirm_dispatching(rid, v + 2, ctx.epoch))
		self.assertTrue(ts.mark_streaming(rid, v + 3, ctx.epoch, gateway_run_id=rid))
		frappe.db.commit()
		self.assertEqual(pump._pump_local_reservations(self._target), 1, "in-flight still holds the credit")

		# TERMINAL + SETTLE (default seam) -> slot released -> local_res = 0.
		self.assertTrue(ts.mark_terminal_observed(rid, v + 4, ctx.epoch, "relay:final", {"text": "done"}))
		frappe.db.commit()
		ctx.deps.invoke_settlement(
			rid,
			relay_target_id=self._target,
			epoch=ctx.epoch,
			version=v + 5,
			terminal_kind="relay:final",
			terminal_payload={"text": "done"},
			assistant_message=amsg,
			owner=frappe.session.user,
			conversation=conv,
			deps=ctx.deps,
		)
		self.assertEqual(self._state(rid), "finalizing")
		self.assertEqual(pump._pump_local_reservations(self._target), 0, "credit released at settlement")

	def test_cross_conversation_over_admit_at_promote(self):
		"""PANEL 1: two queued turns on DIFFERENT conversations of the SAME shard
		with cap=1 -> the shard-locked promote reserves EXACTLY ONE (the credit
		count+reserve serialize on the shard, OAR-1)."""
		conv_a = self._mk_conv()
		conv_b = self._mk_conv()
		sa = self._mk_msg(conv_a)
		sb = self._mk_msg(conv_b)
		self._mk_turn(conv_a, "pmp_oa", sa, "queued", version=0, reserved=0)
		self._mk_turn(conv_b, "pmp_ob", sb, "queued", version=0, reserved=0)
		prep_rec = _Recorder()
		deps = self._deps(prepare=prep_rec)
		ctx = self._make_ctx(deps, with_mux=False)

		with patch("jarvis.chat.admission._max_inflight", return_value=1):
			promoted = pump._promote_queued(ctx)

		self.assertEqual(promoted, 1, "exactly one credit granted under cap=1")
		reserved = frappe.db.sql(
			f"SELECT COUNT(*) FROM `tab{TURN}` WHERE relay_target_id=%(t)s AND reserved=1",
			{"t": self._target},
		)[0][0]
		self.assertEqual(reserved, 1, "no cross-conversation over-admit")
		self.assertEqual(prep_rec.count, 1)

	def test_reserve_on_send_winner_dispatches_prepare_without_re_reserve(self):
		"""A queued turn that ALREADY holds a credit (reserve-on-send winner) is
		promoted for prepare without consuming a NEW credit."""
		conv = self._mk_conv()
		rid = "pmp_held"
		seed = self._mk_msg(conv)
		self._mk_turn(conv, rid, seed, "queued", version=1, reserved=1)
		prep_rec = _Recorder()
		deps = self._deps(prepare=prep_rec)
		ctx = self._make_ctx(deps, with_mux=False)
		before = pump._pump_local_reservations(self._target)
		self.assertEqual(pump._promote_queued(ctx), 1)
		self.assertEqual(prep_rec.count, 1)
		self.assertEqual(int(self._val(rid, "reserved")), 1)
		self.assertEqual(pump._pump_local_reservations(self._target), before, "no new credit consumed")


# --------------------------------------------------------------------------- #
# 10. Wake bus round-trip (raw redis, explicit site key)
# --------------------------------------------------------------------------- #


class TestWakeBus(_PumpTestCase):
	def test_lpush_then_drain_roundtrip(self):
		pump.lpush_wake(self._target, "run-1")
		pump.lpush_wake(self._target, "run-2")
		drained = pump.drain_wake(self._target)
		self.assertEqual(set(drained), {"run-1", "run-2"})
		# Draining again yields nothing (the bus was emptied).
		self.assertEqual(pump.drain_wake(self._target), [])


# --------------------------------------------------------------------------- #
# 11. OARF-4 — reserved-but-unclaimed reclaim (retry, never age-out cancel)
# --------------------------------------------------------------------------- #


class TestWatchdogReservationReclaim(_PumpTestCase):
	def test_reserved_unclaimed_reclaimed_for_retry_not_cancelled(self):
		"""OARF-4: a turn that RESERVED a credit at promote but whose prepare never
		CLAIMED it (still `queued` reserved=1, reservation > 120s old) is reclaimed
		back to `queued reserved=0` FOR RETRY — even when it is ALSO past the 900s
		age-out (reclaim WINS over cancel for a reserved turn)."""
		conv = self._mk_conv()
		rid = "pmp_oarf4"
		seed = self._mk_msg(conv)
		self._mk_turn(conv, rid, seed, "queued", version=1, reserved=1)
		frappe.db.set_value(
			TURN,
			rid,
			{
				# reservation made > PREPARE_DISPATCH_DEADLINE_S ago (stale, unclaimed):
				"reservation_expires_at": frappe.utils.add_to_date(
					None, seconds=(ts.RESERVE_TTL_S - pump.PREPARE_DISPATCH_DEADLINE_S - 30)
				),
				# ALSO past the 900s age-out — prove reclaim pre-empts cancel.
				"enqueued_at": frappe.utils.add_to_date(None, seconds=-(ts.QUEUED_MAX_AGE_S + 120)),
			},
			update_modified=False,
		)
		frappe.db.commit()
		wd_deps = pump.PumpDeps()
		wd_deps.enqueue_pump_job = _Recorder()
		with patch.object(pump, "pump_configured", return_value=True):
			summary = pump.watchdog(deps=wd_deps)
		self.assertEqual(self._state(rid), "queued", "reserved-unclaimed turn RETRIED, not cancelled")
		self.assertEqual(int(self._val(rid, "reserved")), 0, "credit released for retry")
		self.assertGreaterEqual(summary["reclaimed"], 1)
		self.assertEqual(summary["aged_out"], 0, "reclaim wins over age-out for a reserved turn")

	def test_unreserved_queued_still_ages_out(self):
		"""The 15-min age-out still cancels a genuinely-waiting UNRESERVED queued turn
		(never given a credit) — OARF-4 only spares RESERVED turns."""
		conv = self._mk_conv()
		rid = "pmp_oarf4b"
		seed = self._mk_msg(conv)
		self._mk_turn(conv, rid, seed, "queued", version=0, reserved=0)
		frappe.db.set_value(
			TURN,
			rid,
			"enqueued_at",
			frappe.utils.add_to_date(None, seconds=-(ts.QUEUED_MAX_AGE_S + 120)),
			update_modified=False,
		)
		frappe.db.commit()
		wd_deps = pump.PumpDeps()
		wd_deps.enqueue_pump_job = _Recorder()
		with patch.object(pump, "pump_configured", return_value=True):
			summary = pump.watchdog(deps=wd_deps)
		self.assertEqual(self._state(rid), "cancelled", "unreserved queued turn still ages out")
		self.assertGreaterEqual(summary["aged_out"], 1)


# --------------------------------------------------------------------------- #
# 12. OARF-8 — prepare/finalize enqueues use attempt-suffixed job ids
# --------------------------------------------------------------------------- #


class TestAttemptSuffixJobIds(_PumpTestCase):
	def test_prepare_finalize_ids_carry_attempt_suffix(self):
		conv = self._mk_conv()
		rid = "pmp_jobid"
		seed = self._mk_msg(conv)
		self._mk_turn(conv, rid, seed, "queued", version=3, reserved=1)
		captured: list = []

		def fake_enqueue(method, **kw):
			captured.append(kw.get("job_id"))

		with patch("frappe.enqueue", fake_enqueue):
			pump._default_dispatch_prepare(rid, self._target)
			pump._default_enqueue_finalize(rid, self._target)
		self.assertEqual(captured[0], f"jarvis-prepare::{rid}::a3", "prepare id carries ::a<version>")
		self.assertEqual(captured[1], f"jarvis-finalize::{rid}::a3", "finalize id carries ::a<version>")

		# A genuine new attempt (version bumped) mints a DIFFERENT id, so a dead
		# STARTED registration of the old id can never no-op the re-enqueue.
		frappe.db.set_value(TURN, rid, "version", 7, update_modified=False)
		frappe.db.commit()
		captured.clear()
		with patch("frappe.enqueue", fake_enqueue):
			pump._default_dispatch_prepare(rid, self._target)
		self.assertEqual(captured[0], f"jarvis-prepare::{rid}::a7", "new attempt -> fresh id")


# --------------------------------------------------------------------------- #
# 12b. F1 — control-job (prepare/finalize) queue routing per bench shape
# --------------------------------------------------------------------------- #


class TestControlQueueRouting(_PumpTestCase):
	"""F1 (long-queue self-starvation): the pump's CONTROL jobs (prepare + finalize)
	must never share the single-worker ``long`` queue the 90s hops ride. Routing per
	bench shape: a live ``jarvis_chat`` lane -> ride it; else ``long`` with >=2
	workers; else ``short``. Hops stay on ``long`` unconditionally (asserted in the
	handoff test)."""

	def test_jarvis_chat_lane_live_rides_it(self):
		with patch("jarvis.chat.api._turn_queue", lambda: "jarvis_chat"):
			self.assertEqual(pump._control_queue(), "jarvis_chat")
			self.assertFalse(pump._pump_shape_starves())

	def test_long_with_two_workers_uses_long(self):
		with (
			patch("jarvis.chat.api._turn_queue", lambda: "long"),
			patch.object(pump, "_live_worker_count", lambda q: 2),
		):
			self.assertEqual(pump._control_queue(), "long")
			self.assertFalse(pump._pump_shape_starves())

	def test_single_long_no_jarvis_chat_uses_short(self):
		with (
			patch("jarvis.chat.api._turn_queue", lambda: "long"),
			patch.object(pump, "_live_worker_count", lambda q: 1),
		):
			self.assertEqual(pump._control_queue(), "short")
			self.assertTrue(pump._pump_shape_starves())

	def test_prepare_finalize_route_to_short_on_starve_shape(self):
		"""The F1 scenario as a queue-name assertion on the enqueue calls: on the
		single-``long``-no-``jarvis_chat`` shape, BOTH prepare and finalize route to
		``short`` — never the ``long`` queue the hops occupy (which self-starves)."""
		conv = self._mk_conv()
		rid = "pmp_route_short"
		seed = self._mk_msg(conv)
		self._mk_turn(conv, rid, seed, "queued", version=2, reserved=1)
		captured: list = []

		def fake_enqueue(method, **kw):
			captured.append((method, kw.get("queue"), kw.get("timeout")))

		with (
			patch("jarvis.chat.api._turn_queue", lambda: "long"),
			patch.object(pump, "_live_worker_count", lambda q: 1),
			patch("frappe.enqueue", fake_enqueue),
		):
			pump._default_dispatch_prepare(rid, self._target)
			pump._default_enqueue_finalize(rid, self._target)
		self.assertEqual(captured[0], ("jarvis.chat.prepare.run_prepare", "short", pump.HOP_TIMEOUT_S))
		self.assertEqual(captured[1], ("jarvis.chat.finalize.run_finalize", "short", pump.HOP_TIMEOUT_S))

	def test_prepare_finalize_ride_jarvis_chat_when_live(self):
		"""When a ``jarvis_chat`` lane is live, prepare/finalize ride it (isolated
		parallel workers), NOT ``long`` or ``short``."""
		conv = self._mk_conv()
		rid = "pmp_route_jc"
		seed = self._mk_msg(conv)
		self._mk_turn(conv, rid, seed, "queued", version=2, reserved=1)
		captured: list = []

		def fake_enqueue(method, **kw):
			captured.append((method, kw.get("queue")))

		with (
			patch("jarvis.chat.api._turn_queue", lambda: "jarvis_chat"),
			patch("frappe.enqueue", fake_enqueue),
		):
			pump._default_dispatch_prepare(rid, self._target)
			pump._default_enqueue_finalize(rid, self._target)
		self.assertEqual(captured[0], ("jarvis.chat.prepare.run_prepare", "jarvis_chat"))
		self.assertEqual(captured[1], ("jarvis.chat.finalize.run_finalize", "jarvis_chat"))

	def test_provision_warning_emitted_once_then_throttled(self):
		"""§8-I: the starve shape emits ONE loud provisioning warning, then throttles
		(so the after-every-commit ensure_pump path never spams)."""
		key = f"jarvis:pump:provision_warn:{frappe.local.site}"
		frappe.cache().delete_value(key)
		events: list = []
		try:
			with (
				patch("jarvis.chat.api._turn_queue", lambda: "long"),
				patch.object(pump, "_live_worker_count", lambda q: 1),
				patch.object(pump, "_telemetry", lambda ev, **kw: events.append(ev)),
				patch("frappe.log_error", lambda *a, **k: None),
			):
				pump._warn_provisioning_if_starved()
				pump._warn_provisioning_if_starved()  # throttled — a no-op
			self.assertEqual(events.count("provision_warning"), 1, "warned once, then throttled")
		finally:
			frappe.cache().delete_value(key)

	def test_no_provision_warning_when_shape_healthy(self):
		events: list = []
		with (
			patch("jarvis.chat.api._turn_queue", lambda: "jarvis_chat"),
			patch.object(pump, "_telemetry", lambda ev, **kw: events.append(ev)),
		):
			pump._warn_provisioning_if_starved()
		self.assertNotIn("provision_warning", events)


# --------------------------------------------------------------------------- #
# 13. OARF-9 — the canonical lock-order assertion fires under the test config
# --------------------------------------------------------------------------- #


class TestLockOrderAssertion(_PumpTestCase):
	def test_lock_order_violation_raises_under_test_config(self):
		# setUp activates jarvis_pump_lock_assert, so _dev_mode() is True and an
		# inversion RAISES instead of silently log_error-ing (OARF-9).
		self.assertTrue(ts._dev_mode(), "lock-assert config active for the suite")
		ts.reset_lock_tracking()
		try:
			ts.assert_lock_order("turn")  # rank 3
			with self.assertRaises(ts.LockOrderError):
				ts.assert_lock_order("shard")  # rank 1 while holding rank 3 -> inversion
		finally:
			ts.reset_lock_tracking()

	def test_canonical_order_does_not_raise(self):
		ts.reset_lock_tracking()
		try:
			ts.assert_lock_order("shard")
			ts.assert_lock_order("conversation")
			ts.assert_lock_order("turn")
			ts.assert_lock_order("message")  # canonical order -> no raise
		finally:
			ts.reset_lock_tracking()


# --------------------------------------------------------------------------- #
# 14. OARF-5 — the reactor does not block on RPC futures inside a slice
# --------------------------------------------------------------------------- #


class TestNonBlockingReactor(_PumpTestCase):
	def test_dispatch_wave_does_not_block_on_slow_acks(self):
		"""OARF-5: dispatching N ready turns whose gateway HOLDS the ack must NOT
		block the reactor per-ack (the old fut.result(15s) wave). _dispatch_ready
		issues every send and returns fast; the acks are parked for polling."""
		double = self._double()
		rids = []
		for i in range(3):
			conv = self._mk_conv()
			rid = f"pmp_wave_{i}"
			rids.append(rid)
			seed = self._mk_msg(conv)
			amsg = self._mk_msg(conv, role="assistant", content="", streaming=1)
			self._mk_turn(
				conv,
				rid,
				seed,
				"ready",
				version=2,
				reserved=1,
				assistant_message=amsg,
				ready_at=frappe.utils.now(),
				dispatch_payload=json.dumps({"session_key": f"s-{rid}", "message": "hi"}),
			)
			double.arm(rid, "ack-timeout")  # the gateway holds every ack
		deps = self._deps(double=double)
		ctx = self._make_ctx(deps)
		t0 = time.monotonic()
		with patch.object(pump, "ACK_TIMEOUT_S", 5.0):
			n = pump._dispatch_ready(ctx)
		elapsed = time.monotonic() - t0
		self.assertEqual(n, 3, "all three sends issued")
		self.assertLess(elapsed, 2.0, "OARF-5: the wave did NOT block ~N*ACK_TIMEOUT on acks")
		self.assertEqual(len(ctx.pending_acks), 3, "acks parked for polling, not awaited inline")
		for rid in rids:
			self.assertEqual(self._state(rid), "dispatching")
