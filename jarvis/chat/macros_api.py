"""SPA-facing CRUD + run/stop for customer macros.

The ``/jarvis`` Macros UI calls these whitelisted methods to manage
``Jarvis Macro`` rows (owner-scoped) and to run/stop them. Mirrors the shape of
``jarvis.chat.custom_skills_api`` (owner ``frappe.get_all``, ``{ok, data}``,
commit). Execution itself lives in ``jarvis.chat.macros``.
"""

import re

import frappe
from frappe import _

MACRO = "Jarvis Macro"
RUN = "Jarvis Macro Run"
MSG = "Jarvis Chat Message"


def _parse_steps(steps) -> list[dict]:
	"""Normalize the steps array (JSON string or list) into child-row dicts,
	dropping blank prompts. Order is preserved (child ``idx``)."""
	if steps is None:
		return []
	if isinstance(steps, str):
		steps = frappe.parse_json(steps)
	if not isinstance(steps, list):
		return []
	rows = []
	for s in steps:
		if not isinstance(s, dict):
			continue
		prompt = (s.get("prompt") or "").strip()
		if not prompt:
			continue
		rows.append({
			"label": (s.get("label") or "").strip(),
			"prompt": prompt,
			"model_override": (s.get("model_override") or "").strip(),
			"thinking_override": (s.get("thinking_override") or "").strip(),
			"skills": frappe.as_json(_clean_step_skills(s.get("skills"))),
		})
	return rows


# --------------------------------------------------------------------------- #
# CRUD (owner-scoped)
# --------------------------------------------------------------------------- #
def _clean_step_skills(skills) -> list[str]:
	"""Normalize one step's tagged-skills value (JSON string or list of Jarvis
	Custom Skill row-names) into a validated list. Only skills the current user
	OWNS or was SHARED are accepted — same visibility rule as invoking /slug in
	chat. Stored as a JSON list on the step row (child tables can't nest a
	child table, so a Table field is not an option here)."""
	if skills is None:
		return []
	if isinstance(skills, str):
		try:
			skills = frappe.parse_json(skills)
		except Exception:
			return []
	if not isinstance(skills, list):
		return []
	from jarvis.chat.custom_skills_api import _skill_names_shared_with

	me = frappe.session.user
	shared = set(_skill_names_shared_with(me))
	clean, seen = [], set()
	for name in skills:
		name = (name or "").strip() if isinstance(name, str) else ""
		if not name or name in seen:
			continue
		owner = frappe.db.get_value("Jarvis Custom Skill", name, "owner")
		if not owner:
			continue
		if owner != me and name not in shared:
			continue
		seen.add(name)
		clean.append(name)
	return clean


@frappe.whitelist()
def list_macros() -> list[dict]:
	"""The current user's macros (no step bodies), newest first, with a count."""
	macros = frappe.get_all(
		MACRO,
		filters={"owner": frappe.session.user},
		fields=[
			"name", "macro_name", "description", "enabled", "stop_on_error",
			"schedule_enabled", "schedule_frequency", "schedule_time",
			"next_run_at", "last_run_at", "modified",
		],
		order_by="macro_name asc",
	)
	for m in macros:
		m["step_count"] = frappe.db.count("Jarvis Macro Step", {"parent": m["name"]})
	return macros


@frappe.whitelist()
def get_macro(name: str) -> dict:
	"""One macro incl. its ordered steps (owner-gated)."""
	doc = frappe.get_doc(MACRO, name)
	doc.check_permission("read")  # get_doc alone doesn't enforce if_owner
	return {
		"name": doc.name,
		"macro_name": doc.macro_name,
		"description": doc.description or "",
		"enabled": int(doc.enabled or 0),
		"stop_on_error": int(doc.stop_on_error or 0),
		"schedule_enabled": int(doc.schedule_enabled or 0),
		"schedule_frequency": doc.schedule_frequency or "daily",
		"schedule_time": str(doc.schedule_time or ""),
		"next_run_at": str(doc.next_run_at or ""),
		"steps": [
			{
				"label": s.label or "",
				"prompt": s.prompt or "",
				"model_override": s.model_override or "",
				"thinking_override": s.thinking_override or "",
				"skills": _step_skills(s),
			}
			for s in (doc.steps or [])
		],
	}


def _step_skills(step) -> list[str]:
	"""Parse a step row's ``skills`` JSON into a list (tolerant of legacy rows)."""
	try:
		v = frappe.parse_json(step.skills) if step.skills else []
		return v if isinstance(v, list) else []
	except Exception:
		return []


