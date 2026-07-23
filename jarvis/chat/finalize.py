"""WP-1d — the finalize (enrichment) runner off the effect ledger (Relay Pump).

Short RQ job enqueued by settlement (D3 S6) and re-enqueued by the pump watchdog
for a ``finalizing`` turn (R-13). It drives the turn's owed ``Jarvis Turn Effect``
rows — the closed set settlement fixed atomically (OAR-9) — to ``done``, then flips
``finalizing -> done`` and publishes ``message:enriched`` (SUX-7).

Every effect is idempotent per ``(turn, effect_name)`` (the ledger's composite PK)
and best-effort: a failing effect is retried on the next finalize cycle and
FORCE-DONE after ``FINALIZE_MAX_ATTEMPTS=3`` (turn_state.claim_effect), so a
permanently-broken enrichment can NEVER strand a settled turn — the turn ALWAYS
reaches ``done`` (D2 §1a). Finalize NEVER errors a settled turn (row 13 is the
explicit NEVER transition): an errored/cancelled terminal runs only its
macro-advance + telemetry hooks and stays terminal (no finalize_done).

Ownership (WP-D / D1 Stage 4): canvas/rich outputs (#43/#44), chat-ask
materialize (#45), macro advance + app-learning (#46/#47), auto-title (#50), wiki
nudge (#51), USAGE (#42, R-4: the ≤4.5s gateway poll runs HERE off the critical
path, with a (turn_id) idempotency guard so a replay can't double-count the soft
cap), and telemetry (#49). ``run:end`` is settlement's (S5); this publishes
``message:enriched`` at completion.

Wired as the pump's ``enqueue_finalize`` seam target
(``jarvis.chat.finalize.run_finalize``); tests drive it in-process.
"""

from __future__ import annotations

import json
import time

import frappe

from jarvis.chat import turn_state as ts

TURN = "Jarvis Chat Turn"
MSG = "Jarvis Chat Message"
CONV = "Jarvis Conversation"

# Canonical run order. Effects NOT in a turn's required set claim as "done"
# (no ledger row) and are skipped — so a single ordered pass covers both the
# relay:final full set and the errored/cancelled minimal set.
_EFFECT_ORDER = (
	"rich_outputs",
	"chat_asks",
	"macro_advance",
	"auto_title",
	"wiki_nudge",
	"usage",
	"telemetry_flush",
)


def run_finalize(run_id: str, relay_target_id: str | None = None, deps=None) -> dict:
	"""Run every pending enrichment effect for ``run_id`` (idempotent, force-done at
	3), then finalize the turn to ``done`` (success path). Safe to re-run: a done
	turn is a no-op; a partially-failed run leaves the rest pending for the next
	cycle. Never raises out (best-effort)."""
	turn = frappe.db.get_value(
		TURN,
		run_id,
		["state", "conversation", "assistant_message", "seed_message", "dispatch_payload"],
		as_dict=True,
	)
	if not turn:
		return {"ok": False, "reason": "no turn"}
	state = turn["state"]
	if state == "done":
		return {"ok": True, "already_done": True}
	# Only settled turns own an effect ledger. A turn still pre-terminal (queued/
	# preparing/.../streaming/terminal_observed) has nothing to enrich yet.
	if state not in ("finalizing", "errored", "cancelled"):
		return {"ok": False, "reason": f"not settled ({state})"}

	conversation = turn["conversation"]
	owner = frappe.db.get_value(CONV, conversation, "owner")
	errored = state in ("errored", "cancelled")
	ctx = _Ctx(
		run_id=run_id,
		turn=turn,
		conversation=conversation,
		owner=owner,
		errored=errored,
		payload=_load_payload(turn),
	)

	ran = 0
	for name in _EFFECT_ORDER:
		outcome = ts.claim_effect(run_id, name)
		# Persist the attempt increment / force-done so a crash mid-effect still
		# counts toward the force-done budget (never an infinite retry loop).
		frappe.db.commit()
		if outcome != "attempt":
			continue  # 'done' (not required / already applied) or 'force_done' (budget) — skip
		try:
			_RUNNERS[name](ctx)
			ts.complete_effect(run_id, name)
			frappe.db.commit()
			ran += 1
		except Exception:
			# Leave the row PENDING (rolls back this effect's uncommitted work, e.g.
			# the usage guard CAS); the watchdog re-enqueues finalize, and
			# claim_effect force-dones it after 3 attempts. NEVER errors the turn.
			try:
				frappe.db.rollback()
			except Exception:
				pass
			frappe.log_error(title=f"finalize.{name}", message=frappe.get_traceback())

	# Success path only: flip finalizing -> done once every required effect is done
	# (force-done counts as done), then publish message:enriched (SUX-7). An
	# errored/cancelled turn is already terminal — no finalize_done, no un-settling.
	done = False
	if state == "finalizing" and ts.all_required_effects_done(run_id):
		v = int(frappe.db.get_value(TURN, run_id, "version") or 0)
		if ts.finalize_done(run_id, v):
			frappe.db.commit()
			done = True
			if owner and turn.get("assistant_message"):
				ts.publish_fenced(
					owner,
					"message:enriched",
					conversation_id=conversation,
					run_id=run_id,
					message_id=turn["assistant_message"],
				)
	return {"ok": True, "ran": ran, "done": done, "state": state}


