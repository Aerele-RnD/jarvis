"""SPA-facing CRUD + apply + run controls for the Agents Marketplace.

Mirrors ``jarvis.chat.custom_skills_api``: owner-scoped CRUD over ``Jarvis Agent
Installation`` rows, an explicit Apply that pushes the ENABLED installed bundles
to the container via a deduped redis-locked worker (admin -> fleet -> restart),
and read endpoints for the catalog / runs / findings.

Security (adversarial S3 — HARD REQ): every MUTATION resolves the row via
``frappe.get_doc`` + ``doc.check_permission(...)`` (owner-gate — ``get_doc``
alone does NOT enforce ``if_owner``), NEVER ``frappe.db.set_value`` by a
user-supplied bare name. A non-owner cannot mutate another owner's installation.
Enable / schedule are pure DB writes (no container restart — O6); only Apply
(install/uninstall/update reconcile) restarts the container.
"""

import frappe
from frappe import _

from jarvis.chat.agent_catalog import build_agent_push_payload
from jarvis.chat.macro_scheduler import compute_next_run

LISTING = "Jarvis Agent Listing"
INSTALLATION = "Jarvis Agent Installation"
RUN = "Jarvis Agent Run"
FINDING = "Jarvis Agent Finding"
ALLOWED_ROLE = "Jarvis Agent Allowed Role"
_SETTINGS = "Jarvis Settings"
_PUSH_JOB_ID = "jarvis_agent_skills_push"
_LOCK_NAME = "jarvis_agent_skills_push"

_FREQUENCIES = ("daily", "weekly", "monthly")
# Statuses a bench admin may set via set_listing_status (Draft is registry-only).
_ADMIN_STATUSES = ("Published", "Coming Soon", "Deprecated")
# Never meaningful as an agent restriction ("All" == unrestricted; the other two
# are identities, not grantable roles) and never offered in the admin picker.
_NON_SELECTABLE_ROLES = ("Administrator", "Guest", "All")


# --------------------------------------------------------------------------- #
# role-based access (RBAC)
# --------------------------------------------------------------------------- #
def _user_allowed_for_agent(listing, user: str | None = None) -> bool:
	"""True iff ``user`` may install / run the agent.

	Allowed iff the listing has NO ``allowed_roles`` rows (empty = unrestricted)
	OR the user's roles intersect them. System Manager is ALWAYS allowed.
	``listing`` may be a Jarvis Agent Listing doc or its name (agent_slug).
	Fail-closed on the restricted side: an unknown user has no roles beyond
	Guest/All, which never satisfy a restriction.
	"""
	user = user or frappe.session.user
	if isinstance(listing, str):
		allowed = frappe.get_all(
			ALLOWED_ROLE,
			filters={"parenttype": LISTING, "parent": listing},
			pluck="role",
		)
	else:
		allowed = [row.role for row in (listing.get("allowed_roles") or [])]
	if not allowed:
		return True
	roles = set(frappe.get_roles(user))
	if "System Manager" in roles:
		return True
	return bool(roles.intersection(allowed))


def _allowed_roles_map() -> dict[str, list[str]]:
	"""All listings' allowed_roles child rows in ONE query: {listing_name: [role, ...]}."""
	out: dict[str, list[str]] = {}
	for row in frappe.get_all(
		ALLOWED_ROLE,
		filters={"parenttype": LISTING, "parentfield": "allowed_roles"},
		fields=["parent", "role"],
		order_by="parent asc, idx asc",
	):
		out.setdefault(row.parent, []).append(row.role)
	return out


