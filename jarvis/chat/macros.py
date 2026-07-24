"""Macro execution engine.

A macro (``Jarvis Macro``) is an ordered list of prompts. Running one creates a
fresh conversation and executes each prompt as its own agent turn, chained
server-side: after a turn's ``run:end`` (or an error) the chaining hook in
``jarvis.chat.turn_handler`` calls :func:`advance_after_turn`, which enqueues the
next step. Because the steps run as turns in one conversation they share the
openclaw session, so context accumulates across the macro — and the run survives
a closed browser tab (unlike a frontend-driven loop).

State lives in ``Jarvis Macro Run`` (``current_step`` = 1-based index of the step
last started; ``status`` in queued/running/completed/failed/stopped). Progress is
pushed to the owner's realtime channel as ``macro:progress`` / ``macro:done``.
"""

import frappe
from frappe import _

from jarvis.chat.events import publish_to_user

MACRO = "Jarvis Macro"
RUN = "Jarvis Macro Run"
CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"

# CDX-19: how many capacity-resume cron cycles a step may be deferred before the run
# fails honestly. The resume cron runs every 5 min, so ~20 attempts ≈ 100 min of sustained
# site overload before giving up — far longer than any real transient backpressure.
_MAX_CAPACITY_ATTEMPTS = 20


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #
def run_macro(macro_name: str, *, trigger: str = "manual") -> dict:
	"""Start a macro: create a fresh conversation, a Macro Run, and enqueue the
	first step. Returns ``{ok, data:{macro_run, conversation}}``. ``trigger`` is
	``manual`` (user clicked Run) or ``scheduled`` (the cron)."""
	doc = frappe.get_doc(MACRO, macro_name)
	doc.check_permission("read")  # owner-gate: get_doc alone doesn't enforce if_owner
	steps = doc.steps or []
	if not steps:
		frappe.throw(_("This macro has no steps."))
	if trigger == "scheduled" and not doc.enabled:
		return {"ok": False, "reason": "macro disabled"}
	if (doc.merge_status or "") == "pending" and trigger != "scheduled":
		frappe.throw(_("Still summarizing this macro — try again in a few seconds."))
	owner = doc.owner
	# A stored merged prompt (the background LLM summary) runs as ONE turn
	# instead of chaining the steps — the steps stay as the editable source
	# the summary was made from. merge_status "failed"/unmergeable falls back
	# to the sequence (an unmergeable sequence NEEDS its checkpoints).
	merged = (doc.merged_prompt or "").strip()
	total = 1 if merged else len(steps)

	# Fresh conversation titled after the macro, seeded with an intro so the
	# transcript reads as a self-contained run.
	conv = frappe.get_doc({"doctype": CONV, "title": doc.macro_name[:140], "status": "Active"})
	conv.flags.ignore_permissions = True
	conv.insert()
	intro = frappe.get_doc(
		{
			"doctype": MSG,
			"conversation": conv.name,
			"seq": 1,
			"role": "assistant",
			"content": (
				f"▶ Running macro **{doc.macro_name}** — summarized prompt."
				if merged
				else f"▶ Running macro **{doc.macro_name}** — {len(steps)} step(s)."
			),
		}
	)
	intro.flags.ignore_permissions = True
	intro.insert()

	run = frappe.get_doc(
		{
			"doctype": RUN,
			"macro": doc.name,
			"conversation": conv.name,
			"status": "running",
			"current_step": 0,
			"total_steps": total,
			"trigger": trigger,
			"started_at": frappe.utils.now(),
		}
	)
	run.flags.ignore_permissions = True
	run.insert()

	# When run on behalf of another user (the scheduler runs as the owner, but be
	# defensive), hand ownership of the owner-scoped rows over so they're visible
	# to the intended user only.
	if owner != frappe.session.user:
		for dt, name in ((CONV, conv.name), (MSG, intro.name), (RUN, run.name)):
			frappe.db.set_value(dt, name, "owner", owner, update_modified=False)
	frappe.db.commit()

	# Scheduled runs surface via the proactive "conversation:new" toast; manual
	# runs are navigated to directly by the SPA, so no toast there.
	if trigger == "scheduled":
		publish_to_user(
			owner,
			{
				"kind": "conversation:new",
				"conversation_id": conv.name,
				"title": doc.macro_name[:140],
				"preview": f"Scheduled macro: {doc.macro_name}",
			},
		)

	if merged:
		_run_merged(run, doc, merged)
	else:
		_run_step(run, doc, 0)
	return {"ok": True, "data": {"macro_run": run.name, "conversation": conv.name}}


