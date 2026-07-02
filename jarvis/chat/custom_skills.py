"""Render Jarvis Custom Skill rows into openclaw SKILL.md payloads.

A customer authors a bare slug (e.g. ``invoicing``); everywhere it reaches
openclaw it becomes ``custom-invoicing`` so it can never collide with a shared
persona skill (none of which start with ``custom-``). The push payload is a
list of ``{slug, description, user_invocable, body}`` dicts, where ``body`` is
the fully-rendered SKILL.md text written verbatim to disk by the fleet-agent.

The render helpers are PURE (no frappe calls) so they're unit-testable;
:func:`build_push_payload` is the only frappe-touching function.
"""

import re

import frappe

# Mirrors the bench-side cap in jarvis_custom_skill.py; re-asserted here so a
# stale/over-cap state can never be pushed.
MAX_SKILLS_PER_PUSH = 25
RESERVED_PREFIX = "custom-"

# Matches a /slug token the user typed in the composer to invoke a skill.
_INVOKE_RE = re.compile(r"(?:^|\s)/([a-z0-9]+(?:-[a-z0-9]+)*)")


def prefixed_slug(skill_name: str) -> str:
	"""Bare authored slug -> the namespaced slug used on disk and in openclaw."""
	return f"{RESERVED_PREFIX}{(skill_name or '').strip().lower()}"


def _yaml_quote(s: str) -> str:
	"""Return ``s`` as a safe double-quoted YAML scalar (single logical line).

	Newlines/tabs are folded to spaces so the frontmatter ``description`` stays
	one line; backslashes and double-quotes are escaped.
	"""
	folded = " ".join((s or "").split())
	escaped = folded.replace("\\", "\\\\").replace('"', '\\"')
	return f'"{escaped}"'


def render_skill_md(
	skill_name: str, description: str, user_invocable: bool, instructions: str
) -> str:
	"""Build the full SKILL.md text (YAML frontmatter + markdown body).

	Frontmatter matches the shared persona skills (name / description /
	user-invocable). ``name`` uses the PREFIXED slug.
	"""
	body = (instructions or "").strip()
	lines = [
		"---",
		f"name: {prefixed_slug(skill_name)}",
		f"description: {_yaml_quote(description)}",
		f"user-invocable: {'true' if user_invocable else 'false'}",
		"---",
		"",
		body,
		"",
	]
	return "\n".join(lines)


def invoked_skill_clause(message: str) -> str:
	"""Return a context-line clause naming any enabled custom skills the user
	invoked via ``/slug`` in ``message`` (so the agent activates the installed
	``custom-<slug>`` skills deterministically), or ``""`` if none match.

	The clause is folded INTO the worker's leading ``[Context: ...]`` line,
	which the persona's AGENTS.md tells the agent to treat as system, not user.
	"""
	if not message or "/" not in message:
		return ""
	slugs = {s.lower() for s in _INVOKE_RE.findall(message)}
	if not slugs:
		return ""
	# Only skills the current chat user OWNS or was SHARED with can be invoked by
	# slug — so a skill shared with specific people isn't triggerable by others
	# (even though it lives in the customer's shared container). Auto-pick by
	# description is still bench-global (a container-level limitation).
	me = frappe.session.user
	enabled = {
		r.skill_name
		for r in frappe.get_all(
			"Jarvis Custom Skill", filters={"enabled": 1, "owner": me}, fields=["skill_name"]
		)
	}
	shared_names = [
		r.parent
		for r in frappe.get_all(
			"Jarvis Custom Skill Share",
			filters={"user": me, "parenttype": "Jarvis Custom Skill"},
			fields=["parent"],
		)
	]
	if shared_names:
		enabled |= {
			r.skill_name
			for r in frappe.get_all(
				"Jarvis Custom Skill",
				filters={"enabled": 1, "name": ["in", shared_names]},
				fields=["skill_name"],
			)
		}
	matched = sorted(s for s in slugs if s in enabled)
	if not matched:
		return ""
	names = ", ".join(prefixed_slug(s) for s in matched)
	return f"; the user invoked these skills, apply them: {names}"


def build_push_payload(owner: str | None = None) -> list[dict]:
	"""Collect the enabled custom skills into the fleet push payload.

	Bench-global by design: a Jarvis bench maps to one customer / one
	container, so ALL enabled rows on the site are pushed (``owner`` is accepted
	only to scope tests). An empty list is a valid "remove all custom skills"
	reconcile.
	"""
	filters = {"enabled": 1}
	if owner:
		filters["owner"] = owner
	rows = frappe.get_all(
		"Jarvis Custom Skill",
		filters=filters,
		fields=["skill_name", "description", "user_invocable", "instructions"],
		order_by="skill_name asc",
	)
	payload = []
	for r in rows[:MAX_SKILLS_PER_PUSH]:
		ui = bool(r.user_invocable)
		payload.append(
			{
				"slug": prefixed_slug(r.skill_name),
				"description": r.description or "",
				"user_invocable": ui,
				"body": render_skill_md(r.skill_name, r.description, ui, r.instructions),
			}
		)
	return payload
