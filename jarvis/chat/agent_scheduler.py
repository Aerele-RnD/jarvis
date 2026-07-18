"""Scheduled auditor runs — the identity-safe agent scheduler.

An hourly cron (``jarvis.hooks.scheduler_events``) calls
:func:`run_due_agent_audits`, which fires every enabled AUDITOR installation
whose ``next_run_at`` has passed. Modeled on
``jarvis.chat.macro_scheduler.run_due_macros`` but hardened per the adversarial
review:

* **S1 (THE HINGE):** the audit conversation + triggering message row are
  created INSIDE ``frappe.set_user(installation.owner)`` (try/finally that
  restores the user). Frappe scheduler jobs run as Administrator with no
  session; a ``jarvis__*`` call runs as the DB owner of the triggering message
  row, so binding it to Administrator would bypass every DocType permission,
  silently, unattended. A fail-closed guard REFUSES to bind a scheduled audit
  to Administrator / Guest / a disabled user.
* **O1:** a per-owner monthly scheduled-scan budget (skip + record ``failed``
  when over budget), so scheduled scans can't drain the customer's own
  subscription.
* **O3:** the turn is dispatched ``background=1`` (unattended), so it never
  jumps ahead of a human's queued question.
* **O4:** ``next_run_at`` advances ONLY after a successful enqueue; on failure a
  ``failed`` run is recorded + the owner notified, and the missed slot is NOT
  backfilled (``compute_next_run`` from *now* yields a single next future slot).
* **O7:** identical ``(owner, agent, cadence, time)`` due rows are deduped.

``_launch_audit`` is shared with ``agents_api.run_agent_now`` so a manual
trigger takes the EXACT same code path as the scheduler.
"""

import frappe
from frappe.utils import now_datetime

from jarvis.chat.agent_activity import log_activity
from jarvis.chat.macro_scheduler import compute_next_run

INSTALLATION = "Jarvis Agent Installation"
LISTING = "Jarvis Agent Listing"
RUN = "Jarvis Agent Run"
CONV = "Jarvis Conversation"

# O1: a simple constant monthly cap on SCHEDULED scans per owner (interactive /
# manual runs are not counted). Keep it simple for v1 but present.
MAX_SCHEDULED_RUNS_PER_OWNER_PER_MONTH = 60


# --------------------------------------------------------------------------- #
# hourly cron
# --------------------------------------------------------------------------- #
def run_due_agent_audits() -> None:
	"""Run every enabled auditor installation whose next_run_at is due. Runs as
	Administrator (the scheduler user); each audit executes as its own owner."""
	now = now_datetime()
	due = frappe.get_all(
		INSTALLATION,
		filters={"enabled": 1, "schedule_enabled": 1, "next_run_at": ["<=", now]},
		fields=["name", "owner", "run_as_user", "agent", "schedule_frequency", "schedule_time"],
	)
	if not due:
		return

	from jarvis.chat.agents_api import _user_allowed_for_agent

	original_user = frappe.session.user
	seen: set = set()  # O7: dedupe identical (owner, agent, cadence, time)
	for row in due:
		key = (row.owner, row.agent, row.schedule_frequency, str(row.schedule_time))
		if key in seen:
			_advance(row, now)
			continue
		seen.add(key)

		# Only auditor agents run scheduled scans; an operator install with a
		# schedule set just consumes its slot (it drafts through the board, not
		# on a cron).
		if frappe.db.get_value(LISTING, row.agent, "nature") != "Auditor":
			_advance(row, now)
			continue

		# Phase 1 identity: the audit executes AS the install's run_as_user (its
		# jarvis__* reads are permission-bounded to that user). Falls back to
		# owner for installs from before run_as_user / the A13 backfill.
		run_as = row.run_as_user or row.owner

		# S1 fail-closed identity guard — never bind a scheduled audit turn to
		# Administrator / Guest / a disabled RUN-AS user.
		if not _valid_owner(run_as):
			_record_failed(row, "scheduled audit skipped: invalid run-as user (fail-closed guard)")
			_advance(row, now)
			continue

		# RBAC: the listing may have been restricted (or the run-as user's roles
		# revoked) AFTER install. Skip, record WHY, and consume the slot — never
		# dispatch a turn for a run-as identity the agent no longer permits
		# (gotcha #8 — the EXECUTING identity is gated, not the triggerer).
		if not _user_allowed_for_agent(row.agent, run_as):
			_record_failed(row, "run-as user's roles no longer permit this agent")
			_advance(row, now)
			continue

		# O1 cost cap (per human owner — the subscription is theirs).
		if _scheduled_runs_this_month(row.owner) >= MAX_SCHEDULED_RUNS_PER_OWNER_PER_MONTH:
			_record_failed(row, "scheduled scan budget exceeded")
			_advance(row, now)
			continue

		# S1 hinge: mint the run session + create conv/run INSIDE set_user(run_as).
		# Row ownership is reassigned to the human owner inside _launch_audit; only
		# the ERP-read identity is the run-as user.
		try:
			frappe.set_user(run_as)
			inst = frappe.get_doc(INSTALLATION, row.name)
			_launch_audit(inst, trigger="scheduled")
			frappe.set_user(original_user)
			_advance(row, now)  # O4: advance ONLY after a successful enqueue
		except Exception:
			frappe.set_user(original_user)
			frappe.log_error(
				title=f"jarvis scheduled audit failed: {row.name}",
				message=frappe.get_traceback(),
			)
			_record_failed(row, "scheduled audit enqueue failed; see Error Log")
			_notify_owner(row.owner, row)
			# Do NOT advance -> retry next hour. compute_next_run(from=now) means
			# even a long outage yields ONE next slot, never a backfill storm.
		finally:
			if frappe.session.user != original_user:
				frappe.set_user(original_user)