@frappe.whitelist()
def create_macro(
	macro_name: str,
	description: str = "",
	steps=None,
	enabled: int = 1,
	stop_on_error: int = 1,
	schedule_enabled: int = 0,
	schedule_frequency: str = "daily",
	schedule_time=None,
) -> dict:
	"""Create a macro. Validation (name/steps/caps) runs in the doctype validate().
	Per-step tagged skills arrive INSIDE each step dict (``steps[].skills``)."""
	doc = frappe.get_doc({
		"doctype": MACRO,
		"macro_name": macro_name,
		"description": description or "",
		"enabled": int(enabled or 0),
		"stop_on_error": int(stop_on_error or 0),
		"schedule_enabled": int(schedule_enabled or 0),
		"schedule_frequency": schedule_frequency or "daily",
		"schedule_time": schedule_time or None,
		"steps": _parse_steps(steps),
	})
	doc.insert()
	frappe.db.commit()
	return {"ok": True, "data": {"name": doc.name, "macro_name": doc.macro_name}}


@frappe.whitelist()
def update_macro(
	name: str,
	macro_name: str | None = None,
	description: str | None = None,
	steps=None,
	enabled: int | None = None,
	stop_on_error: int | None = None,
	schedule_enabled: int | None = None,
	schedule_frequency: str | None = None,
	schedule_time=None,
) -> dict:
	"""Update provided fields of a macro (owner-gated). When ``steps`` is given it
	replaces the whole ordered list (per-step skills ride inside each step dict)."""
	doc = frappe.get_doc(MACRO, name)
	doc.check_permission("write")  # owner-gate (save enforces too; explicit for clarity)
	if macro_name is not None:
		doc.macro_name = macro_name
	if description is not None:
		doc.description = description
	if enabled is not None:
		doc.enabled = int(enabled)
	if stop_on_error is not None:
		doc.stop_on_error = int(stop_on_error)
	if schedule_enabled is not None:
		doc.schedule_enabled = int(schedule_enabled)
	if schedule_frequency is not None:
		doc.schedule_frequency = schedule_frequency
	if schedule_time is not None:
		doc.schedule_time = schedule_time or None
	if steps is not None:
		doc.set("steps", _parse_steps(steps))
	doc.save()
	frappe.db.commit()
	return {"ok": True, "data": {"name": doc.name, "modified": str(doc.modified)}}


@frappe.whitelist()
def delete_macro(name: str) -> dict:
	"""Delete a macro row (owner-gated). Its Macro Run history rows link the
	macro and would block the delete (LinkExistsError), so they go first — they
	are just execution history; the run conversations themselves stay."""
	doc = frappe.get_doc(MACRO, name)
	doc.check_permission("write")  # owner-gate before touching linked runs
	for r in frappe.get_all(RUN, filters={"macro": name}, pluck="name"):
		frappe.delete_doc(RUN, r, ignore_permissions=True, force=True)
	frappe.delete_doc(MACRO, name)  # honors if_owner
	frappe.db.commit()
	return {"ok": True}


# --------------------------------------------------------------------------- #
# Run / stop
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def run_macro(name: str) -> dict:
	"""Start a macro now (manual trigger). Returns the run + conversation."""
	from jarvis.chat import macros

	return macros.run_macro(name, trigger="manual")


@frappe.whitelist()
def stop_macro_run(run: str) -> dict:
	"""Stop an in-progress run (owner-gated)."""
	from jarvis.chat import macros

	return macros.stop_macro_run(run)


@frappe.whitelist()
def get_macro_run(run: str) -> dict:
	"""Current state of a run (for polling as a socketio fallback)."""
	doc = frappe.get_doc(RUN, run)
	doc.check_permission("read")  # owner-gate
	return {
		"name": doc.name,
		"macro": doc.macro,
		"conversation": doc.conversation,
		"status": doc.status,
		"current_step": doc.current_step,
		"total_steps": doc.total_steps,
		"error": doc.error or "",
	}


# --------------------------------------------------------------------------- #
# Run history dashboard (settings → Macro runs)
# --------------------------------------------------------------------------- #
_RUN_STATUSES = {"queued", "running", "completed", "failed", "stopped"}


