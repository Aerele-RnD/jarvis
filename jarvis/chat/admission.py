"""Phase-0 durable admission control (chat concurrency, WP-0).

The reported incident: when every in-flight chat slot is taken, a new send
becomes an invisible multi-minute RQ wait (or starves the site). Phase 0
kills that in the CURRENT transport - no pump, no WS/relay changes. A send
that cannot dispatch becomes a durable ``queued`` Jarvis Chat Turn with a
visible position and a cancel affordance; the legacy per-turn job path is
still the executor for admitted turns.

Design (binding: ../wp-d D2/D3 + PANEL-DISPOSITIONS OAR/SUX):

* MariaDB is the only authority. Every state change is a version-CAS
  (``WHERE state=X AND version=V``) whose affected-rows count is the success
  signal. Redis is never authoritative.
* The admission serializer takes ``SELECT ... FOR UPDATE`` on the per-shard
  ``Jarvis Relay Pump`` control row (OAR-1). Lock order (OAR-6, normative):
  control-row -> conversation -> turn -> message.
* Dual-signal active check (OAR-11): a conversation/shard is busy on a
  Turn-row ``dispatching`` OR a legacy fresh-``streaming`` assistant Message
  with no owning Turn row (the flag can flip mid-traffic, so legacy turns
  always coexist in Phase 0).
* Flag OFF (``jarvis_phase0_admission_enabled``, default off) => byte-
  identical legacy behavior: the gate is a cheap ``frappe.conf`` read that
  short-circuits before any Turn row or admission query. No schema traffic
  on the hot path.

Phase-0 simplifications (recorded for WP-1):

* ``relay_target_id`` is a single site-wide shard (``"default"``) - one
  gateway per bench. WP-1 derives real per-container ids; the schema keys on
  ``relay_target_id`` from day one so that is additive.
* ``dispatching`` covers the whole legacy job lifetime; the reservation IS
  the ``dispatching`` row itself, and ``reservation_expires_at`` guards only
  a crashed/lost enqueue.
"""

from __future__ import annotations

import json
import time

import frappe

from jarvis.chat.events import publish_to_user
from jarvis.permissions import require_jarvis_access

TURN = "Jarvis Chat Turn"
PUMP = "Jarvis Relay Pump"
MSG = "Jarvis Chat Message"
CONV = "Jarvis Conversation"

FLAG = "jarvis_phase0_admission_enabled"

# One gateway per bench in Phase 0 -> one site-wide admission shard.
DEFAULT_RELAY_TARGET = "default"

# Container main-lane ceiling (fleet agents.defaults.maxConcurrent, default 4).
DEFAULT_MAX_INFLIGHT = 4

# Accept-time overload guard (SUX-5): reject (no row) past this queued depth.
MAX_QUEUE_DEPTH = 25

# Sweep age-out (SUX-5): a queued turn older than this is system-cancelled.
QUEUED_MAX_AGE_S = 15 * 60

# Durable transcript marker copy (SUXI-4).
USER_CANCEL_REASON = "You cancelled this message before it was answered."
AGE_OUT_REASON = "Waited too long in the queue and was cancelled. Please try again."

# Crashed-enqueue guard: a dispatching turn whose enqueue was lost is returned
# to the queue after this many seconds. Deliberately >> the worker turn timeout
# (720s) so a legitimately long live turn is never reclaimed.
RESERVE_TTL_S = 900

# Legacy fresh-streaming window (mirrors api._INFLIGHT_FRESH_SECONDS).
_INFLIGHT_FRESH_SECONDS = 180

_ACTIVE_STATES = ("queued", "dispatching")


# --------------------------------------------------------------------------- #
# Flag / shard helpers
# --------------------------------------------------------------------------- #


def admission_enabled() -> bool:
	"""Cheap conf read (no DB). The single gate that keeps flag-OFF behavior
	byte-identical: callers short-circuit to the legacy dispatch path."""
	return bool(frappe.conf.get(FLAG))


def relay_target_id(conversation: str | None = None) -> str:
	"""The admission shard for a conversation. Phase 0: one site-wide shard."""
	return DEFAULT_RELAY_TARGET


def _max_inflight() -> int:
	try:
		v = int(frappe.conf.get("jarvis_site_max_inflight_turns") or 0)
	except (TypeError, ValueError):
		v = 0
	return v if v > 0 else DEFAULT_MAX_INFLIGHT


def _now() -> str:
	return frappe.utils.now()


def _fresh_cutoff() -> str:
	return frappe.utils.add_to_date(None, seconds=-_INFLIGHT_FRESH_SECONDS)


def _ensure_control_row(target: str) -> None:
	"""Get-or-create the shard control row OUTSIDE the serializing lock so the
	FOR UPDATE below always has a row to lock."""
	if frappe.db.exists(PUMP, target):
		return
	try:
		doc = frappe.get_doc({"doctype": PUMP, "relay_target_id": target})
		doc.flags.ignore_permissions = True
		doc.insert()
		frappe.db.commit()
	except frappe.DuplicateEntryError:
		frappe.db.rollback()


def _lock_shard(target: str) -> None:
	"""Serialize the credit read + admit decision across every sender and the
	promoter for this shard (OAR-1).

	Correctness under REPEATABLE READ: the inflight/queued COUNTs that follow
	MUST see data committed by whoever held this lock before us. InnoDB
	establishes a transaction's consistent-read snapshot at its first
	NON-locking read, so we commit here to start a FRESH transaction - making
	the ``SELECT ... FOR UPDATE`` the first statement. The lock then blocks
	until the prior holder commits, and the first non-locking COUNT after it
	takes its snapshot AFTER that commit (verified on patterntest under both
	READ COMMITTED and REPEATABLE READ). Callers commit their own durable work
	BEFORE entering admission, so this commit never drops pending state."""
	_ensure_control_row(target)
	frappe.db.commit()
	frappe.db.sql(
		f"SELECT name FROM `tab{PUMP}` WHERE name=%(t)s FOR UPDATE",
		{"t": target},
	)