# --------------------------------------------------------------------------- #
# shared launch (scheduler + manual run_agent_now take the SAME path)
# --------------------------------------------------------------------------- #
def _launch_audit(inst, trigger: str) -> dict:
	"""Create the audit conversation + a ``running`` Jarvis Agent Run + enqueue
	the triggering turn. MUST run as the installation owner (the scheduler
	set_user's it; run_agent_now is already the owner). Returns
	``{run, conversation}``. Identity/budget guards + next_run_at advancement are
	the caller's job."""
	from jarvis.chat import api

	listing = frappe.get_doc(LISTING, inst.agent)
	owner = inst.owner
	# Phase 1 identity: the run's ERP-read identity. The caller (scheduler /
	# run_agent_now) has already switched the session to this user, so
	# frappe.session.user == run_as_user here — scope + watermark below are
	# resolved AS the run-as user (permission-bounded).
	run_as_user = inst.run_as_user or owner

	# Fresh conversation. ROW ownership is the human owner (reassigned below) so
	# if_owner visibility works; the ERP-read identity is the run-as user.
	# ignore_permissions matches the macro engine.
	conv = frappe.get_doc({"doctype": CONV, "title": f"{listing.title} audit"[:140], "status": "Active"})
	conv.flags.ignore_permissions = True
	conv.insert()

	run = frappe.get_doc({
		"doctype": RUN,
		"agent": inst.agent,
		"installation": inst.name,
		"trigger": trigger,
		"status": "running",
		"conversation": conv.name,
		"started_at": frappe.utils.now(),
	})
	run.flags.ignore_permissions = True
	run.insert()

	# Defensive: hand the row-owned rows to the intended HUMAN owner (mirrors
	# macros.run_macro). When run_as_user != owner the session user here is the
	# run-as user, so this reassignment is what keeps row ownership = owner.
	if owner != frappe.session.user:
		for dt, name in ((CONV, conv.name), (RUN, run.name)):
			frappe.db.set_value(dt, name, "owner", owner, update_modified=False)

	# Phase 1: mint a per-run Jarvis Chat Session bound to the RUN-AS user and
	# stamp it on the Run. This is the row the delegate's jarvis__* calls resolve
	# their identity from (api.py:44-141 → impersonate(run_as_user)). The dispatch
	# itself is stubbed until Phase 2; the session + scope + watermark are the
	# Phase-1 deliverable.
	slug = listing.agent_slug
	# openclaw session keys are `agent:<agent-id>:<key>` and the gateway resolves
	# the session under that agent-id. The delegate agent id is `agent-<slug>`
	# (fleet-agent compose.agent_delegates), so the id component MUST be the full
	# delegate id, not the bare slug — otherwise the gateway `agent` RPC's
	# agentId (`agent-<slug>`) and the session key's embedded id (`<slug>`)
	# disagree. The bench never parses this shape (it matches the Jarvis Chat
	# Session row verbatim), so aligning it is free on the bench side and correct
	# on the openclaw side.
	session_key = f"agent:agent-{slug}:{run.name}"
	_mint_run_session(session_key, run_as_user)
	frappe.db.set_value(RUN, run.name, "session_key", session_key, update_modified=False)

	# A6 explicit scope + A17 consistency watermark + A12 permission profile —
	# all best-effort (never abort the launch) and computed AS the run-as user.
	scope = _stamp_scope_and_watermark(run.name, inst, run_as_user)

	frappe.db.commit()

	# Activity trail (best-effort, Link-free): row is owner-scoped like the run.
	log_activity(
		agent=inst.agent,
		agent_title=listing.title,
		installation=inst.name,
		action="run_started",
		run=run.name,
		detail=f"trigger: {trigger}",
	)

	# O3: dispatch as an unattended background turn (interactive=False) so it
	# never jumps ahead of a human's queued question. delegated_send() marks
	# this as a trusted server re-entry so send_message's Jarvis-access gate
	# (and the now role-gated Message create perm) accept it even when the
	# impersonated owner does not hold the Jarvis User role.
	from jarvis.permissions import delegated_send

	with delegated_send():
		result = api.send_message(
			conversation=conv.name,
			message=_audit_prompt(listing, inst, trigger, scope),
			background=1,
		)
	if not result.get("ok"):
		raise RuntimeError(f"send_message refused: {result.get('reason')}")
	return {"run": run.name, "conversation": conv.name, "session_key": session_key}