class _Ctx:
	__slots__ = ("conversation", "errored", "owner", "payload", "run_id", "turn")

	def __init__(self, *, run_id, turn, conversation, owner, errored, payload):
		self.run_id = run_id
		self.turn = turn
		self.conversation = conversation
		self.owner = owner
		self.errored = errored
		self.payload = payload


def _load_payload(turn: dict) -> dict:
	raw = turn.get("dispatch_payload")
	if not raw:
		return {}
	try:
		parsed = json.loads(raw)
		return parsed if isinstance(parsed, dict) else {}
	except Exception:
		return {}


def _turn_start_ms(ctx: _Ctx) -> int:
	"""Epoch-ms baseline for scoping this turn's generated-image files (#44).
	prepare stashes it; fall back to the turn's dispatching_at, then now-ish."""
	ms = ctx.payload.get("turn_start_ms")
	if ms:
		try:
			return int(ms)
		except (TypeError, ValueError):
			pass
	dt = frappe.db.get_value(TURN, ctx.run_id, "dispatching_at")
	if dt:
		try:
			return int(frappe.utils.get_datetime(dt).timestamp() * 1000)
		except Exception:
			pass
	return int(time.time() * 1000)


# --------------------------------------------------------------------------- #
# Effect runners (D1 Stage 4). Each is best-effort + idempotent by construction.
# --------------------------------------------------------------------------- #


def _effect_rich_outputs(ctx: _Ctx) -> None:
	am = ctx.turn.get("assistant_message")
	if not am:
		return
	from jarvis.chat import turn_handler

	turn_handler.persist_rich_outputs(am, ctx.conversation, ctx.owner, ctx.run_id, _turn_start_ms(ctx))


def _effect_chat_asks(ctx: _Ctx) -> None:
	# A final reply carrying a ```jarvis-ask fence surfaces on the Approval Board.
	# Skipped for an errored/cancelled turn (a partial fence is not a real ask).
	if ctx.errored:
		return
	am = ctx.turn.get("assistant_message")
	if not am:
		return
	final = frappe.db.get_value(MSG, am, ["content", "error"], as_dict=True) or {}
	if final.get("error"):
		return
	from jarvis.chat import chat_asks

	chat_asks.materialize_from_turn(ctx.conversation, final.get("content") or "")