@frappe.whitelist()
def list_macro_runs(status: str = "", macro: str = "", limit=30, start=0) -> dict:
	"""The current user's macro runs, newest-first, for the history dashboard.

	Joins the macro for its display name and computes each run's duration in
	seconds. Optional filters: ``status`` (a run status) and ``macro`` (a macro
	row-name). Owner-scoped in SQL so another user's runs are never returned.
	Fetches ``limit + 1`` rows to report ``has_more`` for the SPA's Load more."""
	limit = max(1, min(int(limit or 30), 100))
	start = max(0, int(start or 0))
	conditions = ["r.owner = %(owner)s"]
	params = {"owner": frappe.session.user, "limit": limit + 1, "start": start}
	if status and status in _RUN_STATUSES:
		conditions.append("r.status = %(status)s")
		params["status"] = status
	if macro:
		conditions.append("r.macro = %(macro)s")
		params["macro"] = macro
	where = " AND ".join(conditions)
	rows = frappe.db.sql(
		f"""
		SELECT r.name, r.macro, COALESCE(m.macro_name, r.macro) AS macro_name,
		       r.conversation, r.status, r.current_step, r.total_steps,
		       r.`trigger` AS `trigger`, r.creation, r.started_at, r.finished_at, r.error,
		       CASE WHEN r.started_at IS NOT NULL AND r.finished_at IS NOT NULL
		            THEN TIMESTAMPDIFF(SECOND, r.started_at, r.finished_at)
		       END AS duration_s
		FROM `tabJarvis Macro Run` r
		LEFT JOIN `tabJarvis Macro` m ON m.name = r.macro
		WHERE {where}
		ORDER BY r.creation DESC
		LIMIT %(limit)s OFFSET %(start)s
		""",
		params,
		as_dict=True,
	)
	return {"runs": rows[:limit], "has_more": len(rows) > limit}


@frappe.whitelist()
def macro_run_stats() -> dict:
	"""Summary tiles for the dashboard: counts per status, success rate, and the
	last run time — all owner-scoped. Success rate = completed / (completed +
	failed); stopped runs are user cancellations, not failures, so they're
	excluded from the rate (but still counted in ``total``)."""
	owner = {"owner": frappe.session.user}
	rows = frappe.db.sql(
		"SELECT status, COUNT(*) AS n FROM `tabJarvis Macro Run` "
		"WHERE owner = %(owner)s GROUP BY status",
		owner,
		as_dict=True,
	)
	by = {r.status: r.n for r in rows}
	completed = by.get("completed", 0)
	failed = by.get("failed", 0)
	finished = completed + failed
	last = frappe.db.sql(
		"SELECT MAX(creation) FROM `tabJarvis Macro Run` WHERE owner = %(owner)s", owner
	)[0][0]
	return {
		"total": sum(by.values()),
		"completed": completed,
		"failed": failed,
		"running": by.get("running", 0),
		"queued": by.get("queued", 0),
		"stopped": by.get("stopped", 0),
		"success_rate": round(completed * 100 / finished) if finished else None,
		"last_run_at": str(last) if last else "",
	}


# --------------------------------------------------------------------------- #
# Macro merge — summarize a 2+ step sequence into one prompt (spec:
# docs/superpowers/specs/2026-07-03-macro-merge-design.md). The LLM does the
# merging via the persona /macro-merge skill in a throwaway archived
# conversation; these endpoints are the deterministic plumbing around it.
# --------------------------------------------------------------------------- #
_MERGE_RE = re.compile(r"```jarvis-macro-merge[ \t]*\n([\s\S]*?)```")

_MERGE_INSTRUCTION = (
	"Summarize this macro's steps into ONE coherent self-contained prompt — a "
	"genuine rewrite that reads as a single ask, NOT the steps restated as a "
	"numbered list. Keep the execution order and weave every inter-step "
	'dependency into the prose ("...and from those results..."). Keep every '
	"concrete detail (filters, dates, names, quantities, formats). Reply with "
	"one short lead-in line and exactly one fenced ```jarvis-macro-merge``` "
	'block holding JSON: {"mergeable": bool, "reason": str, "merged_prompt": '
	'str, "dependencies": [{"step": int, "uses": [int]}]}. Set '
	"mergeable=false when merging would lose a user review checkpoint before "
	"a data change. Steps:\n\n"
)


def _own_conversation(conversation: str) -> None:
	owner = frappe.db.get_value("Jarvis Conversation", conversation, "owner")
	if not owner:
		frappe.throw(_("Unknown conversation."))
	if owner != frappe.session.user:
		frappe.throw(_("Not your conversation."), frappe.PermissionError)