def on_conversation_trash(doc, method=None) -> None:
	"""doc_events hook: cascade-delete a deleted conversation's Turn rows so a
	removed conversation never leaves ghost queued/dispatching rows in the
	admission shard. Best-effort - never blocks the trash."""
	try:
		frappe.db.delete(TURN, {"conversation": doc.name})
	except Exception:
		frappe.log_error(title="admission.on_conversation_trash", message=frappe.get_traceback())


def _lock_conversation(conversation: str) -> None:
	"""Second lock in the canonical order; defends per-conversation
	single-flight / seq (OAR-6)."""
	frappe.db.sql(
		f"SELECT name FROM `tab{CONV}` WHERE name=%(c)s FOR UPDATE",
		{"c": conversation},
	)


def _run_cas(sql: str, params: dict) -> int:
	"""Run a CAS UPDATE and return affected rows (read BEFORE commit, as
	turn_recovery._conditional_clear does - commit can reset the cursor)."""
	frappe.db.sql(sql, params)
	cursor = getattr(frappe.db, "_cursor", None)
	return int(cursor.rowcount) if cursor else 0


# --------------------------------------------------------------------------- #
# Dual-signal counting (OAR-11)
# --------------------------------------------------------------------------- #


def _turn_dispatching_count(target: str) -> int:
	return frappe.db.sql(
		f"SELECT COUNT(*) FROM `tab{TURN}` WHERE relay_target_id=%(t)s AND state='dispatching'",
		{"t": target},
	)[0][0]


def _turn_dispatching_count_by_class(target: str, turn_class: str) -> int:
	return frappe.db.sql(
		f"""SELECT COUNT(*) FROM `tab{TURN}`
		WHERE relay_target_id=%(t)s AND state='dispatching' AND turn_class=%(k)s""",
		{"t": target, "k": turn_class},
	)[0][0]


def _legacy_streaming_count(target: str) -> int:
	"""Conversations whose newest assistant Message is fresh-``streaming`` and
	have NO owning ``dispatching`` Turn row - turns that started before the flag
	flipped on. The ``NOT EXISTS`` de-dups only against a ``dispatching`` Turn
	(the row that actually OWNS a stream); a merely ``queued`` Turn owns no
	stream, so it must NOT hide a live legacy turn from the shard count (OARI-2 -
	previously ``state IN ('queued','dispatching')`` let the caller's own queued
	row zero out a coexisting legacy stream). Phase-0 shard is site-wide, so
	every conversation belongs to ``target``.

	Freshness is approximated from the assistant row's own ``modified`` (rather
	than the conversation's newest-of-any-role, as api._conversation_busy uses);
	a tool-heavy turn can look briefly stale, at worst under-counting by one
	during a flag flip - a transitional signal, documented."""
	return frappe.db.sql(
		f"""
		SELECT COUNT(*) FROM (
			SELECT m.conversation
			FROM `tab{MSG}` m
			INNER JOIN (
				SELECT conversation, MAX(seq) AS mseq
				FROM `tab{MSG}` WHERE role='assistant' GROUP BY conversation
			) latest ON latest.conversation = m.conversation AND latest.mseq = m.seq
			WHERE m.role='assistant' AND m.streaming=1 AND m.recovering=0
			  AND m.modified > %(fresh)s
			  AND NOT EXISTS (
					SELECT 1 FROM `tab{TURN}` t
					WHERE t.conversation = m.conversation AND t.state='dispatching'
			  )
		) x
		""",
		{"fresh": _fresh_cutoff()},
	)[0][0]


def _shard_inflight(target: str) -> int:
	"""Dual-signal inflight = Turn-row dispatching + legacy fresh-streaming."""
	return _turn_dispatching_count(target) + _legacy_streaming_count(target)


def _shard_queued_depth(target: str) -> int:
	return frappe.db.sql(
		f"SELECT COUNT(*) FROM `tab{TURN}` WHERE relay_target_id=%(t)s AND state='queued'",
		{"t": target},
	)[0][0]


def shard_overloaded(conversation: str | None = None) -> bool:
	"""Cheap unlocked pre-check so send_message can reject BEFORE inserting the
	user Message (avoids an orphan row). The authoritative overload check runs
	under the shard lock inside accept_or_queue."""
	return _shard_queued_depth(relay_target_id(conversation)) >= MAX_QUEUE_DEPTH


def _conv_has_other_active_turn(conversation: str, run_id: str) -> bool:
	"""Any other non-terminal (queued/dispatching) Turn row on this conversation."""
	return bool(
		frappe.db.sql(
			f"""SELECT 1 FROM `tab{TURN}`
			WHERE conversation=%(c)s AND name!=%(r)s AND state IN ('queued','dispatching')
			LIMIT 1""",
			{"c": conversation, "r": run_id},
		)
	)