def _effect_macro_advance(ctx: _Ctx) -> None:
	# Macro chaining + app-learning turn hook (D1 #46/#47). Runs on BOTH success and
	# error/cancel (the macro must advance/abort either way — matches legacy
	# _advance_macro). Each has its own per-run redis lock (idempotent).
	from jarvis.chat import macros

	macros.advance_after_turn(ctx.conversation, errored=ctx.errored)
	from jarvis.learning import app_analysis

	app_analysis.on_turn_end(ctx.conversation, errored=ctx.errored)


def _effect_auto_title(ctx: _Ctx) -> None:
	# Managed-only (pump is managed). Job re-gates on title=="New chat".
	from jarvis import selfhost

	if selfhost.is_self_hosted():
		return
	from jarvis.chat import title as title_mod

	title_mod.enqueue_autotitle(ctx.conversation, ctx.owner)


def _effect_wiki_nudge(ctx: _Ctx) -> None:
	from jarvis import selfhost

	if selfhost.is_self_hosted():
		return
	from jarvis.chat import wiki as wiki_mod

	if not wiki_mod.wiki_enabled():
		return
	# Nudge goes to the turn's actual sender (chat_user), not conv.owner — they
	# diverge in shared conversations. prepare stashes chat_user; fall back to owner.
	chat_user = ctx.payload.get("chat_user") or ctx.owner
	frappe.enqueue(
		"jarvis.chat.wiki.maybe_nudge",
		queue="short",
		conversation_id=ctx.conversation,
		user=chat_user,
		run_id=ctx.run_id,
	)


def _effect_usage(ctx: _Ctx) -> None:
	# R-4 / §10.7: the ≤4.5s gateway poll runs HERE (off the critical path), and the
	# accrual is (turn_id)-idempotent. The guard CAS lives in THIS uncommitted txn:
	#   * poll/record succeeds -> record_turn_usage commits the guard + counters
	#     together (at-most-once);
	#   * poll raises -> the caller rolls back, UNDOING the guard, so the effect
	#     retries next cycle (never a silent permanent loss on a transient hiccup);
	#   * a later finalize replay after a committed accrual sees usage_recorded=1
	#     and no-ops (never double-count the soft monthly cap).
	won = ts._run_cas(
		f"UPDATE `tab{TURN}` SET usage_recorded=1 WHERE name=%(r)s AND usage_recorded=0",
		{"r": ctx.run_id},
	)
	if won != 1:
		return  # already recorded — never double-count
	if ctx.errored:
		# An errored/cancelled turn accrues no usage; the guard commits with the
		# effect (record only on a real completed run). Leave counters untouched.
		return
	session_key = ctx.payload.get("session_key") or frappe.db.get_value(CONV, ctx.conversation, "session_key")
	if not session_key:
		return
	from jarvis.chat import openclaw_session_pool
	from jarvis.chat import usage as _usage

	settings = frappe.get_cached_doc("Jarvis Settings")
	gateway_url = (settings.agent_url or "").replace("http://", "ws://").replace("https://", "wss://")
	with openclaw_session_pool.checkout(gateway_url) as sess:
		row = _usage.fetch_fresh_session_row(sess, session_key)
	# record_turn_usage commits internally (guard + counters atomic) or no-ops
	# without committing (no fresh row) — either way NEVER raises.
	_usage.record_turn_usage(session_key, row)


def _effect_telemetry(ctx: _Ctx) -> None:
	# Latency summary + turn telemetry (customization discovery). Best-effort.
	try:
		from jarvis.chat.latency import get_logger

		get_logger().info("pump turn_finalized run_id=%s errored=%d", ctx.run_id, int(ctx.errored))
	except Exception:
		pass
	try:
		from jarvis import telemetry

		telemetry.emit_turn(ctx.conversation, ctx.run_id, 0)
	except Exception:
		pass


_RUNNERS = {
	"rich_outputs": _effect_rich_outputs,
	"chat_asks": _effect_chat_asks,
	"macro_advance": _effect_macro_advance,
	"auto_title": _effect_auto_title,
	"wiki_nudge": _effect_wiki_nudge,
	"usage": _effect_usage,
	"telemetry_flush": _effect_telemetry,
}