# --------------------------------------------------------------------------- #
# catalog + install state (read)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def list_agents() -> list[dict]:
	"""The full catalog plus THIS owner's install/enable/schedule state per
	agent. Read-only — the catalog is visible to every logged-in user. Each row
	also carries ``allowed_roles`` (empty = unrestricted) and ``allowed`` (0/1
	for the CURRENT user; System Manager is always 1) — display state only, the
	real gate is server-side in install_agent / run_agent_now / the scheduler."""
	me = frappe.session.user
	roles_map = _allowed_roles_map()
	my_roles = set(frappe.get_roles(me))
	is_sm = "System Manager" in my_roles
	listings = frappe.get_all(
		LISTING,
		fields=[
			"name", "agent_slug", "title", "description", "category", "nature",
			"version", "publisher", "status", "rule_pack", "default_schedule",
			"validated_for_fy", "tools_required",
		],
		order_by="status asc, title asc",
	)
	installs = {
		i.agent: i
		for i in frappe.get_all(
			INSTALLATION,
			filters={"owner": me},
			fields=[
				"name", "agent", "enabled", "installed_version", "sync_status",
				"schedule_enabled", "schedule_frequency", "schedule_time",
				"next_run_at", "last_run_at",
			],
		)
	}
	# All owners' install counts in one grouped query (DESIGN-V3 §14 F5 —
	# additive; feeds the "Featured" strip + the "N installs" hero stat).
	install_counts = {
		r.agent: r.n
		for r in frappe.db.sql(
			"SELECT agent, COUNT(*) AS n FROM `tabJarvis Agent Installation` GROUP BY agent",
			as_dict=True,
		)
	}
	out = []
	for lst in listings:
		inst = installs.get(lst.name)
		lst["installed"] = 1 if inst else 0
		lst["installation"] = inst.name if inst else None
		lst["enabled"] = int(inst.enabled) if inst else 0
		lst["installed_version"] = inst.installed_version if inst else None
		lst["schedule_enabled"] = int(inst.schedule_enabled) if inst else 0
		lst["schedule_frequency"] = inst.schedule_frequency if inst else None
		lst["schedule_time"] = str(inst.schedule_time) if (inst and inst.schedule_time) else None
		lst["next_run_at"] = str(inst.next_run_at) if (inst and inst.next_run_at) else None
		lst["update_available"] = (
			1 if inst and inst.installed_version and inst.installed_version != lst.version else 0
		)
		allowed_roles = roles_map.get(lst.name, [])
		lst["allowed_roles"] = allowed_roles
		lst["allowed"] = (
			1 if (is_sm or not allowed_roles or my_roles.intersection(allowed_roles)) else 0
		)
		lst["install_count"] = install_counts.get(lst.name, 0)
		out.append(lst)
	return out


@frappe.whitelist()
def get_agent(agent_slug: str) -> dict:
	"""One listing + the CURRENT user's installation for the agent detail page
	(DESIGN-V3 §8.3 / D39). Any authenticated user may read (listing perms =
	All read); the ``installation`` block is the caller's own install or None.
	``all_roles`` rides along only for System Managers (Admin-tab roles editor)."""
	listing = frappe.get_doc(LISTING, agent_slug)  # All-role read; 404s if unknown
	me = frappe.session.user
	is_sm = "System Manager" in frappe.get_roles(me)

	out: dict = {
		"name": listing.name,
		"agent_slug": listing.agent_slug,
		"title": listing.title,
		"description": listing.description,
		"category": listing.category,
		"nature": listing.nature,
		"version": listing.version,
		"publisher": listing.publisher,
		"status": listing.status,
		"tools_required": listing.tools_required,
		"min_apps": listing.min_apps,
		"rule_pack": listing.rule_pack,
		"skill_bundle": listing.skill_bundle,
		"default_schedule": listing.default_schedule,
		"validated_for_fy": listing.validated_for_fy,
		"allowed_roles": [row.role for row in (listing.allowed_roles or [])],
		"allowed": 1 if _user_allowed_for_agent(listing, me) else 0,
		"install_count": frappe.db.count(INSTALLATION, {"agent": listing.name}),
		"installation": None,
	}

	inst = frappe.get_all(
		INSTALLATION,
		filters={"owner": me, "agent": listing.name},
		fields=[
			"name", "enabled", "installed_version", "installed_at", "config",
			"sync_status", "synced_at", "schedule_enabled", "schedule_frequency",
			"schedule_time", "next_run_at", "last_run_at",
		],
		limit=1,
	)
	if inst:
		i = inst[0]
		i["enabled"] = int(i.enabled or 0)
		i["schedule_enabled"] = int(i.schedule_enabled or 0)
		i["schedule_time"] = str(i.schedule_time) if i.schedule_time else None
		i["next_run_at"] = str(i.next_run_at) if i.next_run_at else None
		i["last_run_at"] = str(i.last_run_at) if i.last_run_at else None
		out["installation"] = i

	if is_sm:
		out["all_roles"] = [
			r
			for r in frappe.get_all(
				"Role",
				filters={"disabled": 0, "desk_access": 1},
				order_by="name asc",
				pluck="name",
			)
			if r not in _NON_SELECTABLE_ROLES
		]
	return out