def _conv_legacy_busy(conversation: str) -> bool:
	"""Legacy single-flight signal: a fresh streaming assistant row on this
	conversation (a turn that started before the flag flipped on, or a mid-flight
	self-hop). At every call site the *current* turn has no assistant row of its
	own yet (accept: the queued row was just inserted; promote: the candidate is
	queued), and a Turn-owned ``dispatching`` turn is already caught by
	``_conv_has_other_active_turn``, so a plain ``_conversation_busy`` is the
	correct legacy probe.

	OARI-2: the previous body subtracted "our own Turn row" via
	``_conv_has_other_active_turn(conversation, run_id="")`` - but the ``""``
	sentinel made ``name != ''`` exclude nothing, so the inner query counted the
	just-inserted queued row and always returned True, making this guard return
	False (dead) at BOTH call sites. Dropping the subtraction restores the
	OAR-11 coexistence interlock."""
	from jarvis.chat.api import _conversation_busy

	return _conversation_busy(conversation)


# --------------------------------------------------------------------------- #
# Position / publishing
# --------------------------------------------------------------------------- #


def _queued_ordered(target: str) -> list[dict]:
	return frappe.db.sql(
		f"""
		SELECT t.run_id, t.conversation, t.seed_message, t.turn_class, c.owner
		FROM `tab{TURN}` t
		INNER JOIN `tab{CONV}` c ON c.name = t.conversation
		WHERE t.relay_target_id=%(t)s AND t.state='queued'
		ORDER BY CASE t.turn_class WHEN 'interactive' THEN 0 ELSE 1 END,
		         t.enqueued_at ASC, t.run_id ASC
		""",
		{"t": target},
		as_dict=True,
	)


def _position_of(run_id: str, target: str) -> int | None:
	"""1-based rank among queued turns of the shard (interactive ahead of
	background, then FIFO). None when the run is not queued."""
	for i, r in enumerate(_queued_ordered(target), start=1):
		if r["run_id"] == run_id:
			return i
	return None


def _publish_queue_positions(target: str) -> None:
	"""Push queue:position to every queued turn's owner (bounded fan-out,
	SUX-2). Position labeled approximate in the UI ('~N ahead')."""
	for i, r in enumerate(_queued_ordered(target), start=1):
		try:
			publish_to_user(
				r["owner"],
				{
					"kind": "queue:position",
					"conversation_id": r["conversation"],
					"run_id": r["run_id"],
					"message_id": r["seed_message"],
					"position": i,
				},
			)
		except Exception:
			pass


def publish_action_confirmed(conversation: str, owner: str | None = None, run_id: str | None = None) -> None:
	"""SUX-3: on a synchronous confirm write, tell the user 'change saved'
	immediately - decoupled from the continuation turn, which then renders the
	standard queued chip. Best-effort. Flag-gated so flag-OFF stays byte-
	identical (no extra realtime event)."""
	if not admission_enabled():
		return
	try:
		user = owner or frappe.db.get_value(CONV, conversation, "owner")
		if not user:
			return
		publish_to_user(
			user,
			{
				"kind": "action:confirmed",
				"conversation_id": conversation,
				"run_id": run_id or "",
				"message": "Change saved",
			},
		)
	except Exception:
		pass


# --------------------------------------------------------------------------- #
# Telemetry (feeds C1-C6 later; existing latency channel + log lines)
# --------------------------------------------------------------------------- #


def _telemetry(event: str, **fields) -> None:
	try:
		from jarvis.chat.latency import get_logger

		parts = " ".join(f"{k}={v}" for k, v in fields.items())
		get_logger().info("admission %s %s", event, parts)
	except Exception:
		pass


# --------------------------------------------------------------------------- #
# accept_or_queue - the one chokepoint (all four _dispatch_turn callers)
# --------------------------------------------------------------------------- #