def advance_after_turn(conversation_id: str, *, errored: bool) -> None:
	"""Chaining hook, called from ``turn_handler`` after every terminal turn
	outcome. If the conversation belongs to a ``running`` Macro Run, advance it:
	enqueue the next step, or finish. If it's a macro's background SUMMARIZE
	turn, apply the summary to the macro. No-op for normal (non-macro) chats.

	Best-effort: never raises (a macro bug must not strand a normal turn).
	Serialized + idempotent via a per-run redis lock + the ``current_step`` guard
	so a re-delivered event / RQ retry can't double-advance."""
	try:
		_apply_merge_after_turn(conversation_id, errored=errored)
	except Exception:
		frappe.log_error(title="jarvis macro merge-apply failed", message=frappe.get_traceback())
	try:
		run_name = frappe.db.get_value(RUN, {"conversation": conversation_id, "status": "running"}, "name")
		if not run_name:
			return
		from jarvis._redis_lock import redis_lock

		with redis_lock(f"jarvis_macro_run:{run_name}", timeout_s=60, blocking_timeout_s=10.0) as acquired:
			if not acquired:
				return
			run = frappe.get_doc(RUN, run_name)
			if run.status != "running":  # stopped mid-flight, or already advanced
				return
			macro_doc = frappe.get_doc(MACRO, run.macro)
			steps = macro_doc.steps or []
			total = min(run.total_steps or len(steps), len(steps))

			if errored and macro_doc.stop_on_error:
				_finish(run, "failed", error=f"Step {run.current_step} failed.")
				_publish_done(run, macro_doc, "failed")
				return

			next_index = run.current_step or 0  # 0-based index of the next step
			if next_index >= total:
				_finish(run, "completed")
				_publish_done(run, macro_doc, "completed")
				return

			_run_step(run, macro_doc, next_index)
	except Exception:
		frappe.log_error(title="jarvis macro advance failed", message=frappe.get_traceback())