@frappe.whitelist()
def get_installations() -> list[dict]:
	"""This owner's installations, with the linked listing title/nature/status."""
	me = frappe.session.user
	rows = frappe.get_all(
		INSTALLATION,
		filters={"owner": me},
		fields=[
			"name", "agent", "enabled", "installed_version", "installed_at",
			"config", "sync_status", "synced_at", "schedule_enabled",
			"schedule_frequency", "schedule_time", "next_run_at", "last_run_at",
		],
		order_by="modified desc",
	)
	for r in rows:
		meta = frappe.db.get_value(
			LISTING, r.agent, ["title", "nature", "status", "version"], as_dict=True
		) or {}
		r["title"] = meta.get("title")
		r["nature"] = meta.get("nature")
		r["listing_status"] = meta.get("status")
		r["latest_version"] = meta.get("version")
	return rows


# --------------------------------------------------------------------------- #
# admin surface (System Manager ONLY — every check server-side)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def set_agent_roles(agent_slug: str, roles=None) -> dict:
	"""Restrict an agent listing to a set of Roles. System Manager only.

	``roles`` is a JSON array of Role names; ``[]`` clears the restriction
	(unrestricted). Roles are validated against the Role doctype; the
	non-grantable Administrator/Guest/All are rejected (All would silently mean
	unrestricted — force the explicit empty list instead)."""
	frappe.only_for("System Manager")
	parsed = roles
	if isinstance(parsed, str):
		try:
			parsed = frappe.parse_json(parsed)
		except Exception:
			frappe.throw(_("roles must be a JSON array of Role names."))
	if parsed is None:
		parsed = []
	if not isinstance(parsed, list):
		frappe.throw(_("roles must be a JSON array of Role names."))

	clean: list[str] = []
	for r in parsed:
		if not isinstance(r, str) or not r.strip():
			frappe.throw(_("roles must be a JSON array of Role names."))
		r = r.strip()
		if r in _NON_SELECTABLE_ROLES:
			frappe.throw(_("Role {0} cannot be used as an agent restriction.").format(r))
		if not frappe.db.exists("Role", r):
			frappe.throw(_("Role {0} does not exist.").format(r))
		if r not in clean:
			clean.append(r)

	doc = frappe.get_doc(LISTING, agent_slug)
	doc.check_permission("write")
	doc.set("allowed_roles", [{"role": r} for r in clean])
	doc.save()
	frappe.db.commit()
	return {"ok": True, "allowed_roles": [row.role for row in doc.allowed_roles]}


@frappe.whitelist()
def set_listing_status(agent_slug: str, status: str) -> dict:
	"""Set a listing's marketplace status. System Manager only. Only the
	admin-meaningful statuses are settable (Draft stays registry-controlled)."""
	frappe.only_for("System Manager")
	if status not in _ADMIN_STATUSES:
		frappe.throw(_("Status must be one of: {0}.").format(", ".join(_ADMIN_STATUSES)))
	doc = frappe.get_doc(LISTING, agent_slug)
	doc.check_permission("write")
	doc.status = status
	doc.save()
	frappe.db.commit()
	return {"ok": True, "status": doc.status}