def accept_or_queue(
	*,
	conversation: str,
	run_id: str,
	seed_message: str | None,
	turn_class: str = "interactive",
	dispatch,
	dispatch_payload: dict | None = None,
	seed_content: str | None = None,
	exempt_overload: bool = False,
) -> dict:
	"""Admit or durably queue one turn. Returns one of:

	  {"ok": True, "dispatched": True,  "run_id", "queued_position": None}
	  {"ok": True, "dispatched": False, "run_id", "queued_position": N}
	  {"ok": False, "overloaded": True, "reason": <friendly copy>}

	``seed_message`` is the already-committed user Message (send/retry/orphan/
	macro all insert it before dispatch today - OAR-3's retry/orphan reuse is
	automatic here since no caller asks admission to insert). ``seed_content``
	+ ``seed_message=None`` is the WP-1 insert branch, wired but unused in
	Phase-0's legacy integration.

	``exempt_overload`` (SUXI-2 ruling): a confirm continuation is the follow-up
	of an ALREADY-committed write - it must never be rejected by the accept-time
	overload guard, only queued. The front-door senders (send/retry) keep the
	depth-25 backpressure; ``enqueue_continuation`` passes True so a continuation
	always queues with a visible position, never silently drops.

	``dispatch`` is a zero-arg callable that runs the legacy ``_dispatch_turn``
	for this turn; it is invoked ONLY on the admit path and ONLY after the
	admission txn commits."""
	target = relay_target_id(conversation)
	turn_class = turn_class if turn_class in ("interactive", "background") else "interactive"
	payload_json = json.dumps(dispatch_payload) if dispatch_payload else None

	_lock_shard(target)
	_lock_conversation(conversation)

	# OARI-11: everything below runs while holding the shard + conversation FOR
	# UPDATE locks. The two designed early-returns (overload reject, duplicate
	# replay) roll back explicitly before returning; an UNEXPECTED failure must
	# also release the locks immediately (not linger until request/job teardown),
	# so the whole locked section is guarded - rollback + re-raise (never mask).
	try:
		# Overload guard (SUX-5): authoritative check under the shard lock. No row.
		# A confirm continuation (exempt_overload) skips it - it always queues.
		if not exempt_overload and _shard_queued_depth(target) >= MAX_QUEUE_DEPTH:
			frappe.db.rollback()
			_telemetry("overload_reject", run_id=run_id, target=target)
			return {
				"ok": False,
				"overloaded": True,
				"reason": frappe._("The site is busy — please try again in a moment."),
			}

		# Seed the user Message if the caller delegated it (WP-1 branch; unused in
		# Phase-0 wiring because every legacy caller inserts before dispatch).
		if not seed_message:
			seq = (
				frappe.db.sql(
					f"SELECT MAX(seq) FROM `tab{MSG}` WHERE conversation=%(c)s", {"c": conversation}
				)[0][0]
				or 0
			) + 1
			msg = frappe.get_doc(
				{
					"doctype": MSG,
					"conversation": conversation,
					"seq": seq,
					"role": "user",
					"content": seed_content or "",
					"streaming": 0,
				}
			)
			msg.flags.ignore_permissions = True
			msg.insert()
			seed_message = msg.name

		# Insert the durable Turn row (idempotent on the run_id PK).
		try:
			turn = frappe.get_doc(
				{
					"doctype": TURN,
					"run_id": run_id,
					"conversation": conversation,
					"relay_target_id": target,
					"turn_class": turn_class,
					"state": "queued",
					"version": 0,
					"seed_message": seed_message,
					"dispatch_payload": payload_json,
					"enqueued_at": _now(),
				}
			)
			turn.flags.ignore_permissions = True
			turn.insert()
		except frappe.DuplicateEntryError:
			# Same send replayed (double-click / retry-after-ack): already accepted.
			frappe.db.rollback()
			return {
				"ok": True,
				"dispatched": False,
				"run_id": run_id,
				"duplicate": True,
				"queued_position": None,
			}

		# Admit decision: dispatch iff nothing else is live on this conversation
		# (single-flight) AND the shard has a free credit.
		conv_busy = _conv_has_other_active_turn(conversation, run_id) or _conv_legacy_busy(conversation)
		inflight = _shard_inflight(target)
		queue_depth_at_accept = _shard_queued_depth(target)
		admit = (not conv_busy) and (inflight < _max_inflight())

		if admit:
			affected = _run_cas(
				f"""UPDATE `tab{TURN}`
				SET state='dispatching', reserved=1, dispatching_at=%(now)s,
				    reservation_expires_at=%(exp)s, version=version+1
				WHERE name=%(r)s AND state='queued' AND version=0""",
				{
					"r": run_id,
					"now": _now(),
					"exp": frappe.utils.add_to_date(None, seconds=RESERVE_TTL_S),
				},
			)
			if affected != 1:
				# Lost a race to a concurrent promoter (should not happen under the
				# shard lock); fall back to queued and let promotion pick it up.
				admit = False

		frappe.db.commit()  # releases both locks; row is durable
	except Exception:
		frappe.db.rollback()  # release the FOR UPDATE locks on an unexpected failure
		raise

	_telemetry(
		"accept",
		run_id=run_id,
		target=target,
		turn_class=turn_class,
		admitted=int(admit),
		admission_queue_depth=queue_depth_at_accept,
	)

	if admit:
		# Enqueue the legacy turn job AFTER the durable commit (mirrors the
		# _dispatch_turn after_commit invariant).
		dispatch()
		return {"ok": True, "dispatched": True, "run_id": run_id, "queued_position": None}

	pos = _position_of(run_id, target)
	# A new queued turn changes nobody else's position, so no shard-wide
	# republish is needed here; the caller returns this turn's own position.
	return {"ok": True, "dispatched": False, "run_id": run_id, "queued_position": pos}


# --------------------------------------------------------------------------- #
# promote_next - weighted, background-floor, per-conversation single-flight
# --------------------------------------------------------------------------- #


def _cas_dispatch(run_id: str) -> bool:
	return (
		_run_cas(
			f"""UPDATE `tab{TURN}`
			SET state='dispatching', reserved=1, dispatching_at=%(now)s,
			    reservation_expires_at=%(exp)s, version=version+1
			WHERE name=%(r)s AND state='queued'""",
			{
				"r": run_id,
				"now": _now(),
				"exp": frappe.utils.add_to_date(None, seconds=RESERVE_TTL_S),
			},
		)
		== 1
	)


def _dispatch_promoted(row: dict) -> None:
	"""Re-dispatch a promoted queued turn via the legacy path, reconstructing
	attachments/context from the stored dispatch_payload."""
	from jarvis.chat import api

	kwargs = {
		"conversation_id": row["conversation"],
		"message_id": row["seed_message"],
		"run_id": row["run_id"],
		"enqueued_at_ms": int(time.time() * 1000),
	}
	extra = row.get("dispatch_payload")
	if extra:
		try:
			parsed = json.loads(extra)
			if isinstance(parsed, dict):
				if parsed.get("attachments"):
					kwargs["attachments"] = parsed["attachments"]
				if parsed.get("context"):
					kwargs["context"] = parsed["context"]
		except Exception:
			pass
	api._dispatch_turn(kwargs, interactive=(row.get("turn_class") == "interactive"))