def _apply_merge_after_turn(conversation_id: str, *, errored: bool) -> None:
	"""When a macro's background summarize turn ends, land the result on the
	macro — server-side, so the summary arrives even if the user's tab is gone.
	ready → merged_prompt set (this is what run_macro executes); failed /
	unmergeable → the step sequence runs (correct fallback: an unmergeable
	sequence NEEDS its checkpoints). Publishes ``macro:merged`` so an open SPA
	refreshes its Run buttons."""
	macro_name = frappe.db.get_value(
		MACRO, {"merge_conversation": conversation_id, "merge_status": "pending"}, "name"
	)
	if not macro_name:
		return
	doc = frappe.get_doc(MACRO, macro_name)
	status, merged = "failed", ""
	if not errored:
		rows = frappe.get_all(
			MSG,
			filters={"conversation": conversation_id, "role": "assistant"},
			fields=["content", "streaming", "error"],
			order_by="seq desc",
			limit=1,
		)
		m = rows[0] if rows else None
		if m and not m.streaming and not (m.error or "").strip():
			from jarvis.chat.macros_api import _MERGE_RE

			mt = _MERGE_RE.search(m.content or "")
			try:
				merge = frappe.parse_json(mt.group(1).strip()) if mt else None
			except Exception:
				merge = None
			if (
				isinstance(merge, dict)
				and merge.get("mergeable")
				and str(merge.get("merged_prompt") or "").strip()
			):
				status, merged = "ready", str(merge.get("merged_prompt")).strip()
	frappe.db.set_value(
		MACRO,
		macro_name,
		{
			"merged_prompt": merged,
			"merge_status": status,
			"merge_conversation": "",
		},
		update_modified=False,
	)
	frappe.db.commit()
	# The throwaway conversation served its purpose — clean it up best-effort.
	try:
		frappe.db.delete(MSG, {"conversation": conversation_id})
		frappe.delete_doc("Jarvis Conversation", conversation_id, force=True, ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		pass
	publish_to_user(
		doc.owner,
		{
			"kind": "macro:merged",
			"macro": macro_name,
			"macro_name": doc.macro_name,
			"status": status,
		},
	)


def stop_macro_run(run_name: str) -> dict:
	"""Mark a run stopped so the chaining hook halts. The in-flight turn, if any,
	still finishes; no further steps are enqueued. Exposed via
	``macros_api.stop_macro_run`` (owner-gated there)."""
	run = frappe.get_doc(RUN, run_name)
	run.check_permission("write")  # owner-gate the stop action
	# CDX-19: waiting_capacity is a live (non-terminal) run parked for capacity, so it must be
	# stoppable too — otherwise the resume cron would keep re-attempting a run the user stopped.
	if run.status in ("running", "waiting_capacity"):
		frappe.db.set_value(RUN, run.name, {"status": "stopped", "finished_at": frappe.utils.now()})
		frappe.db.commit()
		try:
			_publish_done(run, frappe.get_doc(MACRO, run.macro), "stopped")
		except Exception:
			pass
	return {"ok": True}


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _skill_invocations(step) -> str:
	"""Render one STEP's tagged skills (a JSON list of Jarvis Custom Skill
	row-names on the step row) as a ``/slug`` invocation line appended to that
	step's prompt — the same mechanism as typing ``/slug`` in the composer, so
	``invoked_skill_clause`` activates them deterministically at turn time
	(which also re-checks owner/shared visibility). Disabled or since-deleted
	skills drop out silently."""
	try:
		names = frappe.parse_json(step.skills) if step.skills else []
	except Exception:
		names = []
	names = [n for n in names if isinstance(n, str) and n.strip()] if isinstance(names, list) else []
	if not names:
		return ""
	slugs = frappe.get_all(
		"Jarvis Custom Skill",
		filters={"name": ["in", names], "enabled": 1},
		fields=["skill_name"],
		order_by="skill_name asc",
	)
	if not slugs:
		return ""
	return "\n\nApply these skills: " + " ".join(f"/{s.skill_name}" for s in slugs)


def _run_step(run, macro_doc, index: int) -> bool:
	"""Enqueue the turn for step ``index`` (0-based) and stamp current_step. Returns
	True when the step dispatched, False when it was DEFERRED for capacity.

	CDX-19: at the entry to this call ``run.current_step == index`` (run_macro seeds 0
	for step 0; advance_after_turn passes ``next_index == current_step``). If the accept
	gate is overloaded, ``_enqueue_turn`` returns {overloaded:True} WITHOUT dispatching a
	turn and after deleting its seed — the step must NOT advance (no turn will ever chain
	the run forward). Park the run in ``waiting_capacity`` with current_step left pointing
	at this same step so ``resume_waiting_capacity_runs`` re-attempts it next cycle."""
	step = macro_doc.steps[index]
	from jarvis.chat import api

	out = api._enqueue_turn(
		run.conversation,
		(step.prompt or "").strip() + _skill_invocations(step),
		model_override=(step.model_override or None),
		thinking_override=(step.thinking_override or None),
	)
	if isinstance(out, dict) and out.get("overloaded"):
		_defer_capacity(run, macro_doc)
		return False
	frappe.db.set_value(RUN, run.name, "current_step", index + 1)
	frappe.db.commit()
	run.current_step = index + 1
	_publish_progress(run, macro_doc, index)
	return True


def _merged_skill_invocations(macro_doc) -> str:
	"""Union of ALL steps' tagged skills (order kept) for the merged
	single-turn run — the summary covers every step, so it inherits every
	step's skills. Same /slug mechanism + visibility rules as per-step."""
	names, seen = [], set()
	for s in macro_doc.steps or []:
		try:
			lst = frappe.parse_json(s.skills) if s.skills else []
		except Exception:
			lst = []
		for n in lst if isinstance(lst, list) else []:
			if isinstance(n, str) and n.strip() and n not in seen:
				seen.add(n)
				names.append(n)
	if not names:
		return ""
	slugs = frappe.get_all(
		"Jarvis Custom Skill",
		filters={"name": ["in", names], "enabled": 1},
		fields=["skill_name"],
		order_by="skill_name asc",
	)
	if not slugs:
		return ""
	return "\n\nApply these skills: " + " ".join(f"/{s.skill_name}" for s in slugs)


def _run_merged(run, macro_doc, merged_prompt: str) -> bool:
	"""Enqueue the macro's summarized prompt as its single turn. Overrides =
	first non-empty among the steps (same rule the merge apply used). Returns True
	when dispatched, False when DEFERRED for capacity (CDX-19: park in
	``waiting_capacity``; the resume cron re-attempts the merged turn next cycle)."""
	steps = macro_doc.steps or []
	model_o = next((s.model_override for s in steps if (s.model_override or "").strip()), None)
	think_o = next((s.thinking_override for s in steps if (s.thinking_override or "").strip()), None)
	from jarvis.chat import api

	out = api._enqueue_turn(
		run.conversation,
		merged_prompt + _merged_skill_invocations(macro_doc),
		model_override=model_o,
		thinking_override=think_o,
	)
	if isinstance(out, dict) and out.get("overloaded"):
		_defer_capacity(run, macro_doc)
		return False
	frappe.db.set_value(RUN, run.name, "current_step", 1)
	frappe.db.commit()
	run.current_step = 1
	publish_to_user(
		macro_doc.owner,
		{
			"kind": "macro:progress",
			"macro_run": run.name,
			"macro": macro_doc.name,
			"conversation": run.conversation,
			"step": 1,
			"total": 1,
			"label": "Summarized prompt",
			"status": "running",
		},
	)
	return True


def _defer_capacity(run, macro_doc) -> None:
	"""CDX-19: the site's turn queue was momentarily full at the accept gate, so the current
	step could not be admitted (its seed was cleaned up, no turn dispatched). Park the run in
	``waiting_capacity`` WITHOUT advancing ``current_step`` — ``resume_waiting_capacity_runs``
	re-attempts the SAME step on its next cron cycle. Idempotent: only flips a ``running`` run
	(a stop/finish that already moved on wins)."""
	if frappe.db.get_value(RUN, run.name, "status") != "running":
		return
	frappe.db.set_value(RUN, run.name, {"status": "waiting_capacity"}, update_modified=True)
	frappe.db.commit()
	run.status = "waiting_capacity"
	try:
		publish_to_user(
			macro_doc.owner,
			{
				"kind": "macro:progress",
				"macro_run": run.name,
				"macro": macro_doc.name,
				"conversation": run.conversation,
				"step": (run.current_step or 0) + 1,
				"total": run.total_steps,
				"label": "Waiting for capacity",
				"status": "waiting_capacity",
			},
		)
	except Exception:
		pass


def resume_waiting_capacity_runs() -> None:
	"""Cron backstop (chat-concurrency CDX-19): re-attempt every macro run parked in
	``waiting_capacity``. A run lands there when a step could not be admitted because the
	site's turn queue was momentarily full (``_enqueue_turn`` returned overloaded). This is
	the ONLY re-attempt path for an in-flight step — a deferred step dispatches no turn, so
	the turn-end chaining hook (``advance_after_turn``) never fires for it.

	Bounded: ``capacity_attempts`` is incremented each cycle; once it exceeds
	``_MAX_CAPACITY_ATTEMPTS`` the run takes its NORMAL failure path with an honest reason
	rather than retrying forever. Serialized + idempotent via the same per-run redis lock
	the chaining hook uses, so a resume can never race a late step advance. Never raises."""
	rows = frappe.get_all(RUN, filters={"status": "waiting_capacity"}, pluck="name")
	if not rows:
		return
	from jarvis._redis_lock import redis_lock

	for run_name in rows:
		try:
			with redis_lock(f"jarvis_macro_run:{run_name}", timeout_s=60, blocking_timeout_s=0.0) as acquired:
				if not acquired:
					continue
				run = frappe.get_doc(RUN, run_name)
				if run.status != "waiting_capacity":
					continue
				macro_doc = frappe.get_doc(MACRO, run.macro)
				attempts = int(run.capacity_attempts or 0) + 1
				if attempts > _MAX_CAPACITY_ATTEMPTS:
					_finish(
						run,
						"failed",
						error="The site stayed busy — the macro could not get capacity to run this step.",
					)
					_publish_done(run, macro_doc, "failed")
					continue
				# Flip back to running + record the attempt BEFORE re-enqueue so a re-overload
				# (which flips back to waiting_capacity) keeps the bounded, incremented count.
				frappe.db.set_value(
					RUN, run.name, {"status": "running", "capacity_attempts": attempts}, update_modified=True
				)
				frappe.db.commit()
				run.status = "running"
				run.capacity_attempts = attempts
				merged = (macro_doc.merged_prompt or "").strip()
				if merged:
					_run_merged(run, macro_doc, merged)
				else:
					_run_step(run, macro_doc, int(run.current_step or 0))
		except Exception:
			frappe.log_error(title="jarvis macro capacity-resume failed", message=frappe.get_traceback())


def _finish(run, status: str, error: str | None = None) -> None:
	frappe.db.set_value(
		RUN,
		run.name,
		{"status": status, "finished_at": frappe.utils.now(), "error": (error or "")[:500]},
	)
	frappe.db.commit()


def _publish_progress(run, macro_doc, index: int) -> None:
	step = macro_doc.steps[index]
	publish_to_user(
		macro_doc.owner,
		{
			"kind": "macro:progress",
			"macro_run": run.name,
			"macro": macro_doc.name,
			"conversation": run.conversation,
			"step": index + 1,
			"total": run.total_steps,
			"label": (step.label or "").strip() or f"Step {index + 1}",
			"status": "running",
		},
	)


def _publish_done(run, macro_doc, status: str) -> None:
	publish_to_user(
		macro_doc.owner,
		{
			"kind": "macro:done",
			"macro_run": run.name,
			"macro": macro_doc.name,
			"conversation": run.conversation,
			"status": status,
		},
	)