@frappe.whitelist()
def get_agent_admin_overview() -> dict:
	"""Bench-admin overview: the selectable Roles + every listing with its
	allowed_roles and ALL owners' installs. System Manager only — the SPA probes
	this endpoint and hides the Admin tab when it throws PermissionError."""
	frappe.only_for("System Manager")

	roles = [
		r
		for r in frappe.get_all(
			"Role",
			filters={"disabled": 0, "desk_access": 1},
			order_by="name asc",
			pluck="name",
		)
		if r not in _NON_SELECTABLE_ROLES
	]

	roles_map = _allowed_roles_map()
	installs_by_agent: dict[str, list[dict]] = {}
	for i in frappe.get_all(
		INSTALLATION,
		fields=[
			"name", "agent", "owner", "enabled", "schedule_enabled",
			"schedule_frequency", "next_run_at", "last_run_at", "sync_status",
		],
		order_by="owner asc, creation asc",
	):
		installs_by_agent.setdefault(i.agent, []).append({
			"installation": i.name,
			"owner": i.owner,
			"enabled": int(i.enabled or 0),
			"schedule_enabled": int(i.schedule_enabled or 0),
			"schedule_frequency": i.schedule_frequency,
			"next_run_at": str(i.next_run_at) if i.next_run_at else None,
			"last_run_at": str(i.last_run_at) if i.last_run_at else None,
			"sync_status": i.sync_status,
		})

	listings = frappe.get_all(
		LISTING,
		fields=[
			"name", "agent_slug", "title", "nature", "category", "status",
			"version", "validated_for_fy",
		],
		order_by="status asc, title asc",
	)
	for lst in listings:
		lst["allowed_roles"] = roles_map.get(lst.name, [])
		lst["installs"] = installs_by_agent.get(lst.name, [])

	return {"roles": roles, "listings": listings}


# --------------------------------------------------------------------------- #
# install / enable / schedule / uninstall (mutations — all owner-gated)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def install_agent(agent_slug: str) -> dict:
	"""Install a Published agent for the current user. The doctype validate()
	enforces the per-owner cap + (owner, agent) uniqueness. Role-gated: a user
	whose roles do not intersect the listing's allowed_roles is refused
	server-side (System Manager always allowed)."""
	listing = frappe.get_doc(LISTING, agent_slug)  # All-role read
	me = frappe.session.user
	if not _user_allowed_for_agent(listing, me):
		frappe.throw(
			_("Your roles do not permit installing this agent."), frappe.PermissionError
		)
	if listing.status != "Published":
		frappe.throw(_("This agent is not available to install."))
	if frappe.db.exists(INSTALLATION, {"owner": me, "agent": listing.name}):
		frappe.throw(_("You have already installed this agent."))

	sched = {}
	try:
		sched = frappe.parse_json(listing.default_schedule) or {}
	except Exception:
		sched = {}
	freq = str(sched.get("schedule_frequency") or "daily").strip().lower()
	if freq not in _FREQUENCIES:
		freq = "daily"

	doc = frappe.get_doc({
		"doctype": INSTALLATION,
		"agent": listing.name,
		"enabled": 0,
		"installed_version": listing.version,
		"installed_at": frappe.utils.now(),
		"schedule_enabled": int(sched.get("schedule_enabled") or 0),
		"schedule_frequency": freq,
	})
	doc.insert()  # owner = me; validate() runs the cap/uniqueness checks
	frappe.db.commit()
	return {"ok": True, "data": {"name": doc.name, "agent": listing.name}}


@frappe.whitelist()
def set_enabled(installation: str, enabled: int) -> dict:
	"""Enable/disable an installed agent — a pure DB write (O6: NO restart; the
	bundle only reaches the container on the next Apply)."""
	doc = frappe.get_doc(INSTALLATION, installation)
	doc.check_permission("write")  # S3 owner-gate
	doc.enabled = int(enabled or 0)
	doc.save()
	frappe.db.commit()
	return {"ok": True, "data": {"name": doc.name, "enabled": doc.enabled}}


@frappe.whitelist()
def set_schedule(
	installation: str,
	schedule_enabled: int | None = None,
	schedule_frequency: str | None = None,
	schedule_time=None,
) -> dict:
	"""Set an installed agent's audit schedule — pure DB write (O6: no restart).
	Recomputes ``next_run_at`` when the schedule is enabled."""
	doc = frappe.get_doc(INSTALLATION, installation)
	doc.check_permission("write")  # S3 owner-gate
	if schedule_enabled is not None:
		doc.schedule_enabled = int(schedule_enabled or 0)
	if schedule_frequency is not None:
		freq = str(schedule_frequency).strip().lower()
		if freq not in _FREQUENCIES:
			frappe.throw(_("Frequency must be daily, weekly or monthly."))
		doc.schedule_frequency = freq
	if schedule_time is not None:
		doc.schedule_time = schedule_time or None

	if doc.schedule_enabled:
		doc.next_run_at = compute_next_run(doc.schedule_frequency, doc.schedule_time)
	doc.save()
	frappe.db.commit()
	return {
		"ok": True,
		"data": {"name": doc.name, "next_run_at": str(doc.next_run_at or "")},
	}


