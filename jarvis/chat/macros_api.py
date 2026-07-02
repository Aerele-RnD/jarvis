"""SPA-facing CRUD + run/stop for customer macros.

The ``/jarvis`` Macros UI calls these whitelisted methods to manage
``Jarvis Macro`` rows (owner-scoped) and to run/stop them. Mirrors the shape of
``jarvis.chat.custom_skills_api`` (owner ``frappe.get_all``, ``{ok, data}``,
commit). Execution itself lives in ``jarvis.chat.macros``.
"""

import frappe

MACRO = "Jarvis Macro"
RUN = "Jarvis Macro Run"


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
