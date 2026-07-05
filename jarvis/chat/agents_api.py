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
_SETTINGS = "Jarvis Settings"
_PUSH_JOB_ID = "jarvis_agent_skills_push"
_LOCK_NAME = "jarvis_agent_skills_push"

_FREQUENCIES = ("daily", "weekly", "monthly")


# --------------------------------------------------------------------------- #
# catalog + install state (read)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def list_agents() -> list[dict]:
	"""The full catalog plus THIS owner's install/enable/schedule state per
	agent. Read-only — the catalog is visible to every logged-in user."""
	me = frappe.session.user
	listings = frappe.get_all(
		LISTING,
		fields=[
			"name", "agent_slug", "title", "description", "category", "nature",
			"version", "publisher", "status", "rule_pack", "default_schedule",
			"validated_for_fy",
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
		out.append(lst)
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
# install / enable / schedule / uninstall (mutations — all owner-gated)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def install_agent(agent_slug: str) -> dict:
	"""Install a Published agent for the current user. The doctype validate()
	enforces the per-owner cap + (owner, agent) uniqueness."""
	listing = frappe.get_doc(LISTING, agent_slug)  # All-role read
	if listing.status != "Published":
		frappe.throw(_("This agent is not available to install."))
	me = frappe.session.user
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
	if not doc.enabled:
		frappe.throw(_("Enable the agent before running it."))
	if frappe.db.get_value(LISTING, doc.agent, "nature") != "Auditor":
		frappe.throw(
			_("Only auditor agents run on demand; operators draft through the Approval Board.")
		)
	from jarvis.chat.agent_scheduler import _launch_audit, _valid_owner

	# Fail-closed identity guard (same as the scheduler): never run an audit
	# turn as Administrator/Guest/a disabled user, even on the manual path.
	if not _valid_owner(doc.owner):
		frappe.throw(_("This installation's owner cannot run audits (identity guard)."))

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
	"""This owner's persisted findings (optionally filtered by run and/or state)."""
	me = frappe.session.user
	filters = {"owner": me}
	if run:
		filters["run"] = run
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