@frappe.whitelist()
def set_config(installation: str, config: str) -> dict:
	"""Persist an installed auditor's engagement / materiality config JSON — a
	pure DB write (O6: no restart; consumed by compute_materiality / run_scrutiny
	on the next audit). Owner-gated (S3). Validates the payload is a JSON object
	(keys: benchmark_value, percentage, engagement_risk_level, rounding_step, …)."""
	doc = frappe.get_doc(INSTALLATION, installation)
	doc.check_permission("write")  # S3 owner-gate
	try:
		parsed = frappe.parse_json(config) if config else {}
	except Exception:
		frappe.throw(_("Config must be valid JSON."))
	if not isinstance(parsed, dict):
		frappe.throw(_("Config must be a JSON object."))
	doc.config = frappe.as_json(parsed)
	doc.save()
	frappe.db.commit()
	return {"ok": True, "data": {"name": doc.name}}


@frappe.whitelist()
def uninstall_agent(installation: str) -> dict:
	"""Delete an installation (owner-gated). The bundle leaves the container on
	the next Apply (the fleet endpoint does a full reconcile)."""
	doc = frappe.get_doc(INSTALLATION, installation)
	doc.check_permission("delete")  # S3 owner-gate
	frappe.delete_doc(INSTALLATION, installation)  # honors if_owner
	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist()
def run_agent_now(installation: str) -> dict:
	"""Manual trigger: enqueue an audit turn NOW via the SAME code path the
	scheduler uses (``agent_scheduler._launch_audit``), executed UNDER THE
	INSTALLATION OWNER's identity — never the triggering user's.

	``check_permission`` gates WHO may trigger (owner, or a System Manager);
	but the audit's ``jarvis__*`` tool calls must always be scoped to the
	installation OWNER's permissions, so a System Manager triggering another
	owner's audit cannot run ERP reads with elevated rights. This mirrors the
	scheduler's S1 identity hinge on the manual path."""
	doc = frappe.get_doc(INSTALLATION, installation)
	doc.check_permission("write")  # S3: who may trigger
	# RBAC: the audit executes AS the installation OWNER, so it is the OWNER's
	# roles that must permit the agent (covers both a self-run by a user who
	# lost the role, and an SM triggering an install whose owner lost it — the
	# manual analogue of the scheduler's role skip). SM-owned installs pass via
	# the System Manager bypass inside the helper.
	if not _user_allowed_for_agent(doc.agent, doc.owner):
		frappe.throw(
			_("The installation owner's roles do not permit running this agent."),
			frappe.PermissionError,
		)
	if not doc.enabled:
		frappe.throw(_("Enable the agent before running it."))
	if frappe.db.get_value(LISTING, doc.agent, "nature") != "Auditor":
		frappe.throw(
			_("Only auditor agents run on demand; operators draft through the Approval Board.")
		)
	from jarvis.chat.agent_scheduler import _launch_audit, _valid_owner

	# Fail-closed identity guard: refuse to run an audit AS Administrator / Guest /
	# a disabled user ON SOMEONE ELSE'S behalf (the escalation a System Manager could
	# otherwise cause, and the unattended risk the scheduler faces). An owner running
	# their OWN install manually is attended + same-identity, so it is allowed — this
	# is how a single-admin dev / self-host box runs audits at all.
	if not _valid_owner(doc.owner) and doc.owner != frappe.session.user:
		frappe.throw(_("Cannot run this audit as the installation's owner (identity guard)."))

	original_user = frappe.session.user
	try:
		if doc.owner != original_user:
			frappe.set_user(doc.owner)
			doc = frappe.get_doc(INSTALLATION, installation)  # re-fetch under owner
		result = _launch_audit(doc, trigger="manual")
	finally:
		if frappe.session.user != original_user:
			frappe.set_user(original_user)
	return {"ok": True, "data": result}