@frappe.whitelist()
def summarize_macro(name: str) -> dict:
	"""Kick off the merge: throwaway archived conversation + one agent turn
	that invokes /macro-merge over the macro's steps. Returns the conversation
	for the SPA to poll. The macro itself is untouched here."""
	doc = frappe.get_doc(MACRO, name)
	doc.check_permission("read")  # owner-gate (if_owner)
	steps = doc.steps or []
	if len(steps) < 2:
		frappe.throw(_("Nothing to merge — the macro has fewer than 2 steps."))
	conv = frappe.get_doc({
		"doctype": "Jarvis Conversation",
		"title": f"Merge: {doc.macro_name}"[:140],
		"status": "Active",  # enqueue against Active; hidden right after
	})
	conv.flags.ignore_permissions = True
	conv.insert()
	payload = [
		{"n": i + 1, "label": s.label or "", "prompt": s.prompt or ""}
		for i, s in enumerate(steps)
	]
	from jarvis.chat import api as chat_api

	prompt = _MERGE_INSTRUCTION + frappe.as_json(payload) + "\n\nApply these skills: /macro-merge"
	chat_api._enqueue_turn(conv.name, prompt)
	# Hide from the sidebar (list_conversations skips Archived).
	frappe.db.set_value("Jarvis Conversation", conv.name, "status", "Archived",
						update_modified=False)
	frappe.db.commit()
	return {"ok": True, "conversation": conv.name}


@frappe.whitelist()
def get_macro_merge(conversation: str) -> dict:
	"""Poll target for the merge turn: pending → ready(merge)/error."""
	_own_conversation(conversation)
	rows = frappe.get_all(
		MSG,
		filters={"conversation": conversation, "role": "assistant"},
		fields=["content", "streaming", "error"],
		order_by="seq desc", limit=1,
	)
	m = rows[0] if rows else None
	if m and (m.error or "").strip():
		return {"status": "error", "error": m.error}
	if not m or m.streaming or not (m.content or "").strip():
		return {"status": "pending"}
	mt = _MERGE_RE.search(m.content)
	if not mt:
		return {"status": "error", "error": "no merge block in the reply"}
	try:
		merge = frappe.parse_json(mt.group(1).strip())
	except Exception:
		merge = None
	if not isinstance(merge, dict):
		return {"status": "error", "error": "unparsable merge block"}
	return {"status": "ready", "merge": {
		"mergeable": bool(merge.get("mergeable")),
		"reason": str(merge.get("reason") or ""),
		"merged_prompt": str(merge.get("merged_prompt") or ""),
		"dependencies": merge.get("dependencies") if isinstance(merge.get("dependencies"), list) else [],
	}}


@frappe.whitelist()
def apply_macro_merge(name: str, merged_prompt: str, conversation: str = "") -> dict:
	"""Collapse the macro to ONE step holding ``merged_prompt`` (possibly
	user-edited). Skills = union of the original steps' tags (order kept);
	model/thinking overrides = first non-empty. Cleans up the merge
	conversation best-effort."""
	doc = frappe.get_doc(MACRO, name)
	doc.check_permission("write")
	merged_prompt = (merged_prompt or "").strip()
	if not merged_prompt:
		frappe.throw(_("Merged prompt is empty."))
	steps = doc.steps or []
	union, seen = [], set()
	for s in steps:
		for sk in _step_skills(s):
			if sk not in seen:
				seen.add(sk)
				union.append(sk)
	model_o = next((s.model_override for s in steps if (s.model_override or "").strip()), "")
	think_o = next((s.thinking_override for s in steps if (s.thinking_override or "").strip()), "")
	doc.set("steps", [{
		"label": "Merged",
		"prompt": merged_prompt,
		"model_override": model_o or "",
		"thinking_override": think_o or "",
		"skills": frappe.as_json(union),
	}])
	doc.save()
	frappe.db.commit()
	if conversation:
		try:
			discard_macro_merge(conversation)
		except Exception:
			pass  # best-effort cleanup; the conversation is archived anyway
	return {"ok": True, "step_count": 1}


@frappe.whitelist()
def discard_macro_merge(conversation: str) -> dict:
	"""Delete the throwaway merge conversation + its messages (Keep sequence /
	unmergeable / error paths). Best-effort: if a link blocks the delete the
	conversation stays archived, which is invisible anyway."""
	_own_conversation(conversation)
	frappe.db.delete(MSG, {"conversation": conversation})
	try:
		frappe.delete_doc("Jarvis Conversation", conversation, force=True, ignore_permissions=True)
	except Exception:
		pass
	frappe.db.commit()
	return {"ok": True}