def promote_next(target: str | None = None) -> int:
	"""Dispatch as many eligible queued turns as free credits allow. Weighted
	classes with a background floor of 1 (SUX-4a): when background turns are
	queued, interactive holds at most ``ceiling - 1`` credits. Per-conversation
	single-flight respected. Returns the number promoted. Best-effort - never
	raises into a terminal hook.

	OARI-4: flag-gated so a flag-OFF sweep never issues a FRESH dispatch. With
	the flag off, existing Turn rows still drain to terminal via the sweep's
	reconcile/age-out duties (which only settle/cancel existing rows), but no
	queued row is ever promoted onto a worker - disabling admission is a true
	kill switch for new dispatch, not just for new rows."""
	if not admission_enabled():
		return 0
	if target is None:
		target = DEFAULT_RELAY_TARGET
	promoted_rows: list[dict] = []
	try:
		_lock_shard(target)
		cap = _max_inflight()
		promoted_convs: set[str] = set()

		while _shard_inflight(target) < cap:
			candidate = _pick_next(target, cap, promoted_convs)
			if not candidate:
				break
			if _cas_dispatch(candidate["run_id"]):
				promoted_rows.append(candidate)
				promoted_convs.add(candidate["conversation"])
			# else lost the row; loop re-reads and tries the next candidate

		frappe.db.commit()  # release the shard lock before enqueueing
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="admission.promote_next", message=frappe.get_traceback())
		return 0

	for row in promoted_rows:
		try:
			wait_ms = _queue_wait_ms(row["run_id"])
			_dispatch_promoted(row)
			_telemetry("promote", run_id=row["run_id"], target=target, queue_wait_ms=wait_ms)
		except Exception:
			frappe.log_error(title="admission.promote dispatch", message=frappe.get_traceback())

	# Positions shifted for everyone still queued.
	try:
		_publish_queue_positions(target)
	except Exception:
		pass
	return len(promoted_rows)


def _pick_next(target: str, cap: int, promoted_convs: set[str]) -> dict | None:
	"""Choose the next queued turn to promote, honoring the background floor
	and per-conversation single-flight. Reads a small ordered batch and filters
	in Python (bounded work: at most a handful of credits per round)."""
	rows = frappe.db.sql(
		f"""
		SELECT t.run_id, t.conversation, t.seed_message, t.turn_class, t.dispatch_payload
		FROM `tab{TURN}` t
		WHERE t.relay_target_id=%(t)s AND t.state='queued'
		ORDER BY t.enqueued_at ASC, t.run_id ASC
		LIMIT 200
		""",
		{"t": target},
		as_dict=True,
	)

	def eligible(r: dict) -> bool:
		conv = r["conversation"]
		if conv in promoted_convs:
			return False
		if _conv_has_other_active_turn(conv, r["run_id"]):
			return False
		if _conv_legacy_busy(conv):
			return False
		return True

	interactive = next((r for r in rows if r["turn_class"] == "interactive" and eligible(r)), None)
	background = next((r for r in rows if r["turn_class"] == "background" and eligible(r)), None)

	if interactive and background:
		# Background floor: reserve at least one credit for background work when
		# any is queued - interactive may hold at most cap-1 credits. Only for
		# cap>=2: at cap 1 the floor "int_inflight >= cap-1" degenerates to ">= 0"
		# (always true) and would hand the SOLE credit to background over a
		# waiting interactive turn, inverting priority (OARI-8). With one credit
		# there is no room to reserve a floor, so interactive wins.
		int_inflight = _turn_dispatching_count_by_class(target, "interactive")
		if cap >= 2 and int_inflight >= cap - 1:
			return background
		return interactive
	return interactive or background


def _queue_wait_ms(run_id: str) -> int:
	row = frappe.db.get_value(TURN, run_id, ["enqueued_at", "dispatching_at"], as_dict=True)
	if not row or not row.get("enqueued_at") or not row.get("dispatching_at"):
		return 0
	try:
		delta = frappe.utils.get_datetime(row["dispatching_at"]) - frappe.utils.get_datetime(
			row["enqueued_at"]
		)
		return int(delta.total_seconds() * 1000)
	except Exception:
		return 0


# --------------------------------------------------------------------------- #
# Terminal hooks (worker + recovery) - CAS + best-effort promote
# --------------------------------------------------------------------------- #


def settle_turn(run_id: str, terminal_state: str, error: str | None = None) -> None:
	"""Mark a dispatching Turn terminal (done/errored/cancelled) then promote.
	Called AFTER the legacy terminal commit points, OUTSIDE the brittle region.
	Guarded by the flag so flag-OFF is byte-identical. Best-effort: never
	breaks the turn."""
	if not admission_enabled():
		return
	try:
		affected = _run_cas(
			f"""UPDATE `tab{TURN}`
			SET state=%(s)s, reserved=0, cancel_requested=0, done_at=%(now)s,
			    error=%(err)s, version=version+1
			WHERE name=%(r)s AND state='dispatching'""",
			{"s": terminal_state, "now": _now(), "err": (error or "")[:1000], "r": run_id},
		)
		target = frappe.db.get_value(TURN, run_id, "relay_target_id") or DEFAULT_RELAY_TARGET
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="admission.settle_turn", message=frappe.get_traceback())
		return
	if affected == 1:
		promote_next(target)


def settle_conversation_dispatching(
	conversation: str, terminal_state: str, error: str | None = None
) -> None:
	"""Recovery-path settle: close the (single-flight) dispatching Turn on this
	conversation. turn_recovery works off Message rows and has no run_id, so we
	settle by conversation - per-conversation single-flight makes this
	unambiguous. Best-effort + flag-gated."""
	if not admission_enabled():
		return
	try:
		run_id = frappe.db.get_value(
			TURN, {"conversation": conversation, "state": "dispatching"}, "name"
		)
	except Exception:
		run_id = None
	if run_id:
		settle_turn(run_id, terminal_state, error=error)


