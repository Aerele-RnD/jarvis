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
from frappe import _

# Mirrors the bench-side cap in jarvis_custom_skill.py; re-asserted here so a
# stale/over-cap state can never be pushed.
MAX_SKILLS_PER_PUSH = 25
RESERVED_PREFIX = "custom-"
# Genuine compiled learned rows are ALWAYS Administrator-owned (the compiler owns
# them as Administrator). Pinning the turn-injection query to this owner is
# defense in depth: even if a rogue row somehow carries managed_by_learning=1, it
# is only ever injected into every user's turn when Administrator owns it.
MANAGED_OWNER = "Administrator"

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


def render_learned_skill_md(slug: str, description: str, instructions: str) -> str:
	"""The learned-namespace sibling of :func:`render_skill_md` (Behavioural
	Pattern Learning Phase 2). ``slug`` is the FULL wire slug
	(``learned-<domain>`` — never ``custom-`` prefixed: learned skills reconcile
	into the fleet's separate ``learned_skills`` namespace, so the frontmatter
	``name`` must match the on-disk ``learned-<domain>`` dir). Learned skills are
	never user-invocable (they auto-inject via ``learned_skill_clause``)."""
	body = (instructions or "").strip()
	lines = [
		"---",
		f"name: {(slug or '').strip().lower()}",
		f"description: {_yaml_quote(description)}",
		"user-invocable: false",
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
	# Allowed Roles (plan section 6.6): a skill scoped to a role via allowed_roles
	# is invocable by a matching-role user even without an explicit share. Purely
	# additive - a skill with EMPTY allowed_roles is unchanged (owner/shared only),
	# and managed learned skills are excluded here (they auto-inject, see
	# learned_skill_clause).
	enabled |= _role_scoped_invocable_names(me)
	matched = sorted(s for s in slugs if s in enabled)
	if not matched:
		return ""
	names = ", ".join(prefixed_slug(s) for s in matched)
	return f"; the user invoked these skills, apply them: {names}"


def _role_scoped_invocable_names(user: str) -> set[str]:
	"""Bare slugs of enabled, non-managed skills whose (non-empty) allowed_roles
	intersect ``user``'s roles. One cached role lookup + two indexed queries; no
	per-skill N+1 (plan section 6.6)."""
	from jarvis.learning.roles import roles_for_user

	user_roles = roles_for_user(user)
	if not user_roles:
		return set()
	parents = {
		r.parent
		for r in frappe.get_all(
			"Jarvis Custom Skill Allowed Role",
			filters={"parenttype": "Jarvis Custom Skill", "role": ["in", list(user_roles)]},
			fields=["parent"],
		)
	}
	if not parents:
		return set()
	return {
		r.skill_name
		for r in frappe.get_all(
			"Jarvis Custom Skill",
			filters={"name": ["in", list(parents)], "enabled": 1, "managed_by_learning": 0},
			fields=["skill_name"],
		)
	}


def learned_skill_clause(user: str | None = None) -> str:
	"""Context-line clause naming the role-matched learned skills to apply this
	turn (plan section 6.6 - the reliable deterministic activation path).

	Enabled ``managed_by_learning`` skills whose ``allowed_roles`` the chat user
	satisfies (empty = everyone; System Manager / Administrator always pass) are
	folded into the leading ``[Context: ...]`` line as ``learned-<domain>`` — the
	dedicated learned-namespace wire slug (Phase 2; the persona interplay clause
	names both the old ``custom-learned-`` and the new ``learned-`` prefixes, so
	agent-side behaviour is unchanged across the cutover). Portal users
	(desk_access=0 roles) never intersect desk-role allowed_roles, so learned
	skills self-suppress for them at this layer.

	Hot path: ONE cached role lookup + two indexed queries, capped at the <=6
	managed rows - no per-skill N+1.
	"""
	from jarvis.learning.roles import roles_for_user

	user = user or frappe.session.user
	managed = frappe.get_all(
		"Jarvis Custom Skill",
		filters={"managed_by_learning": 1, "enabled": 1, "owner": MANAGED_OWNER},
		fields=["name", "skill_name"],
	)
	if not managed:
		return ""

	user_roles = roles_for_user(user)
	privileged = user == "Administrator" or "System Manager" in user_roles

	if privileged:
		matched = [m.skill_name for m in managed]
	else:
		names = [m.name for m in managed]
		roles_by_skill: dict[str, set] = {m.name: set() for m in managed}
		for row in frappe.get_all(
			"Jarvis Custom Skill Allowed Role",
			filters={"parent": ["in", names], "parenttype": "Jarvis Custom Skill"},
			fields=["parent", "role"],
		):
			if row.role:
				roles_by_skill[row.parent].add(row.role)
		matched = [
			m.skill_name
			for m in managed
			if not roles_by_skill[m.name] or (roles_by_skill[m.name] & user_roles)
		]
	if not matched:
		return ""
	# skill_name on a managed row IS the wire slug ("learned-<domain>"): learned
	# skills ship through the dedicated learned_skills namespace, NOT the custom-
	# prefixed custom-skills push, so no RESERVED_PREFIX here.
	slugs = ", ".join(sorted(matched))
	return f"; apply these learned skills: {slugs}"


PERSONAL_CLAUSE_TTL_S = 300


def personal_skills_cache_key(user: str) -> str:
	return f"jarvis:pskills:{user}"


def personal_skill_clause(user: str | None = None) -> str:
	"""Context-line clause telling the agent the chat user has Personal-scope
	skills saved on the bench. Personal rows are never pushed to the container
	catalog (see :func:`build_push_payload`), so without this hint the model
	has no way to know they exist; it retrieves them via jarvis__find_skills /
	jarvis__get_skill. Redis-cached per-user count (300s; invalidated by the
	DocType controller on any row change) so the hot chat path pays one cache
	read."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return ""
	cache = frappe.cache()
	key = personal_skills_cache_key(user)
	count = cache.get_value(key)
	if count is None:
		# Exact scope match: NULL/empty scope rows are Org and never counted.
		count = frappe.db.count(
			"Jarvis Custom Skill",
			{"owner": user, "enabled": 1, "scope": "Personal"},
		)
		cache.set_value(key, int(count or 0), expires_in_sec=PERSONAL_CLAUSE_TTL_S)
	try:
		count = int(count or 0)
	except (TypeError, ValueError):
		count = 0
	if not count:
		return ""
	# Precedence tag (Skills-area rework, DESIGN.md section 6): personal skills
	# augment ONLY this user's own turns and must yield to org/role guidance on
	# conflict. The turn_handler emits this clause AFTER the org/role/learned/wiki
	# clauses so the ordering reinforces the same rule. Explicit /slug invocation
	# stays intentional (invoked_skill_clause is not demoted).
	return (
		f"; {count} personal skill(s) saved "
		"(applies to you; org guidance takes priority on conflict) "
		"- search with jarvis__find_skills"
	)


def build_push_payload(owner: str | None = None, strict: bool = False) -> list[dict]:
	"""Collect the enabled custom skills into the fleet push payload.

	Bench-global by design: a Jarvis bench maps to one customer / one
	container, so ALL enabled rows on the site are pushed (``owner`` is accepted
	only to scope tests). An empty list is a valid "remove all custom skills"
	reconcile.

	Personal-scope rows are EXCLUDED: they exist only for their owner (reached
	via the find_skills/get_skill tools), never for the shared container
	catalog, and must not eat into the 25-skill push budget. NULL/empty scope
	(pre-migration rows) means Org and IS pushed.

	Managed learned rows (``managed_by_learning=1``) are EXCLUDED: since the
	Phase-2 learned namespace they ride their own push
	(``jarvis.learning.compiler.build_learned_push_payload`` ->
	``admin_client.post_push_learned_skills``) and must not eat into the
	customer's 25-skill custom budget. Their exclusion here is also what makes
	the first post-cutover custom reconcile delete the stale
	``custom-learned-<domain>`` dirs from the container.

	Over-cap handling (Phase 2, plan 'tenant audit + graceful resync, then
	build_push_payload raise'):

	- ``strict=True`` (interactive callers - a human is present to act):
	  ``frappe.throw`` an actionable error naming the count, the cap and the
	  fix. Nothing is pushed.
	- ``strict=False`` (default; unattended callers - the enqueued push worker
	  and the post-restart resync): truncate to the first
	  ``MAX_SKILLS_PER_PUSH`` rows (``skill_name`` asc, as before) but
	  ``frappe.log_error`` a loud warning naming the dropped slugs, so the
	  truncation is never silent again.
	"""
	# ("in", ("Org", "")) — not ("!=", "Personal") — because db_query wraps the
	# "in" operator in ifnull(scope, ''), so legacy NULL-scope rows match ''.
	filters = {"enabled": 1, "managed_by_learning": 0, "scope": ("in", ("Org", ""))}
	if owner:
		filters["owner"] = owner
	rows = frappe.get_all(
		"Jarvis Custom Skill",
		filters=filters,
		fields=["skill_name", "description", "user_invocable", "instructions"],
		order_by="skill_name asc",
	)
	if len(rows) > MAX_SKILLS_PER_PUSH:
		if strict:
			frappe.throw(
				_(
					"{0} enabled custom skills exceed the push cap of {1}; "
					"disable {2} or consolidate. Nothing was pushed."
				).format(len(rows), MAX_SKILLS_PER_PUSH, len(rows) - MAX_SKILLS_PER_PUSH)
			)
		dropped = [prefixed_slug(r.skill_name) for r in rows[MAX_SKILLS_PER_PUSH:]]
		preview = ", ".join(dropped[:5]) + (", ..." if len(dropped) > 5 else "")
		frappe.log_error(
			title="Jarvis: custom-skills push truncated",
			message=(
				f"custom-skills push truncated: {len(rows)} enabled, "
				f"{MAX_SKILLS_PER_PUSH} pushed, {len(dropped)} dropped: {preview}"
			),
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