# --------------------------------------------------------------------------- #
# Phase 1 identity helpers — per-run session, scope, watermark, perm-profile
# --------------------------------------------------------------------------- #
def _mint_run_session(session_key: str, user: str) -> None:
	"""Insert the per-run ``Jarvis Chat Session`` row that maps session_key →
	run-as user, mirroring ``chat/api._ensure_session_key``'s shape: snapshot the
	bench's current ``chat_device_id`` so a re-pair invalidates the row (the
	device-binding check at ``api.py:106-139``). ignore_permissions — this is
	trusted server infrastructure, and session_key is unique (run.name is a hash)."""
	device_id = (
		frappe.db.get_single_value("Jarvis Settings", "chat_device_id") or ""
	).strip()
	frappe.get_doc({
		"doctype": "Jarvis Chat Session",
		"session_key": session_key,
		"user": user,
		"chat_device_id": device_id,
	}).insert(ignore_permissions=True)


def _stamp_scope_and_watermark(run_name: str, inst, run_as_user: str) -> dict | None:
	"""Resolve the explicit scope (A6), compute the GL consistency watermark
	(A17) and the run-as permission profile (A12), and stamp them on the Run.

	All best-effort: a bench without a resolvable Company (e.g. no erpnext setup)
	must NOT abort the launch — it degrades to an unscoped run (no watermark). The
	watermark + scope are resolved AS the run-as user (this runs under that
	session). Returns the resolved scope dict (or None)."""
	from jarvis.chat import agent_scope

	values: dict = {}
	scope = None
	try:
		scope = agent_scope.resolve_scope(inst)
		values["scope_json"] = frappe.as_json(scope)
	except Exception:
		frappe.log_error(
			title="jarvis agent: scope resolution failed (unscoped run)",
			message=frappe.get_traceback(),
		)

	if scope and scope.get("company") and scope.get("to_date"):
		# A17: row-count + max(modified) over the scope's GL as-of window. The old
		# engine ran the whole pack in one snapshot; the chunked container run
		# spans minutes, so a mid-run backdated JV (endemic at Indian year-end)
		# is caught by recomputing this at writeback (Phase 3) and comparing.
		try:
			wm = frappe.db.sql(
				"""select count(*) n, max(modified) m from `tabGL Entry`
				   where company = %(company)s and posting_date <= %(to_date)s""",
				{"company": scope["company"], "to_date": scope["to_date"]},
				as_dict=True,
			)[0]
			values["wm_row_count"] = int(wm.n or 0)
			values["wm_gl_max_modified"] = wm.m
		except Exception:
			frappe.log_error(
				title="jarvis agent: GL watermark computation failed",
				message=frappe.get_traceback(),
			)

	try:
		values["permission_profile"] = _permission_profile(run_as_user)
	except Exception:
		pass

	if values:
		frappe.db.set_value(RUN, run_name, values, update_modified=False)
	return scope


def _permission_profile(user: str) -> str:
	"""A compact JSON summary + sha256 of the run-as user's roles + user-permission
	keys, so a drift between mapping-time and run-time perms is detectable (A12)."""
	import hashlib
	import json

	from frappe.permissions import get_user_permissions

	roles = sorted(frappe.get_roles(user))
	try:
		perms = get_user_permissions(user) or {}
	except Exception:
		perms = {}
	up_keys: dict = {}
	for dt, entries in perms.items():
		vals = sorted(
			{
				(e.get("doc") if isinstance(e, dict) else str(e))
				for e in (entries or [])
			}
		)
		up_keys[dt] = [v for v in vals if v]
	summary = {"roles": roles, "user_permissions": up_keys}
	digest = hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest()
	return json.dumps({"hash": digest, **summary})


