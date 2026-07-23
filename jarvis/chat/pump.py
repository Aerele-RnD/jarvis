"""WP-1c — the Relay Pump reactor (the heart of the managed-relay transport).

One leased supervisor per ``(site, relay_target_id)`` drains every turn on a
container over ONE multiplexed WebSocket (WP-1b's :class:`RelayMux`), driving the
durable turn-state machine (WP-1a's ``turn_state`` CAS library) forward. This
module is the D6 lifecycle: bounded 60-120s hops on ``long``, hop = mini-takeover
(epoch bump + adopted-turn re-stamp EVERY hop), snapshot reconcile on every
start/reconnect, full-credit admission at promote under the shard lock,
idle-exit conditional release, DB-disconnect bounded-backoff parking, and the one
shared lease-loss exit.

Binding contract (read in order):
  * implementation/wp-d/D6-lifecycle-diagrams.md (AMENDED) — cold start, the
    idle-exit/send race (act-on-affected-rows, OAR-12), hop handoff with a FRESH
    job id, SIGTERM warm shutdown, the 240s scheduler backstop, DB-disconnect park.
  * implementation/wp-d/D3-cas-pseudocode.md (AMENDED) — shard-lock admission at
    promote (Race 2), the settlement transaction (Race 3), reservation lifecycle.
  * implementation/wp-d/D2-schema-transitions.md (AMENDED) — the transition table
    ``turn_state`` implements; the watchdog's PER-STATE actions (finalizing ⇒
    re-enqueue finalize only, R-13; PREPARE_DEADLINE_S=300; queued age-out).
  * Binding spec §10.4 (pump control jobs ride ``long`` UNCONDITIONALLY), §10.5
    (hop = mini-takeover), §10.6 (state-machine corrections), §8-E (sender-driven
    ``ensure_pump`` PRIMARY; fresh job id per hop — the frappe dedupe trap; the
    240s scheduler backstop).
  * spikes/S4-turn-queue-cache.md (why pump jobs → ``long``) + S2 (ack semantics).

HARD INVARIANTS:
  * EVERY turn mutation goes through ``turn_state`` (no raw CAS SQL here); every
    realtime publish goes through ``turn_state.publish_fenced`` AFTER a winning
    commit. A pump-owned CAS that affects 0 rows AND whose epoch no longer matches
    routes through the ONE shared ``lease_lost_exit`` (stop reading, no publishes,
    hop returns).
  * Pump control jobs (hops, watchdog-triggered starts) ALWAYS enqueue to
    ``long`` with an EXPLICIT ``timeout=180`` and a FRESH job id per hop (§10.4,
    S4 — a dead ``jarvis_chat`` queue can look provisioned for ~420-480s, longer
    than a hop; ``long`` always has a live consumer).
  * The commit-first REPEATABLE-READ shard-lock discipline at every control-row
    lock site: ``turn_state._lock_shard`` commits to start a fresh transaction so
    the ``SELECT ... FOR UPDATE`` is the first statement and the credit COUNT that
    follows takes its snapshot AFTER the prior holder committed. Canonical lock
    order (OAR-6): control(shard) -> conversation -> turn -> message.

DEADLOCK-REPLAY SAFETY (Frappe replays a deadlocked job up to 5x): the hop body
is replay-safe BY CONSTRUCTION. Every effect is either a ``turn_state`` CAS keyed
by ``state+version(+pump_epoch)`` or an idempotent effect keyed by
``(turn, effect)`` / the ``run_id`` PK, so a replayed slice re-applies nothing
already committed — a replayed delta CAS sees the advanced watermark and affects 0
rows; a replayed settlement sees ``finalizing`` and affects 0 rows; a replayed
promote sees ``reserved=1`` and affects 0 rows; a replayed seed collides on the
``run_id`` PK. The mux/WS is rebuilt fresh each hop, so a replay never doubles a
socket. Nothing outside a ``turn_state`` CAS or an idempotency-keyed effect is
mutated on the hot path.

SIGTERM / warm shutdown (D6 §4): a hop finishes its current slice, commits, and
releases the lease cleanly, all inside the supervisor ``stopwaitsecs`` budget
because a hop is at most 120s. The queue-timeout ladder is comfortable
everywhere: 180 (SIGALRM ``timeout=``) < 240 (v16 monitor kill) < 1560 (``long``
``stopwaitsecs``).

WP-1c is DRIVEN BY TESTS ONLY. Production callers (api.py / turn_handler.py /
actions_api.py) are wired in WP-1d/e. The two WP-1d seams (prepare dispatcher +
settlement/finalize invoker) are injectable via :class:`PumpDeps` and default to
minimal-but-correct in-module implementations so the pump is exercisable and
correct standalone; WP-1d replaces them with the full prepare/finalize jobs.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import frappe

from jarvis.chat import turn_state as ts
from jarvis.chat.relay_mux import LaneHandler, RelayMux
from jarvis.exceptions import OpenclawUnreachableError

TURN = "Jarvis Chat Turn"
PUMP = "Jarvis Relay Pump"
MSG = "Jarvis Chat Message"
CONV = "Jarvis Conversation"

# --------------------------------------------------------------------------- #
# Constants (from the amended D6 / RULINGS-PA §10.4)
# --------------------------------------------------------------------------- #

# Pump control jobs ALWAYS ride `long` (S4 / R-19 / §10.4): guaranteed consumer.
PUMP_QUEUE = "long"

# Hop budget ladder (R-18 / §10.4). Soft budget = when to hand off; hard deadline
# = the last moment a slice may start; explicit RQ timeout = the SIGALRM ceiling.
SOFT_HOP_BUDGET_S = 90
HARD_HOP_DEADLINE_S = 120
HOP_TIMEOUT_S = 180

# Loop heartbeat + lease renew cadence (distinct signals, Amendment E). Both are
# written at most this often (a slice is ~sub-second, so we gate them).
HEARTBEAT_INTERVAL_S = 10

# How long a slice blocks on the mux for buffered frames before re-checking the
# lease / budget. Small so budgets + SIGTERM are honored promptly.
SLICE_BLOCK_S = 0.2

# chat.send ack window. Longer than the mux default so a busy accept path still
# acks; on expiry the mux raises the `ack-timeout` sentinel → park recovering.
ACK_TIMEOUT_S = 15.0

# DB-disconnect bounded backoff (D6 §6): after this many CONSECUTIVE slice-level
# operational errors the pump PARKS the affected turns and exits (never spins).
DB_BACKOFF_ATTEMPTS = 5
DB_BACKOFF_BASE_S = 0.2
DB_BACKOFF_CAP_S = 2.0

# Recovery budget: a turn stuck in `recovering` past this (from
# recovery_started_at) is driven to `errored` by the watchdog (D2 row 24).
RECOVERY_BUDGET_S = 600

# Admission safety reserve (§10.1 — heartbeats self-defer, so default 0).
SAFETY_RESERVE = 0

# Redis lease-mirror TTL (fast NO-OP path only; MariaDB is authoritative, R-17).
LEASE_MIRROR_TTL_S = 30

# Injection seams for timing (tests monkeypatch to remove real waits).
_monotonic: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep


# --------------------------------------------------------------------------- #
# Pump-mode routing flags (§10.9 — managed relay ONLY; self-host keeps legacy)
# --------------------------------------------------------------------------- #
#
# Per-site flag `jarvis_pump_enabled` (frappe.conf): unset/falsy = off; a truthy
# value = ON (the pump owns new-turn dispatch); the sentinel 'draining' = no NEW
# pump admissions (new turns fall through to legacy) while the pump keeps draining
# its existing Turn rows to terminal. Independent of `jarvis_phase0_admission_enabled`
# (pump ON implies admission semantics INSIDE the machine).


def pump_mode_active() -> bool:
	"""True when the Relay Pump owns NEW turn dispatch on this bench: the per-site
	``jarvis_pump_enabled`` flag is truthy AND not ``'draining'``, AND the transport
	is managed relay (§10.9 — self-host turns keep the legacy worker-per-turn path
	even when the flag is set). Cheap conf read + one selfhost check."""
	flag = frappe.conf.get("jarvis_pump_enabled")
	if not flag or str(flag).strip().lower() == "draining":
		return False
	from jarvis import selfhost

	return not selfhost.is_self_hosted()


def pump_draining() -> bool:
	"""True when ``jarvis_pump_enabled == 'draining'`` on a managed bench: NO new
	pump admissions (new turns fall through to the legacy path), while the pump keeps
	draining its existing Turn-row turns to terminal (OAR-11 coexistence)."""
	flag = frappe.conf.get("jarvis_pump_enabled")
	if not flag or str(flag).strip().lower() != "draining":
		return False
	from jarvis import selfhost

	return not selfhost.is_self_hosted()


def pump_configured() -> bool:
	"""True when the pump is turned on in ANY form (active OR draining) on a managed
	bench. Once configured, the pump OWNS every ``Jarvis Chat Turn`` row, so Phase-0
	admission's promote/sweep step back (they must never legacy-dispatch or reconcile
	a pump-owned Turn row) — the coexistence discriminator that keeps the two
	machines from fighting over the same rows."""
	if not frappe.conf.get("jarvis_pump_enabled"):
		return False
	from jarvis import selfhost

	return not selfhost.is_self_hosted()


# Operational-error tuple for the DB-disconnect park path (frappe.db exposes the
# driver's exception classes; resolved lazily so import never needs a live DB).
def _operational_errors() -> tuple[type[BaseException], ...]:
	errs: list[type[BaseException]] = []
	for name in ("OperationalError", "InterfaceError"):
		exc = getattr(frappe.db, name, None) if getattr(frappe, "db", None) else None
		if isinstance(exc, type) and issubclass(exc, BaseException):
			errs.append(exc)
	return tuple(errs) or (Exception,)


# --------------------------------------------------------------------------- #
# Wake bus — RAW redis client with an EXPLICIT site key (RedisWrapper BRPOP trap)
# --------------------------------------------------------------------------- #
#
# frappe's RedisWrapper prefixes `lpush`/`rpop` via `make_key` but NOT the raw
# `brpop` command (HANDOFF §6 gotcha). To make LPUSH and the pop AGREE no matter
# which wrapper method is used, we go through `execute_command` (the un-wrapped
# redis.Redis path) with a fully-explicit, site-scoped key we build ourselves. A
# LOST wake entry costs at most one tick, never a turn — the pump scans `queued`
# rows on wake and on every watchdog tick regardless (§3 v1 amendment).


def _wake_key(target: str) -> str:
	db = (frappe.local.conf.get("db_name") if getattr(frappe, "local", None) else None) or frappe.local.site
	return f"{db}|jarvis:pump:commands:{target}"


def lpush_wake(target: str, run_id: str) -> None:
	"""Best-effort wake signal (called by accept_send AFTER its durable commit,
	§10.6). Raw client + explicit key so it pairs with :func:`drain_wake`."""
	try:
		frappe.cache().execute_command("LPUSH", _wake_key(target), run_id)
	except Exception:
		pass


def drain_wake(target: str, max_items: int = 512) -> list[str]:
	"""Drain the wake bus (RPOP loop, non-blocking) via the RAW client + explicit
	key. Returns the run_ids signalled (advisory only — the pump scans `queued`
	rows anyway, so a lost/duplicate wake is harmless)."""
	out: list[str] = []
	try:
		conn = frappe.cache()
		key = _wake_key(target)
		for _ in range(max_items):
			val = conn.execute_command("RPOP", key)
			if val is None:
				break
			out.append(val.decode() if isinstance(val, bytes) else str(val))
	except Exception:
		pass
	return out


# --------------------------------------------------------------------------- #
# Redis lease mirror (fast NO-OP path ONLY — never proof of vacancy, R-17/D4-b)
# --------------------------------------------------------------------------- #


def _lease_mirror_key(target: str) -> str:
	return f"jarvis:pump:lease:{target}"


def _write_lease_mirror(target: str) -> None:
	try:
		frappe.cache().set_value(_lease_mirror_key(target), "1", expires_in_sec=LEASE_MIRROR_TTL_S)
	except Exception:
		pass


def _clear_lease_mirror(target: str) -> None:
	try:
		frappe.cache().delete_value(_lease_mirror_key(target))
	except Exception:
		pass


def _lease_mirror_live(target: str) -> bool:
	"""Fast NO-OP gate ONLY: a PRESENT+fresh mirror lets ``ensure_pump`` skip the
	DB read (the mirror TTL ~= the lease TTL, so this never no-ops past the point
	MariaDB would). A MISSING mirror is NEVER treated as proof of vacancy — the
	caller falls through to the authoritative MariaDB read (D4-b)."""
	try:
		return bool(frappe.cache().get_value(_lease_mirror_key(target), use_local_cache=False))
	except Exception:
		return False


# --------------------------------------------------------------------------- #
# WP-1d seams + internal test seams (PumpDeps)
# --------------------------------------------------------------------------- #


def _default_dispatch_prepare(run_id: str, relay_target_id: str) -> None:
	"""WP-1d SEAM 1 — prepare dispatcher. Enqueue the short prepare job (D1 stages
	#16-#26 → queued->preparing->ready). WP-1d owns the job body + a DEDUPED
	deterministic job_id (a still-`queued` reserved turn may be re-offered each
	slice; dedupe + the idempotent claim CAS make that a no-op). The default
	enqueues a conventionally-named job that does not exist yet, so it is a
	no-op-until-WP-1d in production and is ALWAYS replaced by tests."""
	try:
		frappe.enqueue(
			"jarvis.chat.prepare.run_prepare",
			queue="long",
			timeout=HOP_TIMEOUT_S,
			job_id=f"jarvis-prepare::{run_id}",
			deduplicate=True,
			run_id=run_id,
			relay_target_id=relay_target_id,
		)
	except Exception:
		frappe.log_error(title="pump.dispatch_prepare", message=frappe.get_traceback())


def _default_enqueue_finalize(run_id: str, relay_target_id: str) -> None:
	"""WP-1d SEAM 2b — finalize invoker. Enqueue the short finalize (enrichment)
	job. Used by settlement (D3 S6) AND by the watchdog for a `finalizing` turn
	(R-13: the watchdog's ONLY legal action there is re-enqueueing finalize).
	Deduped so a watchdog re-enqueue of an in-flight finalize is a no-op."""
	try:
		frappe.enqueue(
			"jarvis.chat.finalize.run_finalize",
			queue="long",
			timeout=HOP_TIMEOUT_S,
			job_id=f"jarvis-finalize::{run_id}",
			deduplicate=True,
			run_id=run_id,
			relay_target_id=relay_target_id,
		)
	except Exception:
		frappe.log_error(title="pump.enqueue_finalize", message=frappe.get_traceback())


def _default_invoke_settlement(
	run_id: str,
	*,
	relay_target_id: str,
	epoch: int,
	version: int,
	terminal_kind: str,
	terminal_payload: dict | None,
	assistant_message: str | None,
	owner: str | None,
	conversation: str,
	deps: "PumpDeps",
) -> None:
	"""WP-1d SEAM 2a — settlement/finalize invoker (D3 Race 3). Pump-invoked and
	EPOCH-fenced: the one critical transaction that writes the final projection,
	releases the conversation slot, fixes the owed-enrichment set, then (after the
	winning commit) publishes the fenced terminal ``run:end`` with
	``enrichment_pending`` (SUX-7) and enqueues finalize.

	WP-1d wires the FULL ownership-table settlement (``jarvis.chat.settlement``):
	final-text projection + slot release + the OAR-9 effect-ledger inserts in ONE
	epoch+version-fenced txn, then the authoritative fenced terminal event
	(``run:end`` w/ ``enrichment_pending`` SUX-7, or ``run:error`` preserving the
	Message.error classification SUX-11) AFTER commit, then ``enqueue_finalize``.
	A 0-rows LOSS raises ``LeaseLostExit`` (D3 S3) — the ``on_terminal`` wrapper
	converts it to the pump's shared exit. Lazy import so pump.py has no import
	cycle with settlement (settlement imports turn_state only)."""
	from jarvis.chat import settlement

	settlement.invoke_settlement(
		run_id,
		relay_target_id=relay_target_id,
		epoch=epoch,
		version=version,
		terminal_kind=terminal_kind,
		terminal_payload=terminal_payload,
		assistant_message=assistant_message,
		owner=owner,
		conversation=conversation,
		deps=deps,
	)


def _default_apply_tool(run_id: str, event: dict) -> None:
	"""WP-1d SEAM (R-6) — precious tool-event application. The real writer is fully
	OUT-OF-BAND with ``(session_key, tool_call_id)`` idempotency and conv-lock seq
	allocation (WP-1d). The default is a no-op so the pump streams tool-bearing
	turns without WP-1d present; a raise here would QUARANTINE the lane (precious),
	so it stays a no-op."""
	return None


def _default_snapshot(ctx: "PumpContext") -> dict:
	"""Snapshot / status reconcile source (Amendment D). Issues ``sessions.list``
	over the mux and returns the reconcile inputs the pump needs:

	  ``{"gateway_active": int, "active_session_keys": set[str] | None}``

	``gateway_active`` = FOREIGN ``main`` runs (gateway sessions with
	``hasActiveRun`` not matched to a local in-flight turn) — added to admission
	inflight so the bench never over-admits past a run it did not start (§10.1).
	``active_session_keys`` (or ``None`` = "no info") lets reconcile tell a
	genuinely-gone in-flight run from one still active. Best-effort; on any error
	returns the conservative empty snapshot (adopt-and-keep)."""
	try:
		fut = ctx.mux.issue_rpc("sessions.list", {}, timeout_s=ACK_TIMEOUT_S)
		frame = fut.result(ACK_TIMEOUT_S)
		payload = frame.get("payload") or frame.get("result") or {}
		sessions = payload.get("sessions") or []
		active_keys = {s.get("key") for s in sessions if s.get("hasActiveRun") and s.get("key")}
		local_keys = _local_active_session_keys(ctx.relay_target_id)
		foreign = len([k for k in active_keys if k not in local_keys])
		return {"gateway_active": foreign, "active_session_keys": active_keys}
	except Exception:
		return {"gateway_active": 0, "active_session_keys": None}


def _default_make_mux(relay_target_id: str, epoch: int) -> RelayMux:
	"""Construct + start a mux on a FRESH dedicated session for this shard
	(reconnect-per-hop; the pump owns connect, the mux is the I/O adapter). The
	gateway URL is resolved from Jarvis Settings ``agent_url``. Production
	(WP-1e) exercises this; tests inject a transport double."""
	from jarvis.chat.openclaw_client import OpenclawSession

	settings = frappe.get_cached_doc("Jarvis Settings")
	gateway_url = (
		(getattr(settings, "agent_url", "") or "").replace("http://", "ws://").replace("https://", "wss://")
	)
	session = OpenclawSession.connect(gateway_url)
	mux = RelayMux(session, relay_target_id, on_breaker=_on_poison_breaker)
	return mux.start()


def _default_enqueue_pump_job(
	*, method: str, queue: str, timeout: int, job_id: str, relay_target_id: str, hop_counter: int
) -> None:
	"""Internal seam — enqueue a hop / watchdog-start job. ALWAYS ``long`` with an
	EXPLICIT ``timeout`` and a FRESH ``job_id`` (§10.4). Tests inject a recorder
	to assert the args without running the successor."""
	frappe.enqueue(
		method,
		queue=queue,
		timeout=timeout,
		job_id=job_id,
		relay_target_id=relay_target_id,
		hop_counter=hop_counter,
	)


@dataclass
class PumpDeps:
	"""Injectable seams. The two WP-1d contracts are ``dispatch_prepare`` (prepare
	dispatcher) and ``invoke_settlement`` + ``enqueue_finalize`` (settlement/
	finalize invoker); the rest are pump-internal test seams. All default to the
	``_default_*`` implementations above."""

	dispatch_prepare: Callable[[str, str], None] = _default_dispatch_prepare
	invoke_settlement: Callable[..., None] = _default_invoke_settlement
	enqueue_finalize: Callable[[str, str], None] = _default_enqueue_finalize
	apply_tool: Callable[[str, dict], None] = _default_apply_tool
	snapshot: Callable[["PumpContext"], dict] = _default_snapshot
	make_mux: Callable[[str, int], RelayMux] = _default_make_mux
	enqueue_pump_job: Callable[..., None] = _default_enqueue_pump_job


def _default_deps() -> PumpDeps:
	return PumpDeps()


def _on_poison_breaker(target: str, count: int) -> None:
	"""Poison-rate circuit-breaker alarm (OAR-7): telemetry + the mux itself then
	refuses re-adopts (stop-readopting). We only record it here."""
	_telemetry("poison_breaker", target=target, count=count)


# --------------------------------------------------------------------------- #
# Per-run streaming state + the pump context
# --------------------------------------------------------------------------- #


@dataclass
class _RunState:
	"""Pump-thread-local bookkeeping for one in-flight run. ``version`` is tracked
	forward through the run's epoch-fenced CAS chain (confirm_dispatching ->
	mark_streaming -> apply_delta* -> mark_terminal_observed) so each CAS passes
	the exact current version without a re-read on the hot path; a 0-rows CAS
	re-reads to distinguish a benign version drift (concurrent cancel bumps
	version out-of-band) from a real epoch loss."""

	run_id: str
	conversation: str
	owner: str | None
	assistant_message: str | None
	session_key: str
	version: int
	gateway_run_id: str | None = None


@dataclass
class PumpContext:
	relay_target_id: str
	epoch: int
	holder: str
	hop_counter: int
	site: str
	deps: PumpDeps
	mux: RelayMux | None = None
	gateway_active: int = 0
	lease_lost: str | None = None
	soft_deadline: float = 0.0
	hard_deadline: float = 0.0
	last_heartbeat: float = 0.0
	runs: dict[str, _RunState] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# The RQ job body — run_pump_hop
# --------------------------------------------------------------------------- #


def run_pump_hop(
	relay_target_id: str,
	*,
	hop_counter: int = 0,
	deps: PumpDeps | None = None,
	soft_budget_s: float = SOFT_HOP_BUDGET_S,
	hard_deadline_s: float = HARD_HOP_DEADLINE_S,
	max_slices: int | None = None,
) -> dict:
	"""One bounded pump hop (the RQ job body; enqueued to ``long`` with an
	explicit ``timeout``). Lifecycle (D6):

	  1. LEASE ACQUIRE = mini-takeover (EVERY hop, §10.5/R-11): epoch bump +
	     adopted-turn re-stamp, via ``turn_state.lease_acquire``. A lost acquire
	     means another pump owns the shard — return without draining.
	  2. RECONCILE on start (Amendment D): snapshot ``sessions.list``, settle
	     settlement-owed turns from the row (R-12), re-attach in-flight lanes,
	     recover parked turns per origin.
	  3. DRAIN LOOP: call :func:`drain_slice` repeatedly until the soft budget
	     (90s). An idle-exit slice releases the lease and returns.
	  4. HANDOFF at soft budget: bump ``hop_counter``, enqueue the successor
	     ``jarvis-pump::<site>::<target>::hop<n+1>`` with an EXPLICIT
	     ``timeout=180`` to ``long`` ALWAYS (fresh id — frappe dedupe trap), exit.

	``LeaseLostExit`` anywhere ⇒ the ONE shared exit (stop reading, no publishes,
	hop returns). A persistent DB operational error ⇒ bounded backoff then park
	the affected turns ``recovering`` and exit (never spin, D6 §6). ``max_slices``
	/ ``soft_budget_s`` are test knobs; production uses the constants."""
	deps = deps or _default_deps()
	site = frappe.local.site
	holder = f"jarvis-pump::{site}::{relay_target_id}::hop{hop_counter}"

	won, epoch = ts.lease_acquire(relay_target_id, holder, hop_counter=hop_counter)
	if not won or epoch is None:
		return {"acquired": False, "relay_target_id": relay_target_id}
	_write_lease_mirror(relay_target_id)

	ctx = PumpContext(
		relay_target_id=relay_target_id,
		epoch=epoch,
		holder=holder,
		hop_counter=hop_counter,
		site=site,
		deps=deps,
	)
	now = _monotonic()
	ctx.soft_deadline = now + soft_budget_s
	ctx.hard_deadline = now + hard_deadline_s
	ctx.last_heartbeat = now

	try:
		ctx.mux = deps.make_mux(relay_target_id, epoch)
	except Exception:
		# Could not build the transport this hop; leave the lease to expire and let
		# ensure_pump / the watchdog revive on the next cycle. Do not crash the job.
		frappe.log_error(title="pump.make_mux", message=frappe.get_traceback())
		return {"acquired": True, "exit": "no_transport", "epoch": epoch}

	outcome = "handoff"
	op_errors = 0
	try:
		_reconcile_on_start(ctx)
		slices = 0
		while _monotonic() < ctx.soft_deadline and _monotonic() < ctx.hard_deadline:
			try:
				result = drain_slice(ctx)
				op_errors = 0
			except ts.LeaseLostExit:
				outcome = "lease_lost"
				break
			except _operational_errors():
				op_errors += 1
				if op_errors >= DB_BACKOFF_ATTEMPTS:
					_park_affected_recovering(ctx)
					outcome = "db_disconnect"
					break
				_backoff_reconnect(op_errors)
				continue
			slices += 1
			if result == "idle_exit":
				outcome = "idle"
				break
			if max_slices is not None and slices >= max_slices:
				outcome = "max_slices"
				break
		else:
			outcome = "handoff"
		if outcome == "handoff":
			_handoff(ctx)
	except ts.LeaseLostExit:
		outcome = "lease_lost"
	finally:
		try:
			if ctx.mux is not None:
				ctx.mux.stop()
		except Exception:
			pass
		ts.reset_lock_tracking()
	return {"acquired": True, "exit": outcome, "epoch": epoch}


# --------------------------------------------------------------------------- #
# drain_slice — the reactor body (a standalone function, F/§8-E)
# --------------------------------------------------------------------------- #


def drain_slice(ctx: PumpContext) -> str:
	"""One reactor slice. Returns ``"idle_exit"`` (lease released — the hop exits)
	or ``"continue"``. Steps:

	  1. drain the wake bus (advisory);
	  2. promote queued turns (reserve credit at queued->preparing under the shard
	     lock, then dispatch prepare — the CREDIT gate for leaving `queued`);
	  3. dispatch ready turns (ready->dispatching stamping the epoch, mux
	     ``send_chat`` with the run_id idempotency key, ack -> dispatching->
	     streaming with gateway_run_id; a DEFINITE ok:false rejection ->
	     dispatching->errored + credit release; the ack-timeout sentinel -> park
	     recovering);
	  4. pump the mux reader (apply deltas/tools/terminals via the lane handlers);
	  5. propagate a lease loss signalled from a lane callback;
	  6. cancel-requested sweep (out-of-band ``chat.abort`` then the aborted
	     terminal + settle);
	  7. heartbeat + lease renew (0 rows ⇒ lease-loss exit);
	  8. idle-exit conditional release (0 rows ⇒ CONTINUE, OAR-12).
	"""
	drain_wake(ctx.relay_target_id)

	_promote_queued(ctx)
	_dispatch_ready(ctx)

	if ctx.mux is not None:
		ctx.mux.dispatch(block_s=SLICE_BLOCK_S)
	if ctx.lease_lost:
		ts.lease_lost_exit(ctx.lease_lost)

	_cancel_sweep(ctx)

	_heartbeat_and_renew(ctx)

	if _idle_exit(ctx):
		return "idle_exit"
	return "continue"


# --------------------------------------------------------------------------- #
# Step 2 — promote (full-credit admission under the shard lock, D3 Race 2)
# --------------------------------------------------------------------------- #


def _promote_queued(ctx: PumpContext) -> int:
	"""Reserve credit for eligible `queued` turns at the queued->preparing
	promotion point and enqueue prepare for them (D3 Race 2 / OAR-1/OAR-2).

	LOCK ORDER (OAR-6): control(shard) -> conversation -> turn -> message. We take
	ONLY the shard control row here (``turn_state._lock_shard``), which restates
	the commit-first REPEATABLE-READ discipline: it commits to start a fresh
	transaction so the ``SELECT ... FOR UPDATE`` is the first statement and the
	credit COUNT that follows takes its snapshot AFTER the prior holder committed
	(never a non-locking read before the lock). Both admission call sites (this
	one and accept_send) serialize the credit count+reserve on the SHARD, which is
	what closes the cross-conversation double-admit race (OAR-1). The prepare
	enqueue happens AFTER the commit that releases the lock."""
	target = ctx.relay_target_id
	to_prepare: list[str] = []
	try:
		ts._lock_shard(target)  # commit-first; FOR UPDATE is the first statement
		active_convs = _pump_active_convs(target)
		promoted_convs: set[str] = set()

		# (a) queued turns that ALREADY hold a credit (reserve-on-send winners):
		#     dispatch prepare, no re-reserve (they are counted in local_res).
		for row in _pump_queued_reserved(target):
			conv = row["conversation"]
			if conv in active_convs or conv in promoted_convs:
				continue
			to_prepare.append(row["run_id"])
			promoted_convs.add(conv)

		# (b) cold queued turns (reserved=0): reserve under the credit ceiling.
		while True:
			usable = _pump_usable_credit(ctx)
			if usable <= 0:
				break
			candidate = _pick_next_cold(target, active_convs, promoted_convs)
			if candidate is None:
				break
			if ts.reserve_credit(candidate["run_id"]):
				to_prepare.append(candidate["run_id"])
				promoted_convs.add(candidate["conversation"])
			# else lost the row to a concurrent actor; loop re-reads.

		frappe.db.commit()  # releases the shard lock; reservations durable
	except Exception:
		frappe.db.rollback()
		ts.reset_lock_tracking()
		raise
	ts.reset_lock_tracking()

	for run_id in to_prepare:
		try:
			ctx.deps.dispatch_prepare(run_id, target)
		except Exception:
			frappe.log_error(title="pump.promote.dispatch_prepare", message=frappe.get_traceback())
	if to_prepare:
		_telemetry("promote", target=target, count=len(to_prepare))
	return len(to_prepare)


def _pump_usable_credit(ctx: PumpContext) -> int:
	"""usable = min(hard_cap, learned_cap) - inflight - safety_reserve (§9-D2).
	inflight = local reservations (reserved OR dispatching/streaming/
	terminal_observed, unexpired) + FOREIGN gateway active runs. Learned cap =
	hard cap until WP-2 telemetry lands (no learned signal yet)."""
	from jarvis.chat import admission

	hard = admission._max_inflight()
	learned = hard
	local_res = _pump_local_reservations(ctx.relay_target_id)
	inflight = local_res + max(0, int(ctx.gateway_active))
	return min(hard, learned) - inflight - SAFETY_RESERVE


def _pump_local_reservations(target: str) -> int:
	"""D3 Race 2 ``local_res``: turns consuming a credit on the shard — reserved
	(pre-dispatch) OR in-flight (dispatching/streaming/terminal_observed) — whose
	reservation has not expired. An expired UNCLAIMED reservation is excluded so
	its credit auto-reclaims on the next recompute (OAR-5)."""
	return int(
		frappe.db.sql(
			f"""SELECT COUNT(*) FROM `tab{TURN}`
			WHERE relay_target_id=%(t)s
			  AND ( reserved=1 OR state IN ('dispatching','streaming','terminal_observed') )
			  AND ( reservation_expires_at IS NULL OR reservation_expires_at > %(now)s )""",
			{"t": target, "now": ts._now()},
		)[0][0]
	)


def _pump_active_convs(target: str) -> set[str]:
	"""Conversations with a turn already in flight (single-flight scope)."""
	rows = frappe.db.sql(
		f"""SELECT DISTINCT conversation FROM `tab{TURN}`
		WHERE relay_target_id=%(t)s
		  AND state IN ('preparing','ready','dispatching','streaming','terminal_observed')""",
		{"t": target},
	)
	return {r[0] for r in rows}


def _pump_queued_reserved(target: str) -> list[dict]:
	return frappe.db.sql(
		f"""SELECT run_id, conversation FROM `tab{TURN}`
		WHERE relay_target_id=%(t)s AND state='queued' AND reserved=1
		  AND ( reservation_expires_at IS NULL OR reservation_expires_at > %(now)s )
		ORDER BY CASE turn_class WHEN 'interactive' THEN 0 ELSE 1 END, enqueued_at ASC, run_id ASC""",
		{"t": target, "now": ts._now()},
		as_dict=True,
	)


def _pick_next_cold(target: str, active_convs: set[str], promoted_convs: set[str]) -> dict | None:
	"""Choose the next cold (reserved=0) queued turn to reserve — weighted classes
	with a background floor of 1 (SUX-4a: when background work is queued,
	interactive holds at most cap-1 credits), per-conversation single-flight."""
	rows = frappe.db.sql(
		f"""SELECT run_id, conversation, turn_class FROM `tab{TURN}`
		WHERE relay_target_id=%(t)s AND state='queued' AND reserved=0
		ORDER BY enqueued_at ASC, run_id ASC LIMIT 200""",
		{"t": target},
		as_dict=True,
	)

	def eligible(r: dict) -> bool:
		conv = r["conversation"]
		return conv not in active_convs and conv not in promoted_convs

	interactive = next((r for r in rows if r["turn_class"] == "interactive" and eligible(r)), None)
	background = next((r for r in rows if r["turn_class"] == "background" and eligible(r)), None)

	if interactive and background:
		from jarvis.chat import admission

		cap = admission._max_inflight()
		int_inflight = _turn_state_count(target, "interactive")
		if cap >= 2 and int_inflight >= cap - 1:
			return background
		return interactive
	return interactive or background


def _turn_state_count(target: str, turn_class: str) -> int:
	return int(
		frappe.db.sql(
			f"""SELECT COUNT(*) FROM `tab{TURN}`
			WHERE relay_target_id=%(t)s AND turn_class=%(k)s
			  AND state IN ('preparing','ready','dispatching','streaming','terminal_observed')""",
			{"t": target, "k": turn_class},
		)[0][0]
	)


# --------------------------------------------------------------------------- #
# Step 3 — dispatch ready turns (ready -> dispatching -> streaming)
# --------------------------------------------------------------------------- #


def _dispatch_ready(ctx: PumpContext) -> int:
	target = ctx.relay_target_id
	rows = frappe.db.sql(
		f"""SELECT run_id FROM `tab{TURN}`
		WHERE relay_target_id=%(t)s AND state='ready'
		ORDER BY ready_at ASC, run_id ASC LIMIT 50""",
		{"t": target},
		as_dict=True,
	)
	dispatched = 0
	for r in rows:
		if _dispatch_one(ctx, r["run_id"]):
			dispatched += 1
	return dispatched


def _dispatch_one(ctx: PumpContext, run_id: str) -> bool:
	"""ready -> dispatching (stamp epoch, CONFIRM-only) then ``chat.send`` and the
	ack transition. Returns True if a stream was started."""
	turn = _read_dispatch_row(run_id)
	if turn is None or turn["state"] != "ready":
		return False

	# ready -> dispatching: E is FIRST stamped here (state+version fenced, no epoch
	# in the guard). A 0-rows loss here is NOT a lease loss (epoch not yet ours on
	# the row) — a concurrent cancel/version drift; skip.
	if not ts.confirm_dispatching(run_id, int(turn["version"]), ctx.epoch):
		return False
	frappe.db.commit()

	owner = frappe.db.get_value(CONV, turn["conversation"], "owner")
	dispatch = _load_dispatch(turn)
	rs = _RunState(
		run_id=run_id,
		conversation=turn["conversation"],
		owner=owner,
		assistant_message=turn.get("assistant_message"),
		session_key=dispatch["session_key"],
		version=int(turn["version"]) + 1,
		gateway_run_id=None,
	)
	ctx.runs[run_id] = rs

	# run:start is pump-owned + epoch-fenced (R-1): the browser's "running" signal
	# comes only from the writer that actually owns the stream.
	if owner:
		ts.publish_fenced(owner, "run:start", conversation_id=rs.conversation, run_id=run_id)

	handler = _make_handler(ctx, rs)
	try:
		fut = ctx.mux.send_chat(
			rs.session_key,
			dispatch["message"],
			run_id,
			handler,
			timeout_s=ACK_TIMEOUT_S,
			start_seq=int(turn.get("last_event_seq") or 0),
			thinking=dispatch.get("thinking"),
			attachments=dispatch.get("attachments"),
		)
		ack = fut.result(ACK_TIMEOUT_S)
	except OpenclawUnreachableError as exc:
		return _handle_ack_failure(ctx, rs, exc)

	payload = ack.get("payload") or ack.get("result") or {}
	gw = payload.get("runId") or run_id
	if gw != run_id:
		ctx.mux.rekey_run(run_id, gw)
	rs.gateway_run_id = gw

	# dispatching -> streaming (record gateway_run_id, epoch-fenced).
	if ts.mark_streaming(run_id, rs.version, ctx.epoch, gateway_run_id=gw):
		rs.version += 1
		frappe.db.commit()
		# R-2: the ack PROVES delivery, so clear EXACTLY the agent-correction notes
		# prepare folded into this prompt (id-keyed, idempotent). Deferred from
		# WP-1c; the clear must fire on proven delivery (post-ack), never on an
		# ack-timeout. Best-effort — a clear failure never breaks the stream.
		_clear_agent_notes_on_ack(rs.conversation, dispatch.get("drained_note_ids"))
		return True
	# 0 rows: distinguish a real epoch loss from a benign version drift (e.g. a
	# concurrent cancel bumped version out-of-band).
	if _epoch_lost(ctx, run_id):
		ts.lease_lost_exit(run_id)
	rs.version = _resync_version(run_id)
	return False


def _handle_ack_failure(ctx: PumpContext, rs: _RunState, exc: OpenclawUnreachableError) -> bool:
	"""Ack did not resolve OK. The ``ack-timeout`` sentinel (also the Closing/WS
	drop sentinel, OAR-10) is AMBIGUOUS — the request was written, the peer may
	have accepted it — so park recovering. A DEFINITE pre-ack rejection (ok:false
	with a concrete code) is dispatching->errored + credit release (OAR-8)."""
	run_id = rs.run_id
	code = getattr(exc, "code", None)
	if code == "ack-timeout":
		_park_recovering(ctx, run_id, reason="ack-timeout")
		return False
	# Definite rejection.
	turn = ts.read_turn(run_id)
	if turn is None:
		return False
	if ts.dispatch_errored(run_id, int(turn["version"]), ctx.epoch, error=str(exc)):
		frappe.db.commit()
		if rs.owner:
			ts.publish_fenced(rs.owner, "run:end", conversation_id=rs.conversation, run_id=run_id)
		return False
	if _epoch_lost(ctx, run_id):
		ts.lease_lost_exit(run_id)
	return False


# --------------------------------------------------------------------------- #
# Lane handlers — wire the mux integrity classes to turn_state CAS + publishes
# --------------------------------------------------------------------------- #


def _make_handler(ctx: PumpContext, rs: _RunState) -> LaneHandler:
	"""Build the per-turn lane callbacks (they run ON THE PUMP THREAD inside
	``mux.dispatch``). A ``LeaseLostExit`` raised inside a callback is CAUGHT and
	converted into ``ctx.lease_lost`` (the mux would otherwise treat a raise as
	poison and quarantine the lane); ``drain_slice`` raises the shared exit after
	``dispatch`` returns. Any OTHER exception propagates so the mux applies its
	integrity class (LOSSY delta -> drop+count+continue; PRECIOUS tool/terminal ->
	quarantine)."""

	def on_delta(event_seq: int, text: str, delta: str) -> None:
		if ctx.lease_lost:
			return
		try:
			won = ts.apply_delta(
				run_id=rs.run_id,
				version=rs.version,
				epoch=ctx.epoch,
				event_seq=event_seq,
				assistant_message=rs.assistant_message,
				content=text,
			)
			if won:
				rs.version += 1
				frappe.db.commit()
				if rs.owner:
					ts.publish_fenced(
						rs.owner,
						"run:delta",
						conversation_id=rs.conversation,
						run_id=rs.run_id,
						event_seq=event_seq,
						text=text,
						delta=delta,
					)
			else:
				# Benign (watermark dup / version drift) vs real epoch loss.
				if _epoch_lost(ctx, rs.run_id):
					ts.lease_lost_exit(rs.run_id)
				rs.version = _resync_version(rs.run_id)
		except ts.LeaseLostExit:
			ctx.lease_lost = rs.run_id

	def on_tool(event: dict) -> None:
		# PRECIOUS: a raise here quarantines the lane. The out-of-band receipt
		# writer (R-6) is WP-1d; the default is a no-op.
		ctx.deps.apply_tool(rs.run_id, event)

	def on_terminal(kind: str, payload: dict) -> None:
		if ctx.lease_lost:
			return
		try:
			won = ts.mark_terminal_observed(rs.run_id, rs.version, ctx.epoch, kind, payload)
			if not won:
				if _epoch_lost(ctx, rs.run_id):
					ts.lease_lost_exit(rs.run_id)
				return
			rs.version += 1
			frappe.db.commit()
			ctx.deps.invoke_settlement(
				rs.run_id,
				relay_target_id=ctx.relay_target_id,
				epoch=ctx.epoch,
				version=rs.version,
				terminal_kind=kind,
				terminal_payload=payload,
				assistant_message=rs.assistant_message,
				owner=rs.owner,
				conversation=rs.conversation,
				deps=ctx.deps,
			)
		except ts.LeaseLostExit:
			ctx.lease_lost = rs.run_id

	def on_quarantine(reason: str) -> None:
		# The mux fenced this lane off (precious fault / overflow). Park the turn
		# toward recovering (out of band, D5 §5-c).
		try:
			_park_recovering(ctx, rs.run_id, reason=reason)
		except ts.LeaseLostExit:
			ctx.lease_lost = rs.run_id

	def on_closing(sentinel: str) -> None:
		# Transport lost — nothing durable to write; the next hop re-attaches from
		# durable state (last_event_seq). The pump's own hop ends via the reader.
		return None

	return LaneHandler(
		on_delta=on_delta,
		on_tool=on_tool,
		on_terminal=on_terminal,
		on_quarantine=on_quarantine,
		on_closing=on_closing,
	)


# --------------------------------------------------------------------------- #
# Step 6 — cancel-requested sweep (out-of-band abort -> aborted terminal)
# --------------------------------------------------------------------------- #


def _cancel_sweep(ctx: PumpContext) -> int:
	"""For in-flight turns the web sender flagged ``cancel_requested`` (D2 row 17),
	drive the out-of-band ``chat.abort`` (the bus is never the only abort route,
	Amendment D), record the aborted terminal (D2 row 18), then settle to
	``cancelled`` (D2 row 19 via the settlement seam)."""
	target = ctx.relay_target_id
	rows = frappe.db.sql(
		f"""SELECT run_id, state, version, gateway_run_id, conversation, assistant_message
		FROM `tab{TURN}`
		WHERE relay_target_id=%(t)s AND cancel_requested=1
		  AND state IN ('dispatching','streaming') AND pump_epoch=%(e)s""",
		{"t": target, "e": ctx.epoch},
		as_dict=True,
	)
	swept = 0
	for r in rows:
		run_id = r["run_id"]
		rs = ctx.runs.get(run_id)
		session_key = (
			rs.session_key if rs else _load_dispatch(_read_dispatch_row(run_id) or {}).get("session_key", "")
		)
		# Out-of-band abort (best-effort — the terminal frame will also arrive).
		try:
			if ctx.mux is not None and session_key:
				ctx.mux.abort(session_key, r.get("gateway_run_id"), timeout_s=ACK_TIMEOUT_S).result(
					ACK_TIMEOUT_S
				)
		except Exception:
			pass
		if not ts.record_aborted_terminal(run_id, r["state"], int(r["version"]), ctx.epoch):
			if _epoch_lost(ctx, run_id):
				ts.lease_lost_exit(run_id)
			continue
		frappe.db.commit()
		owner = frappe.db.get_value(CONV, r["conversation"], "owner")
		try:
			ctx.deps.invoke_settlement(
				run_id,
				relay_target_id=target,
				epoch=ctx.epoch,
				version=int(r["version"]) + 1,
				terminal_kind="relay:error",
				terminal_payload={"aborted": True},
				assistant_message=r.get("assistant_message"),
				owner=owner,
				conversation=r["conversation"],
				deps=ctx.deps,
			)
		except ts.LeaseLostExit:
			ctx.lease_lost = run_id
			raise
		swept += 1
	return swept


# --------------------------------------------------------------------------- #
# Step 7 — heartbeat + lease renew
# --------------------------------------------------------------------------- #


def _heartbeat_and_renew(ctx: PumpContext) -> None:
	"""Write ``loop_heartbeat_ts`` (loop-liveness, DISTINCT from lease renewal) and
	renew the lease, at most once per HEARTBEAT_INTERVAL_S. A 0-rows renew/
	heartbeat means the epoch was lost to a takeover ⇒ shared lease-loss exit."""
	now = _monotonic()
	if now - ctx.last_heartbeat < HEARTBEAT_INTERVAL_S:
		return
	ctx.last_heartbeat = now
	if not ts.lease_heartbeat(ctx.relay_target_id, ctx.epoch):
		ts.lease_lost_exit()
	if not ts.lease_renew(ctx.relay_target_id, ctx.epoch, holder=ctx.holder):
		ts.lease_lost_exit()
	_write_lease_mirror(ctx.relay_target_id)


# --------------------------------------------------------------------------- #
# Step 8 — idle-exit conditional release (D6 §2, OAR-12)
# --------------------------------------------------------------------------- #


def _idle_exit(ctx: PumpContext) -> bool:
	"""Idle exit = ONE atomic conditional release (never check-then-release). The
	release affects 1 row ONLY if this pump still holds the epoch AND no
	nonterminal turn remains on the shard. Acting on the affected-rows count is
	NORMATIVE (OAR-12): 0 rows ⇒ work remains (a turn committed during exit) OR
	the epoch was lost ⇒ KEEP the lease and CONTINUE the drain loop. True ⇒
	released, the hop exits."""
	if ts.lease_release_if_idle(ctx.relay_target_id, ctx.epoch):
		_clear_lease_mirror(ctx.relay_target_id)
		return True
	return False


# --------------------------------------------------------------------------- #
# Reconcile on start (Amendment D) + recovery parking
# --------------------------------------------------------------------------- #


def _reconcile_on_start(ctx: PumpContext) -> None:
	"""Runs on EVERY hop start/reconnect (not just crashes). ``lease_acquire``
	already re-stamped adopted in-flight turns (dispatching/streaming/
	terminal_observed) to the new epoch and bumped their version (D4-c). Here we:
	  * pull the snapshot (foreign gateway active count for admission);
	  * SETTLE settlement-owed turns from the row (R-12 — zero gateway round-trips);
	  * RE-ATTACH in-flight lanes so the future-only broadcast resumes;
	  * recover parked (`recovering`) turns per origin (OAR-4)."""
	target = ctx.relay_target_id
	try:
		snap = ctx.deps.snapshot(ctx)
	except Exception:
		snap = {"gateway_active": 0, "active_session_keys": None}
	ctx.gateway_active = int(snap.get("gateway_active") or 0)
	active_keys = snap.get("active_session_keys")

	rows = frappe.db.sql(
		f"""SELECT run_id, state, version, conversation, assistant_message,
		       last_event_seq, gateway_run_id, dispatching_at, recovery_started_at
		FROM `tab{TURN}`
		WHERE relay_target_id=%(t)s
		  AND state IN ('dispatching','streaming','terminal_observed','recovering')""",
		{"t": target},
		as_dict=True,
	)
	for r in rows:
		try:
			_reconcile_one(ctx, r, active_keys)
		except ts.LeaseLostExit:
			raise
		except Exception:
			frappe.log_error(title="pump.reconcile", message=frappe.get_traceback())


def _reconcile_one(ctx: PumpContext, r: dict, active_keys) -> None:
	run_id = r["run_id"]
	state = r["state"]

	if state == "terminal_observed":
		# Settlement owed (R-12). Settle from the row.
		owner = frappe.db.get_value(CONV, r["conversation"], "owner")
		ctx.deps.invoke_settlement(
			run_id,
			relay_target_id=ctx.relay_target_id,
			epoch=ctx.epoch,
			version=int(r["version"]),
			terminal_kind=frappe.db.get_value(TURN, run_id, "terminal_kind"),
			terminal_payload=_json_or_none(frappe.db.get_value(TURN, run_id, "terminal_payload")),
			assistant_message=r.get("assistant_message"),
			owner=owner,
			conversation=r["conversation"],
			deps=ctx.deps,
		)
		return

	if state == "recovering":
		if r.get("dispatching_at") is None:
			# Parked PRE-dispatch (OAR-4): back to queued for a FRESH prepare.
			ts.recover_to_queued(run_id, int(r["version"]))
			frappe.db.commit()
			return
		# Parked IN-flight: adopt (re-stamp epoch), then re-attach.
		if ts.recover_adopt(run_id, int(r["version"]), ctx.epoch, target_state="streaming"):
			frappe.db.commit()
			r = {**r, "version": int(r["version"]) + 1, "state": "streaming"}
			_reattach_lane(ctx, r)
		return

	# dispatching / streaming — already re-stamped in place by lease_acquire.
	_reattach_lane(ctx, r)


def _reattach_lane(ctx: PumpContext, r: dict) -> None:
	"""Re-register a lane so the future-only broadcast resumes for an adopted
	in-flight turn (start_seq seeded from the durable ``last_event_seq`` so the
	watermark stays monotonic across the hop, WP-1B deviation 2). A breaker-open
	re-adopt is refused (register_run returns None) — stop-readopting (OAR-7)."""
	run_id = r["run_id"]
	owner = frappe.db.get_value(CONV, r["conversation"], "owner")
	dispatch = _load_dispatch(_read_dispatch_row(run_id) or {})
	rs = _RunState(
		run_id=run_id,
		conversation=r["conversation"],
		owner=owner,
		assistant_message=r.get("assistant_message"),
		session_key=dispatch.get("session_key", ""),
		version=int(r["version"]),
		gateway_run_id=r.get("gateway_run_id"),
	)
	ctx.runs[run_id] = rs
	lane_key = r.get("gateway_run_id") or run_id
	if ctx.mux is not None:
		ctx.mux.register_run(
			lane_key,
			_make_handler(ctx, rs),
			session_key=rs.session_key,
			start_seq=int(r.get("last_event_seq") or 0),
			is_readopt=True,
		)


def _park_recovering(ctx: PumpContext, run_id: str, *, reason: str) -> None:
	"""Park a turn toward the durable recovery route (D2 row 20) and publish the
	fenced ``run:recovering`` AFTER commit (SUX-1 — the event name/payload the
	ChatView 'Reconnecting' banner already consumes). Actor-fenced (the park is
	not a pump-owned epoch write), so a benign 0-rows (already parked/moved) is
	not a lease loss."""
	turn = ts.read_turn(run_id)
	if turn is None:
		return
	if ts.mark_recovering(run_id, int(turn["version"])):
		frappe.db.commit()
		owner = frappe.db.get_value(CONV, turn_conversation(run_id), "owner")
		if owner:
			ts.publish_fenced(
				owner,
				"run:recovering",
				conversation_id=turn_conversation(run_id),
				run_id=run_id,
				reason=reason,
			)
	_telemetry("park_recovering", run_id=run_id, reason=reason)


def _park_affected_recovering(ctx: PumpContext) -> None:
	"""DB-disconnect park (D6 §6): mark the shard's in-flight turns ``recovering``
	so the next hop re-attaches from durable state, then let the hop exit. Never
	spins. Best-effort — if the DB is truly down the marks fail and we simply
	exit; the watchdog/ensure_pump revives later."""
	target = ctx.relay_target_id
	try:
		rows = frappe.db.sql(
			f"""SELECT run_id, version FROM `tab{TURN}`
			WHERE relay_target_id=%(t)s
			  AND state IN ('preparing','ready','dispatching','streaming','terminal_observed')""",
			{"t": target},
			as_dict=True,
		)
	except Exception:
		return
	for r in rows:
		try:
			if ts.mark_recovering(r["run_id"], int(r["version"])):
				frappe.db.commit()
		except Exception:
			try:
				frappe.db.rollback()
			except Exception:
				pass


# --------------------------------------------------------------------------- #
# ensure_pump — the sender-driven PRIMARY start/recovery path (§8-E)
# --------------------------------------------------------------------------- #


def ensure_pump(relay_target_id: str, *, deps: PumpDeps | None = None) -> dict:
	"""Start the pump if it is not already leased. MariaDB-authoritative start
	decision (R-17 / §10.6): the Redis mirror may only gate the fast NO-OP path,
	never prove vacancy. Callable after EVERY durable commit (accept_send after
	its commit is the PRIMARY start/recovery path — effectively instant, no
	scheduler dependency). Enqueues hop0 to ``long`` with an EXPLICIT
	``timeout=180`` under a FRESH job id (the frappe dedupe trap)."""
	deps = deps or _default_deps()
	target = relay_target_id
	site = frappe.local.site

	if _lease_mirror_live(target):
		return {"enqueued": False, "reason": "mirror_live"}

	ts._ensure_control_row(target)
	row = frappe.db.get_value(PUMP, target, ["lease_expires_at", "hop_counter"], as_dict=True)
	now = ts._now()
	if row and row.get("lease_expires_at"):
		if frappe.utils.get_datetime(row["lease_expires_at"]) > frappe.utils.get_datetime(now):
			return {"enqueued": False, "reason": "lease_live"}

	hop = int((row.get("hop_counter") if row else 0) or 0) + 1
	job_id = f"jarvis-pump::{site}::{target}::hop{hop}"
	deps.enqueue_pump_job(
		method="jarvis.chat.pump.run_pump_hop",
		queue=PUMP_QUEUE,
		timeout=HOP_TIMEOUT_S,
		job_id=job_id,
		relay_target_id=target,
		hop_counter=hop,
	)
	return {"enqueued": True, "job_id": job_id, "hop_counter": hop}


def request_cancel_conversation(relay_or_conversation: str) -> bool:
	"""Web ``stop_run`` hook (pump mode): flag the conversation's in-flight pump turn
	for cancellation (D2 #17, actor-fenced) and wake the pump so its cancel sweep
	drives the out-of-band ``chat.abort`` + aborted terminal + settle-cancelled.
	Best-effort; returns True iff a turn was flagged. NOT terminal itself — the pump
	still owns the abort + settle."""
	conversation = relay_or_conversation
	row = frappe.db.get_value(
		TURN,
		{"conversation": conversation, "state": ["in", ("dispatching", "streaming")]},
		["run_id", "version", "relay_target_id"],
		as_dict=True,
	)
	if not row:
		return False
	if ts.request_cancel(row["run_id"], int(row["version"])):
		frappe.db.commit()
		ensure_pump(row["relay_target_id"])
		lpush_wake(row["relay_target_id"], row["run_id"])
		return True
	return False


def _handoff(ctx: PumpContext) -> None:
	"""Hop handoff (D6 §3): increment ``hop_counter`` and enqueue the successor
	under a FRESH job id ``jarvis-pump::<site>::<target>::hop<n+1>`` (the SAME id
	would be silently deduped — the frappe self-chain trap), ALWAYS to ``long``
	with an EXPLICIT ``timeout=180``. The lease (not the job id) enforces
	single-instance; the successor re-acquires + bumps the epoch, fencing this
	hop."""
	next_hop = ctx.hop_counter + 1
	job_id = f"jarvis-pump::{ctx.site}::{ctx.relay_target_id}::hop{next_hop}"
	frappe.db.set_value(PUMP, ctx.relay_target_id, "hop_counter", next_hop, update_modified=False)
	frappe.db.commit()
	ctx.deps.enqueue_pump_job(
		method="jarvis.chat.pump.run_pump_hop",
		queue=PUMP_QUEUE,
		timeout=HOP_TIMEOUT_S,
		job_id=job_id,
		relay_target_id=ctx.relay_target_id,
		hop_counter=next_hop,
	)


# --------------------------------------------------------------------------- #
# watchdog — the 240s scheduler backstop (§8-E, D6 §5)
# --------------------------------------------------------------------------- #


def watchdog(deps: PumpDeps | None = None) -> dict:
	"""Last-resort backstop (hooks cron; the sender path is PRIMARY). Scans ALL
	nonterminal states across every shard and applies the per-state actions
	(amended D2), then ``ensure_pump`` for any shard with live work. The one gap
	the sender path cannot cover: a turn was committed, the pump died, and NO new
	send arrives to fire ``ensure_pump``. Never raises out (best-effort)."""
	deps = deps or _default_deps()
	summary = {"aged_out": 0, "reclaimed": 0, "parked": 0, "finalize_requeued": 0, "errored": 0, "revived": 0}
	try:
		targets = [
			r[0]
			for r in frappe.db.sql(
				f"""SELECT DISTINCT relay_target_id FROM `tab{TURN}`
				WHERE state IN ({_in_list(ts.NONTERMINAL_STATES)})"""
			)
		]
	except Exception:
		return summary
	for target in targets:
		try:
			_watchdog_shard(target, deps, summary)
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title="pump.watchdog", message=frappe.get_traceback())
	return summary


def _watchdog_shard(target: str, deps: PumpDeps, summary: dict) -> None:
	now = ts._now()
	# A stale lease is not parked here — ensure_pump (below) revives the pump,
	# which re-stamps + reconciles in-flight turns on start (D6 §5). The watchdog
	# parks only on a per-turn deadline / recovery budget.
	rows = frappe.db.sql(
		f"""SELECT run_id, state, version, reserved, reservation_expires_at, enqueued_at,
		       preparing_at, deadline_at, dispatching_at, recovery_started_at, conversation, seed_message
		FROM `tab{TURN}`
		WHERE relay_target_id=%(t)s AND state IN ({_in_list(ts.NONTERMINAL_STATES)})""",
		{"t": target},
		as_dict=True,
	)

	live_work = False
	for r in rows:
		state = r["state"]
		v = int(r["version"])
		run_id = r["run_id"]

		if state == "queued":
			# Age-out (SUX-5).
			if _older_than(r.get("enqueued_at"), ts.QUEUED_MAX_AGE_S):
				if ts.cancel_queued_max_age(run_id, v, _AGE_OUT_REASON):
					frappe.db.commit()
					_publish_cancelled(r, _AGE_OUT_REASON)
					summary["aged_out"] += 1
					continue
			# Expired UNCLAIMED reservation cleanup (OAR-5): recovering->queued.
			if int(r.get("reserved") or 0) and _expired(r.get("reservation_expires_at"), now):
				if ts.mark_recovering(run_id, v):
					frappe.db.commit()
					if ts.recover_to_queued(run_id, v + 1):
						frappe.db.commit()
						summary["reclaimed"] += 1
			live_work = True

		elif state == "preparing":
			# PREPARE_DEADLINE_S=300 (OAR-5): recovering->queued (fresh prepare).
			if ts.mark_recovering(run_id, v, require_prepare_deadline=True):
				frappe.db.commit()
				if ts.recover_to_queued(run_id, v + 1):
					frappe.db.commit()
					summary["reclaimed"] += 1
			live_work = True

		elif state in ("ready", "dispatching", "streaming", "terminal_observed"):
			# Deadline exceeded (per-turn soft deadline) -> park; budget exhausted
			# -> errored. Otherwise the revived pump adopts/settles (ensure_pump).
			if _recovery_budget_exhausted(r, now):
				if ts.recover_errored(run_id, v, error=_STALLED_ERROR):
					frappe.db.commit()
					summary["errored"] += 1
			elif r.get("deadline_at") and _expired(r.get("deadline_at"), now):
				if ts.mark_recovering(run_id, v, require_deadline_passed=True):
					frappe.db.commit()
					summary["parked"] += 1
			live_work = True

		elif state == "recovering":
			if _recovery_budget_exhausted(r, now):
				if ts.recover_errored(run_id, v):
					frappe.db.commit()
					summary["errored"] += 1
			elif r.get("dispatching_at") is None:
				if ts.recover_to_queued(run_id, v):
					frappe.db.commit()
					summary["reclaimed"] += 1
					live_work = True
			else:
				live_work = True  # pump reconcile adopts

		elif state == "finalizing":
			# R-13: the watchdog's ONLY legal action on a settled turn is
			# re-enqueueing finalize (never re-enter recovering).
			deps.enqueue_finalize(run_id, target)
			summary["finalize_requeued"] += 1

	if live_work:
		res = ensure_pump(target, deps=deps)
		if res.get("enqueued"):
			summary["revived"] += 1


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #


def _read_dispatch_row(run_id: str) -> dict | None:
	return frappe.db.get_value(
		TURN,
		run_id,
		[
			"run_id",
			"state",
			"version",
			"conversation",
			"assistant_message",
			"last_event_seq",
			"dispatch_payload",
		],
		as_dict=True,
	)


def _load_dispatch(turn: dict) -> dict:
	"""The prepare->pump handoff contract: prepare (WP-1d) writes the assembled
	prompt + created session into ``dispatch_payload`` JSON for the pump to
	``chat.send``. Keys the pump reads: ``session_key`` (required), ``message``
	(assembled prompt; falls back to the seed message content), ``thinking``,
	``attachments``. Robust to a missing/partial payload."""
	payload: dict = {}
	raw = turn.get("dispatch_payload") if turn else None
	if raw:
		try:
			parsed = json.loads(raw)
			if isinstance(parsed, dict):
				payload = parsed
		except Exception:
			payload = {}
	message = payload.get("message")
	if not message and turn.get("run_id"):
		seed = frappe.db.get_value(TURN, turn["run_id"], "seed_message")
		if seed:
			message = frappe.db.get_value(MSG, seed, "content") or ""
	return {
		"session_key": payload.get("session_key") or "",
		"message": message or "",
		"thinking": payload.get("thinking"),
		"attachments": payload.get("attachments"),
		"drained_note_ids": payload.get("drained_note_ids") or [],
	}


def _clear_agent_notes_on_ack(conversation: str, drained_note_ids) -> None:
	"""R-2: clear the agent-correction notes prepare folded into this turn's prompt,
	by id (airtight against overlapping turns), once delivery is PROVEN at the ack.
	Best-effort — never breaks the stream."""
	if not drained_note_ids:
		return
	try:
		from jarvis.chat import agent_notes

		agent_notes.clear(conversation, drained_note_ids)
	except Exception:
		frappe.log_error(title="pump.agent_notes_clear", message=frappe.get_traceback())


def _epoch_lost(ctx: PumpContext, run_id: str) -> bool:
	"""True iff the row's ``pump_epoch`` no longer matches this pump's epoch — the
	real lease-loss signal that distinguishes a takeover from a benign version
	drift on a 0-rows pump-owned CAS."""
	epoch = frappe.db.get_value(TURN, run_id, "pump_epoch")
	return epoch is None or int(epoch) != ctx.epoch


def _resync_version(run_id: str) -> int:
	return int(frappe.db.get_value(TURN, run_id, "version") or 0)


def turn_conversation(run_id: str) -> str:
	return frappe.db.get_value(TURN, run_id, "conversation")


def _local_active_session_keys(target: str) -> set[str]:
	"""Session keys the bench has an in-flight local turn for (used to subtract
	local runs from the gateway snapshot so only FOREIGN runs count as inflight)."""
	rows = frappe.db.sql(
		f"""SELECT dispatch_payload FROM `tab{TURN}`
		WHERE relay_target_id=%(t)s
		  AND state IN ('dispatching','streaming','terminal_observed')""",
		{"t": target},
		as_dict=True,
	)
	keys: set[str] = set()
	for r in rows:
		raw = r.get("dispatch_payload")
		if not raw:
			continue
		try:
			parsed = json.loads(raw)
			if isinstance(parsed, dict) and parsed.get("session_key"):
				keys.add(parsed["session_key"])
		except Exception:
			pass
	return keys


def _final_text(payload) -> str | None:
	payload = _coerce_payload(payload)
	if isinstance(payload, dict):
		return payload.get("text")
	return None


def _error_text(payload) -> str:
	payload = _coerce_payload(payload)
	if isinstance(payload, dict):
		return payload.get("error") or payload.get("state") or "The run ended with an error."
	return "The run ended with an error."


def _is_aborted_payload(terminal_kind, payload) -> bool:
	payload = _coerce_payload(payload)
	if isinstance(payload, dict):
		if payload.get("aborted") is True:
			return True
		if payload.get("state") == "aborted":
			return True
	return False


def _coerce_payload(payload):
	if isinstance(payload, str):
		try:
			return json.loads(payload)
		except Exception:
			return {"text": payload}
	return payload


def _json_or_none(raw):
	if not raw:
		return None
	try:
		return json.loads(raw)
	except Exception:
		return raw


def _in_list(values) -> str:
	return ",".join(f"'{v}'" for v in values)


def _older_than(dt, seconds: int) -> bool:
	if not dt:
		return False
	cutoff = frappe.utils.add_to_date(None, seconds=-seconds)
	return frappe.utils.get_datetime(dt) < frappe.utils.get_datetime(cutoff)


def _expired(dt, now) -> bool:
	if not dt:
		return False
	return frappe.utils.get_datetime(dt) < frappe.utils.get_datetime(now)


def _recovery_budget_exhausted(r: dict, now) -> bool:
	started = r.get("recovery_started_at")
	if not started:
		return False
	cutoff = frappe.utils.add_to_date(None, seconds=-RECOVERY_BUDGET_S)
	return frappe.utils.get_datetime(started) < frappe.utils.get_datetime(cutoff)


def _backoff_reconnect(attempt: int) -> None:
	"""Bounded backoff + reconnect attempt (D6 §6). Rolls back the failed txn,
	sleeps (capped), and probes the connection. Never spins: the caller counts
	consecutive failures and parks after DB_BACKOFF_ATTEMPTS."""
	try:
		frappe.db.rollback()
	except Exception:
		pass
	_sleep(min(DB_BACKOFF_BASE_S * (2 ** (attempt - 1)), DB_BACKOFF_CAP_S))
	try:
		frappe.connect()
	except Exception:
		pass


_AGE_OUT_REASON = "Waited too long in the queue and was cancelled. Please try again."
_STALLED_ERROR = "The response was interrupted and could not be recovered."


def _publish_cancelled(r: dict, reason: str) -> None:
	try:
		owner = frappe.db.get_value(CONV, r["conversation"], "owner")
		if owner:
			ts.publish_fenced(
				owner, "turn:cancelled", conversation_id=r["conversation"], run_id=r["run_id"], reason=reason
			)
	except Exception:
		pass


def _telemetry(event: str, **fields) -> None:
	try:
		from jarvis.chat.latency import get_logger

		parts = " ".join(f"{k}={v}" for k, v in fields.items())
		get_logger().info("pump %s %s", event, parts)
	except Exception:
		pass