# --------------------------------------------------------------------------- #
# runs + findings (read)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def list_runs(agent: str | None = None, limit: int = 50) -> list[dict]:
	"""This owner's run history (optionally filtered to one agent)."""
	me = frappe.session.user
	filters = {"owner": me}
	if agent:
		filters["agent"] = agent
	return frappe.get_all(
		RUN,
		filters=filters,
		fields=[
			"name", "agent", "installation", "trigger", "status", "started_at",
			"finished_at", "conversation", "findings_count", "blocker_count",
			"error", "coverage_note",
		],
		order_by="creation desc",
		limit=int(limit or 50),
	)


@frappe.whitelist()
def list_findings(
	run: str | None = None, state: str | None = None, limit: int = 100
) -> list[dict]:
	"""This owner's persisted findings (optionally filtered by run and/or state).

	``run`` means "the findings that run OBSERVED", not "rows whose ``run`` field
	is that run": ``record_scrutiny_run`` dedupes re-detections into the EXISTING
	Finding row (bumping ``last_seen_run``), so filtering on the ``run`` column
	alone returns rows only for the FIRST run that discovered each finding while
	the newer Run's ``findings_count`` still counts them. Dedupe only ever bumps
	``last_seen_run`` while a finding stays open, and a finding NOT seen by a
	recording run is auto-resolved (a later re-detection starts a NEW row), so a
	row's observed runs are exactly the recording runs of its (owner, agent)
	whose creation falls inside the ``[first_seen_run, last_seen_run]`` span —
	which keeps this drill-down consistent with the Runs-table counts."""
	me = frappe.session.user
	filters = {"owner": me}
	if run:
		run_row = frappe.db.get_value(RUN, run, ["agent", "creation", "status"], as_dict=True)
		if not run_row or run_row.status not in ("completed", "partial"):
			# unknown / failed / still-running runs recorded no findings snapshot
			# (findings_count is 0 there too — the drill-down must match).
			return []
		observed = frappe.db.sql(
			"""SELECT f.name FROM `tabJarvis Agent Finding` f
			JOIN `tabJarvis Agent Run` fr ON fr.name = f.first_seen_run
			JOIN `tabJarvis Agent Run` lr ON lr.name = f.last_seen_run
			WHERE f.owner = %(me)s AND f.agent = %(agent)s
			  AND fr.creation <= %(rc)s AND lr.creation >= %(rc)s""",
			{"me": me, "agent": run_row.agent, "rc": run_row.creation},
			pluck=True,
		)
		if not observed:
			return []
		filters["name"] = ["in", observed]
	if state:
		filters["state"] = state
	return frappe.get_all(
		FINDING,
		filters=filters,
		fields=[
			"name", "run", "agent", "rule_id", "severity", "title", "detail_md",
			"section", "effective_date", "ref_doctype", "ref_name", "amount",
			"state", "first_seen_run", "last_seen_run", "modified",
		],
		order_by="modified desc",
		limit=int(limit or 100),
	)


@frappe.whitelist()
def set_finding_state(finding: str, state: str) -> dict:
	"""Move a finding to open/acknowledged/resolved. Owner-gated (S3)."""
	if state not in ("open", "acknowledged", "resolved"):
		frappe.throw(_("Invalid finding state."))
	doc = frappe.get_doc(FINDING, finding)
	doc.check_permission("write")  # S3 owner-gate
	doc.state = state
	doc.save()
	frappe.db.commit()
	return {"ok": True, "data": {"name": doc.name, "state": state}}


# --------------------------------------------------------------------------- #
# Apply (explicit push to the container, via admin -> fleet) + status poller
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def get_agents_sync_status() -> dict:
	"""Lightweight poller mirroring get_custom_skills_sync_status."""
	s = frappe.get_single(_SETTINGS)
	status = s.get("agent_skills_sync_status") or ""
	return {
		"last_sync_at": str(s.get("agent_skills_synced_at") or ""),
		"last_sync_status": status,
		"pending": status.startswith("pending:"),
	}


