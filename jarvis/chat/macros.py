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
	owner = doc.owner

	# Fresh conversation titled after the macro, seeded with an intro so the
	# transcript reads as a self-contained run.
	conv = frappe.get_doc({"doctype": CONV, "title": doc.macro_name[:140], "status": "Active"})
	conv.flags.ignore_permissions = True
	conv.insert()
	intro = frappe.get_doc({
		"doctype": MSG,
		"conversation": conv.name,
		"seq": 1,
		"role": "assistant",
		"content": f"▶ Running macro **{doc.macro_name}** — {len(steps)} step(s).",
	})
	intro.flags.ignore_permissions = True
	intro.insert()

	run = frappe.get_doc({
		"doctype": RUN,
		"macro": doc.name,
		"conversation": conv.name,
		"status": "running",
		"current_step": 0,
		"total_steps": len(steps),
		"trigger": trigger,
		"started_at": frappe.utils.now(),
	})
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
		publish_to_user(owner, {
			"kind": "conversation:new",
			"conversation_id": conv.name,
			"title": doc.macro_name[:140],
			"preview": f"Scheduled macro: {doc.macro_name}",
		})

	_run_step(run, doc, 0)
	return {"ok": True, "data": {"macro_run": run.name, "conversation": conv.name}}


def advance_after_turn(conversation_id: str, *, errored: bool) -> None:
	"""Chaining hook, called from ``turn_handler`` after every terminal turn
	outcome. If the conversation belongs to a ``running`` Macro Run, advance it:
	enqueue the next step, or finish. No-op for normal (non-macro) chats.

	Best-effort: never raises (a macro bug must not strand a normal turn).
	Serialized + idempotent via a per-run redis lock + the ``current_step`` guard
	so a re-delivered event / RQ retry can't double-advance."""
	try:
		run_name = frappe.db.get_value(
			RUN, {"conversation": conversation_id, "status": "running"}, "name"
		)
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
		frappe.log_error(
			title="jarvis macro advance failed", message=frappe.get_traceback()
		)


def stop_macro_run(run_name: str) -> dict:
	"""Mark a run stopped so the chaining hook halts. The in-flight turn, if any,
	still finishes; no further steps are enqueued. Exposed via
	``macros_api.stop_macro_run`` (owner-gated there)."""
	run = frappe.get_doc(RUN, run_name)
	run.check_permission("write")  # owner-gate the stop action
	if run.status == "running":
		frappe.db.set_value(
			RUN, run.name, {"status": "stopped", "finished_at": frappe.utils.now()}
		)
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


def _run_step(run, macro_doc, index: int) -> None:
	"""Enqueue the turn for step ``index`` (0-based) and stamp current_step."""
	step = macro_doc.steps[index]
	from jarvis.chat import api

	api._enqueue_turn(
		run.conversation,
		(step.prompt or "").strip() + _skill_invocations(step),
		model_override=(step.model_override or None),
		thinking_override=(step.thinking_override or None),
	)
	frappe.db.set_value(RUN, run.name, "current_step", index + 1)
	frappe.db.commit()
	run.current_step = index + 1
	_publish_progress(run, macro_doc, index)


def _finish(run, status: str, error: str | None = None) -> None:
	frappe.db.set_value(
		RUN,
		run.name,
		{"status": status, "finished_at": frappe.utils.now(), "error": (error or "")[:500]},
	)
	frappe.db.commit()


def _publish_progress(run, macro_doc, index: int) -> None:
	step = macro_doc.steps[index]
	publish_to_user(macro_doc.owner, {
		"kind": "macro:progress",
		"macro_run": run.name,
		"macro": macro_doc.name,
		"conversation": run.conversation,
		"step": index + 1,
		"total": run.total_steps,
		"label": (step.label or "").strip() or f"Step {index + 1}",
		"status": "running",
	})


def _publish_done(run, macro_doc, status: str) -> None:
	publish_to_user(macro_doc.owner, {
		"kind": "macro:done",
		"macro_run": run.name,
		"macro": macro_doc.name,
		"conversation": run.conversation,
		"status": status,
	})