def mark_cancel_requested(conversation: str) -> None:
	"""stop_run hook: record cancel intent on the dispatching Turn (D2's
	dispatching->cancel-intent transition). NOT terminal - the legacy worker's
	aborted-terminal settles + promotes. Flag-gated, best-effort."""
	if not admission_enabled():
		return
	try:
		run_id = frappe.db.get_value(
			TURN, {"conversation": conversation, "state": "dispatching"}, "name"
		)
		if run_id:
			_run_cas(
				f"""UPDATE `tab{TURN}` SET cancel_requested=1, version=version+1
				WHERE name=%(r)s AND state='dispatching'""",
				{"r": run_id},
			)
			frappe.db.commit()
	except Exception:
		frappe.db.rollback()


# --------------------------------------------------------------------------- #
# Web endpoints - cancel + poll position
# --------------------------------------------------------------------------- #


def _assert_owner(conversation: str) -> str:
	owner = frappe.db.get_value(CONV, conversation, "owner")
	if owner is None:
		raise frappe.DoesNotExistError(f"conversation {conversation!r} not found")
	if owner != frappe.session.user and "System Manager" not in frappe.get_roles():
		raise frappe.PermissionError("not your conversation")
	return owner


@frappe.whitelist()
def cancel_queued_turn(run_id: str) -> dict:
	"""Owner-checked cancel of a queued turn: CAS queued->cancelled, publish
	turn:cancelled, republish positions. Frees no slot (a queued turn holds
	none) but renumbers the queue."""
	require_jarvis_access()
	row = frappe.db.get_value(
		TURN, run_id, ["conversation", "state", "relay_target_id", "seed_message"], as_dict=True
	)
	if not row:
		return {"ok": False, "reason": frappe._("This turn no longer exists.")}
	owner = _assert_owner(row["conversation"])
	affected = _run_cas(
		f"""UPDATE `tab{TURN}` SET state='cancelled', cancel_requested=1, done_at=%(now)s,
		version=version+1 WHERE name=%(r)s AND state='queued'""",
		{"r": run_id, "now": _now()},
	)
	frappe.db.commit()
	if affected != 1:
		return {"ok": False, "reason": frappe._("This turn already started or was cancelled.")}
	try:
		publish_to_user(
			owner,
			{
				"kind": "turn:cancelled",
				"conversation_id": row["conversation"],
				"run_id": run_id,
				"message_id": row["seed_message"],
				"reason": USER_CANCEL_REASON,
			},
		)
	except Exception:
		pass
	# SUXI-4: durable transcript marker so a later reload shows the send was
	# cancelled (not silently dropped).
	_write_cancel_marker(row["conversation"], USER_CANCEL_REASON)
	target = row["relay_target_id"] or DEFAULT_RELAY_TARGET
	# A cancel can free capacity indirectly (an over-cap conversation clears) -
	# best-effort promote + republish positions.
	promote_next(target)
	return {"ok": True, "run_id": run_id}


@frappe.whitelist()
def queue_position(run_id: str) -> dict:
	"""Poll-on-focus fallback for the queued chip. Owner-checked. Returns the
	current state and (when queued) the approximate position."""
	require_jarvis_access()
	row = frappe.db.get_value(
		TURN, run_id, ["conversation", "state", "relay_target_id"], as_dict=True
	)
	if not row:
		return {"ok": False, "reason": frappe._("This turn no longer exists.")}
	_assert_owner(row["conversation"])
	pos = _position_of(run_id, row["relay_target_id"] or DEFAULT_RELAY_TARGET) if row["state"] == "queued" else None
	return {"ok": True, "run_id": run_id, "state": row["state"], "position": pos}


@frappe.whitelist()
def active_turn_for_conversation(conversation: str) -> dict:
	"""SUXI-1 server-truth resync for the queued chip. Owner-checked. Returns the
	conversation's own QUEUED turn (the one the chip represents), if any, so a
	client that lost ``queuedTurn`` (reload, conversation switch, second tab, WS
	reconnect) can rebuild it from server truth - the same pattern as
	``resyncPendingConfirmations``. Conversations are owner-scoped, so this turn
	IS the caller's own. A ``dispatching`` turn is deliberately NOT returned here:
	loadConversation's existing streaming resume already shows its "Thinking…"
	state from the assistant placeholder; the chip is only for a not-yet-running
	queued turn. Returns ``{"ok": True, "active": None}`` when nothing is queued.
	The earliest-enqueued queued turn (position closest to 1) is reported."""
	require_jarvis_access()
	_assert_owner(conversation)
	row = frappe.db.get_value(
		TURN,
		{"conversation": conversation, "state": "queued"},
		["run_id", "seed_message", "relay_target_id"],
		as_dict=True,
		order_by="enqueued_at asc",
	)
	if not row:
		return {"ok": True, "active": None}
	pos = _position_of(row["run_id"], row["relay_target_id"] or DEFAULT_RELAY_TARGET)
	return {
		"ok": True,
		"active": {
			"run_id": row["run_id"],
			"state": "queued",
			"message_id": row["seed_message"],
			"position": pos,
		},
	}


def _write_cancel_marker(conversation: str, reason: str) -> None:
	"""SUXI-4: leave a durable assistant marker Message when a queued turn is
	cancelled (user-initiated or system age-out) so a later reload shows WHY the
	send has no reply - indistinguishable otherwise from a silently dropped send.
	Reuses the error-card pattern (``error`` field) so the transcript renders it
	as a card with a Retry affordance. seq is allocated under the conversation
	FOR UPDATE lock (R-9 discipline) so it never collides with a concurrent
	writer on the same conversation. Best-effort - never blocks the cancel."""
	try:
		_lock_conversation(conversation)
		seq = (
			frappe.db.sql(
				f"SELECT MAX(seq) FROM `tab{MSG}` WHERE conversation=%(c)s", {"c": conversation}
			)[0][0]
			or 0
		) + 1
		marker = frappe.get_doc(
			{
				"doctype": MSG,
				"conversation": conversation,
				"seq": seq,
				"role": "assistant",
				"content": "",
				"streaming": 0,
				"error": reason,
			}
		)
		marker.flags.ignore_permissions = True
		marker.insert()
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="admission._write_cancel_marker", message=frappe.get_traceback())