@frappe.whitelist()
def apply_agents() -> dict:
	"""Push all ENABLED installed agent bundles to the container (one restart).
	Explicit action. Builds the payload synchronously (surfaces size/cap errors
	immediately), marks pending, then enqueues the deduped redis-locked worker —
	mirrors ``custom_skills_api.apply_custom_skills``."""
	_rate_limit_apply()
	payload = build_agent_push_payload()
	frappe.db.set_single_value(_SETTINGS, "agent_skills_sync_status", "pending: applying agents")
	frappe.db.commit()
	run_inline = bool(frappe.flags.in_test or frappe.flags.run_admin_sync_inline)
	frappe.enqueue(
		"jarvis.chat.agents_api._enqueued_push_agent_skills",
		queue="long",
		timeout=180,
		enqueue_after_commit=not run_inline,
		now=run_inline,
		job_id=_PUSH_JOB_ID,
		deduplicate=True,
	)
	return {
		"ok": True,
		"agent_skills_sync_status": "pending: applying agents",
		"count": len(payload),
	}


def _rate_limit_apply() -> None:
	"""Simple per-user redis guard so a double-click / script can't storm the
	admin -> fleet -> restart chain (S3). The deduped enqueue already coalesces;
	this rejects the second call outright within a short window."""
	if frappe.flags.in_test:
		return
	me = frappe.session.user
	key = f"jarvis_apply_agents_rl:{me}"
	if frappe.cache().get_value(key):
		frappe.throw(_("An apply is already in progress — please wait a moment."))
	frappe.cache().set_value(key, "1", expires_in_sec=5)


def _enqueued_push_agent_skills() -> None:
	"""Background worker: push the enabled agent bundles via admin -> fleet ->
	container. Re-builds the payload fresh (never trust a payload across the
	queue boundary) and mirrors ``_enqueued_push_custom_skills``'s
	try/except/finally so the status never stays ``pending:`` forever."""
	from jarvis import admin_client
	from jarvis._redis_lock import redis_lock

	with redis_lock(_LOCK_NAME, timeout_s=180, blocking_timeout_s=60.0) as acquired:
		if not acquired:
			frappe.db.set_single_value(
				_SETTINGS, "agent_skills_sync_status", "failed: skipped (concurrent sync)"
			)
			frappe.db.commit()
			return

		terminal_written = False
		try:
			payload = build_agent_push_payload()
			admin_client.post_push_agent_skills(agent_skills=payload)
			frappe.db.set_value(
				_SETTINGS,
				_SETTINGS,
				{
					"agent_skills_synced_at": frappe.utils.now(),
					"agent_skills_sync_status": f"ok (applied {len(payload)} via admin)",
				},
			)
			terminal_written = True
		except admin_client.AdminAuthError as e:
			_fail(f"failed: auth: {e}")
			terminal_written = True
			frappe.log_error(title="Jarvis: agent-skills admin auth failed", message=frappe.get_traceback())
		except admin_client.AdminUnreachableError as e:
			_fail(f"failed: admin unreachable: {e}")
			terminal_written = True
			frappe.log_error(title="Jarvis: agent-skills admin unreachable", message=frappe.get_traceback())
		except admin_client.AdminRateLimitedError as e:
			retry = getattr(e, "retry_after_seconds", 0) or 0
			retry_str = f"retry_after={retry}s" if retry > 0 else "retry shortly"
			_fail(f"failed: rate-limited; {retry_str}")
			terminal_written = True
		except admin_client.AdminValidationError as e:
			_fail(f"failed: invalid: {e}")
			terminal_written = True
		except Exception:
			_fail("failed: unexpected error; see Error Log")
			terminal_written = True
			frappe.log_error(title="Jarvis: agent-skills push failed", message=frappe.get_traceback())
		finally:
			if not terminal_written:
				try:
					_fail("failed: unexpected error; see Error Log")
				except Exception:
					pass
		frappe.db.commit()


def _fail(status: str) -> None:
	frappe.db.set_value(
		_SETTINGS,
		_SETTINGS,
		{"agent_skills_synced_at": frappe.utils.now(), "agent_skills_sync_status": status},
	)
