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
		fields=["name", "owner", "agent", "schedule_frequency", "schedule_time"],
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

		# S1 fail-closed identity guard — never bind a scheduled audit turn to
		# Administrator / Guest / a disabled user.
		if not _valid_owner(row.owner):
			_record_failed(row, "scheduled audit skipped: invalid owner (fail-closed guard)")
			_advance(row, now)
			continue

		# RBAC: the listing may have been restricted (or the owner's roles
		# revoked) AFTER install. Skip, record WHY, and consume the slot — never
		# dispatch a turn for an owner the agent no longer permits.
		if not _user_allowed_for_agent(row.agent, row.owner):
			_record_failed(row, "owner's roles no longer permit this agent")
			_advance(row, now)
			continue

		# O1 cost cap.
		if _scheduled_runs_this_month(row.owner) >= MAX_SCHEDULED_RUNS_PER_OWNER_PER_MONTH:
			_record_failed(row, "scheduled scan budget exceeded")
			_advance(row, now)
			continue

		# S1 hinge: create conv + message row INSIDE set_user(owner).
		try:
			frappe.set_user(row.owner)
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

	# Fresh conversation, owned by the owner (we run under set_user(owner) / the
	# owner is the caller). ignore_permissions matches the macro engine.
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

	# Defensive: if launched on behalf of another user, hand the owner-scoped
	# rows to the intended owner (mirrors macros.run_macro).
	if owner != frappe.session.user:
		for dt, name in ((CONV, conv.name), (RUN, run.name)):
			frappe.db.set_value(dt, name, "owner", owner, update_modified=False)
	frappe.db.commit()

	# Activity trail (best-effort, Link-free): we run under set_user(owner) /
	# as the owner, so the feed row is owner-scoped like the run itself.
	log_activity(
		agent=inst.agent,
		agent_title=listing.title,
		installation=inst.name,
		action="run_started",
		run=run.name,
		detail=f"trigger: {trigger}",
	)

	# O3: dispatch as an unattended background turn (interactive=False) so it
	# never jumps ahead of a human's queued question.
	result = api.send_message(
		conversation=conv.name,
		message=_audit_prompt(listing, inst, trigger),
		background=1,
	)
	if not result.get("ok"):
		raise RuntimeError(f"send_message refused: {result.get('reason')}")
	return {"run": run.name, "conversation": conv.name}


def _audit_prompt(listing, inst, trigger: str) -> str:
	cfg = ""
	try:
		parsed = frappe.parse_json(inst.config) if inst.config else None
		if parsed:
			cfg = f"\n\nEngagement config: {frappe.as_json(parsed)}"
	except Exception:
		cfg = ""
	slug = listing.agent_slug
	return (
		f"[Automated {trigger} audit] Run the {listing.title} ({slug}) now for the current period. "
		f"Follow your agent-{slug} skill exactly: compute engagement materiality, then call "
		f"jarvis__run_scrutiny for domain \"{listing.category}\" — and pass "
		f"installation=\"{inst.name}\" to it so your findings are recorded — then report the "
		f"severity-tagged findings summary it returns. Read-only — never write.{cfg}"
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