# --------------------------------------------------------------------------- #
# Sweep (scheduler backstop) - reservation expiry, age-out, Turn/Message reconcile
# --------------------------------------------------------------------------- #


def sweep() -> dict:
	"""Backstop tick (hooks cron). Runs whenever any non-terminal Turn rows
	exist (so a flag flip-off still gets its rows reconciled), else a cheap
	no-op. Three duties:

	  1. Reservation expiry: a dispatching turn whose enqueue was lost (expired
	     reservation, no live assistant activity of ITS OWN) returns to queued;
	     a stopped turn (cancel_requested) is cancelled, not re-queued (OARI-6).
	  2. Turn-vs-Message reconcile: a dispatching turn whose OWN assistant
	     Message (seq > seed.seq) already settled/errored is closed to match
	     Message truth; an orphaned turn whose own placeholder is a stale
	     streaming row past a lost worker (reservation expired) is closed errored
	     to free its credit (OARI-1/OARI-3). The legacy transport is the executor.
	  3. Age-out: a queued turn older than QUEUED_MAX_AGE_S is system-cancelled
	     with a recorded reason.

	Then re-promote and republish positions. Never raises.

	Flag-OFF drain semantics (OARI-4): the three settle/reclaim/age-out duties
	still run so residual rows from a flag flip-off DRAIN to terminal, but
	``promote_next`` is flag-gated so NO fresh dispatch is issued while the flag
	is off. Disabling admission therefore stops all new dispatch immediately;
	the leftover rows settle themselves out. accept_or_queue is never reached
	with the flag off (all four callers gate on ``admission_enabled`` first), so
	no NEW rows are created - the flag-OFF hot path stays byte-identical."""
	summary = {"reclaimed": 0, "reconciled": 0, "aged_out": 0, "promoted": 0}
	try:
		open_count = frappe.db.sql(
			f"SELECT COUNT(*) FROM `tab{TURN}` WHERE state IN ('queued','dispatching')"
		)[0][0]
	except Exception:
		return summary
	if not open_count:
		return summary

	targets: set[str] = set()
	try:
		summary["reconciled"] += _sweep_reconcile(targets)
		summary["reclaimed"] += _sweep_reservations(targets)
		summary["aged_out"] += _sweep_age_out(targets)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="admission.sweep", message=frappe.get_traceback())

	for target in targets or {DEFAULT_RELAY_TARGET}:
		try:
			summary["promoted"] += promote_next(target)
		except Exception:
			pass
	return summary


def _sweep_reconcile(targets: set[str]) -> int:
	"""Close dispatching turns whose OWN assistant Message (seq > seed.seq)
	already settled/errored, or whose own placeholder is a stale streaming row
	past a lost worker. Message truth wins.

	OARI-1: the reconcile is scoped to THIS turn's output (an assistant row
	strictly after the turn's seed user row). Keying on the conversation's newest
	assistant of ANY turn silently CLOSED a just-sent later turn as 'done' the
	moment a sweep landed while its own placeholder had not been written yet -
	losing a real user send with no reply and no error, and (in the placeholder
	window) over-promoting into same-session double-occupancy. When the turn has
	produced NOTHING of its own, reconcile leaves it: a lost enqueue is reclaimed
	by _sweep_reservations, a live turn mid-placeholder is untouched.

	OARI-3: an orphaned dispatching turn whose only OWN assistant is a stale
	streaming placeholder (worker provably dead - reservation past the 900s TTL,
	well beyond the 720s worker cap) is closed errored so a post-deploy batch of
	orphans frees its shard credits instead of pinning them for extra cycles."""
	rows = frappe.db.sql(
		f"""
		SELECT t.run_id, t.conversation, t.relay_target_id, t.seed_message,
		       t.reservation_expires_at
		FROM `tab{TURN}` t
		WHERE t.state='dispatching'
		""",
		as_dict=True,
	)
	now = _now()
	fresh = _fresh_cutoff()
	closed = 0
	for r in rows:
		# THIS turn's own latest assistant (strictly after its seed user row).
		latest = frappe.db.sql(
			f"""SELECT streaming, recovering, error, modified FROM `tab{MSG}`
			WHERE conversation=%(c)s AND role='assistant'
			  AND seq > (SELECT seq FROM `tab{MSG}` WHERE name=%(seed)s)
			ORDER BY seq DESC LIMIT 1""",
			{"c": r["conversation"], "seed": r["seed_message"]},
			as_dict=True,
		)
		if not latest:
			# Nothing of its OWN yet - a PRIOR turn's assistant is NOT this turn.
			# Do NOT close it (that was the OARI-1 silent-loss bug); leave it for
			# reservation-reclaim or a live placeholder to arrive.
			continue
		a = latest[0]
		if a.get("recovering"):
			continue  # parked for background recovery - recovery finalize settles it
		if a.get("streaming"):
			# Own placeholder still streaming. Close ONLY a provably-dead orphan
			# (reservation expired AND the placeholder has gone stale past the
			# freshness window); a live or not-yet-expired turn is left alone so a
			# live long turn is never false-closed (OARI-3).
			exp = r.get("reservation_expires_at")
			expired = bool(exp) and frappe.utils.get_datetime(exp) < frappe.utils.get_datetime(now)
			mod = a.get("modified")
			stale = bool(mod) and frappe.utils.get_datetime(mod) < frappe.utils.get_datetime(fresh)
			if expired and stale:
				state = "errored"
			else:
				continue
		else:
			# Settled or errored assistant row but the Turn is still dispatching.
			state = "errored" if a.get("error") else "done"
		affected = _run_cas(
			f"""UPDATE `tab{TURN}` SET state=%(s)s, reserved=0, done_at=%(now)s,
			was_recovered=1, version=version+1 WHERE run_id=%(r)s AND state='dispatching'""",
			{"s": state, "now": now, "r": r["run_id"]},
		)
		if affected == 1:
			closed += 1
			targets.add(r["relay_target_id"] or DEFAULT_RELAY_TARGET)
	if closed:
		frappe.db.commit()
	return closed