def _audit_prompt(listing, inst, trigger: str, scope: dict | None = None) -> str:
	cfg = ""
	try:
		parsed = frappe.parse_json(inst.config) if inst.config else None
		if parsed:
			cfg = f"\n\nEngagement config: {frappe.as_json(parsed)}"
	except Exception:
		cfg = ""
	slug = listing.agent_slug
	# A6: inject the EXPLICIT resolved scope verbatim so the container bundle
	# never infers "the current period" (a UTC container clock vs an IST site
	# picks the wrong FY for ~5.5h/day). Phase 2C rewrites the run_scrutiny
	# reference below into a generic, non-leaky prompt.
	scope_block = ""
	if scope:
		scope_block = (
			"\n\nEXPLICIT SCOPE (use these EXACT values; never infer the period): "
			f"company=\"{scope.get('company')}\", "
			f"fiscal_year=\"{scope.get('fiscal_year')}\", "
			f"from_date=\"{scope.get('from_date')}\", "
			f"to_date=\"{scope.get('to_date')}\", "
			f"prior_fy_start=\"{scope.get('prior_fy_start')}\", "
			f"prior_fy_end=\"{scope.get('prior_fy_end')}\"."
		)
	return (
		f"[Automated {trigger} audit] Run the {listing.title} ({slug}) now for the scope below. "
		f"Follow your agent-{slug} skill exactly: compute engagement materiality, then call "
		f"jarvis__run_scrutiny for domain \"{listing.category}\" — and pass "
		f"installation=\"{inst.name}\" to it so your findings are recorded — then report the "
		f"severity-tagged findings summary it returns. Read-only — never write."
		f"{scope_block}{cfg}"
	)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _valid_owner(owner: str) -> bool:
	if not owner or owner in ("Administrator", "Guest"):
		return False
	return bool(frappe.db.get_value("User", owner, "enabled"))


def _scheduled_runs_this_month(owner: str) -> int:
	month_start = frappe.utils.get_first_day(frappe.utils.today())
	return frappe.db.count(
		RUN, {"owner": owner, "trigger": "scheduled", "creation": [">=", month_start]}
	)


def _advance(row, now) -> None:
	"""Advance the schedule with a raw set_value (no re-validate). ``last_run_at``
	is stamped whether the slot produced a real, failed, or skipped run — the
	slot was consumed either way."""
	frappe.db.set_value(
		INSTALLATION,
		row.name,
		{
			"last_run_at": now,
			"next_run_at": compute_next_run(row.schedule_frequency, row.schedule_time, from_dt=now),
		},
		update_modified=False,
	)
	frappe.db.commit()


def _record_failed(row, reason: str) -> None:
	"""Write a ``failed`` Jarvis Agent Run row (owned by the installation owner)
	so the customer sees WHY a scheduled slot did not run."""
	run = frappe.get_doc({
		"doctype": RUN,
		"agent": row.agent,
		"installation": row.name,
		"trigger": "scheduled",
		"status": "failed",
		"started_at": frappe.utils.now(),
		"finished_at": frappe.utils.now(),
		"error": (reason or "")[:140],
	})
	run.flags.ignore_permissions = True
	run.insert()
	if row.owner and row.owner != frappe.session.user:
		frappe.db.set_value(RUN, run.name, "owner", row.owner, update_modified=False)
	# Activity trail (best-effort, Link-free) — every other run outcome logs
	# one; the explicit owner keeps the feed row owner-scoped even though the
	# scheduler runs as Administrator.
	log_activity(
		agent=row.agent,
		agent_title=frappe.db.get_value(LISTING, row.agent, "title"),
		installation=row.name,
		action="run_failed",
		run=run.name,
		detail=(reason or "")[:140],
		owner=row.owner,
	)
	frappe.db.commit()


def _notify_owner(owner: str, row) -> None:
	"""Best-effort owner notification on enqueue failure (never raises)."""
	if not _valid_owner(owner):
		return
	try:
		frappe.get_doc({
			"doctype": "Notification Log",
			"for_user": owner,
			"type": "Alert",
			"subject": f"Scheduled audit could not start: {row.agent}",
			"email_content": (
				"A scheduled agent audit could not be started. It will retry on the "
				"next hourly run."
			),
		}).insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		pass