def _sweep_reservations(targets: set[str]) -> int:
	"""Reclaim dispatching turns whose reservation expired AND that never
	produced assistant activity OF THEIR OWN (seq > seed.seq) - a lost/crashed
	enqueue - returning them to queued for a fresh promotion.

	OARI-1: scoped to this turn's output (seq > seed.seq). The old ``role=
	'assistant' LIMIT 1`` matched ANY assistant row on the conversation, so on a
	multi-turn conversation a lost enqueue was NEVER reclaimed (an earlier turn's
	assistant made ``has_assistant`` true) - the reclaim path the brief promises
	only worked on first-turn conversations.

	OARI-6: a stopped turn (``cancel_requested``) whose worker died before making
	a placeholder is CANCELLED (terminal), never re-dispatched - a turn the user
	explicitly stopped must not run again."""
	rows = frappe.db.sql(
		f"""
		SELECT t.run_id, t.conversation, t.relay_target_id, t.seed_message,
		       t.cancel_requested
		FROM `tab{TURN}` t
		WHERE t.state='dispatching' AND t.reservation_expires_at IS NOT NULL
		  AND t.reservation_expires_at < %(now)s
		""",
		{"now": _now()},
		as_dict=True,
	)
	reclaimed = 0
	for r in rows:
		has_own_assistant = frappe.db.sql(
			f"""SELECT 1 FROM `tab{MSG}`
			WHERE conversation=%(c)s AND role='assistant'
			  AND seq > (SELECT seq FROM `tab{MSG}` WHERE name=%(seed)s) LIMIT 1""",
			{"c": r["conversation"], "seed": r["seed_message"]},
		)
		if has_own_assistant:
			continue  # reconcile owns this case
		if int(r.get("cancel_requested") or 0):
			# OARI-6: stopped-then-crashed - cancel it, never re-dispatch.
			affected = _run_cas(
				f"""UPDATE `tab{TURN}` SET state='cancelled', reserved=0, done_at=%(now)s,
				was_recovered=1, version=version+1
				WHERE run_id=%(r)s AND state='dispatching'
				  AND reservation_expires_at IS NOT NULL AND reservation_expires_at < %(now)s""",
				{"r": r["run_id"], "now": _now()},
			)
			if affected == 1:
				reclaimed += 1
				targets.add(r["relay_target_id"] or DEFAULT_RELAY_TARGET)
			continue
		affected = _run_cas(
			f"""UPDATE `tab{TURN}`
			SET state='queued', reserved=0, dispatching_at=NULL,
			    reservation_expires_at=NULL, was_recovered=1, version=version+1
			WHERE run_id=%(r)s AND state='dispatching'
			  AND reservation_expires_at IS NOT NULL AND reservation_expires_at < %(now)s""",
			{"r": r["run_id"], "now": _now()},
		)
		if affected == 1:
			reclaimed += 1
			targets.add(r["relay_target_id"] or DEFAULT_RELAY_TARGET)
	if reclaimed:
		frappe.db.commit()
	return reclaimed


def _sweep_age_out(targets: set[str]) -> int:
	"""System-cancel queued turns older than QUEUED_MAX_AGE_S with a recorded
	reason + publish (SUX-5)."""
	cutoff = frappe.utils.add_to_date(None, seconds=-QUEUED_MAX_AGE_S)
	rows = frappe.db.sql(
		f"""
		SELECT t.run_id, t.conversation, t.relay_target_id, t.seed_message, c.owner
		FROM `tab{TURN}` t INNER JOIN `tab{CONV}` c ON c.name = t.conversation
		WHERE t.state='queued' AND t.enqueued_at IS NOT NULL AND t.enqueued_at < %(cut)s
		""",
		{"cut": cutoff},
		as_dict=True,
	)
	reason = AGE_OUT_REASON
	cancelled = 0
	for r in rows:
		affected = _run_cas(
			f"""UPDATE `tab{TURN}` SET state='cancelled', cancel_reason=%(reason)s,
			done_at=%(now)s, version=version+1 WHERE run_id=%(r)s AND state='queued'""",
			{"reason": reason, "now": _now(), "r": r["run_id"]},
		)
		if affected != 1:
			continue
		# Make the cancel durable BEFORE the side-effects: _write_cancel_marker
		# runs its own txn (and rolls back on failure), which would otherwise
		# undo an uncommitted CAS.
		frappe.db.commit()
		cancelled += 1
		targets.add(r["relay_target_id"] or DEFAULT_RELAY_TARGET)
		try:
			publish_to_user(
				r["owner"],
				{
					"kind": "turn:cancelled",
					"conversation_id": r["conversation"],
					"run_id": r["run_id"],
					"message_id": r["seed_message"],
					"reason": reason,
				},
			)
		except Exception:
			pass
		# SUXI-4: durable transcript marker (survives the next-morning reload).
		_write_cancel_marker(r["conversation"], reason)
	return cancelled
