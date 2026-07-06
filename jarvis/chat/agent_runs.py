"""Deterministic Run + Findings persistence for the audit agents (O2).

``record_scrutiny_run`` writes ONE ``Jarvis Agent Run`` + N ``Jarvis Agent
Finding`` rows from a ``run_scrutiny`` result dict. It is DETERMINISTIC server
code, NOT model-mediated: the auditor SKILL narrates the transcript, but the
stored, severity-tagged, deduped finding rows are the reproducibility guarantee
(same scrutiny result -> same rows, re-runnable by a peer reviewer).

Findings dedupe across runs on a stable ``fingerprint`` (sha256 of
``rule_id + ref_doctype + ref_name``): a finding still ``open`` from a prior run
has its ``last_seen_run`` bumped instead of being duplicated, and a prior open
finding NOT seen this run is auto-``resolved``. ``status=partial`` marks a scan
that hit the turn envelope (never masquerades as ``completed``).
"""

import hashlib

import frappe
from frappe.utils import getdate

from jarvis.chat.agent_activity import log_activity
from jarvis.chat.macro_scheduler import compute_next_run

RUN = "Jarvis Agent Run"
FINDING = "Jarvis Agent Finding"
INSTALLATION = "Jarvis Agent Installation"
LISTING = "Jarvis Agent Listing"


def _fingerprint(rule_id, ref_doctype, ref_name) -> str:
	"""Stable dedupe key for a finding — identity only (rule + the doc it hit),
	NOT the amount (which can drift run to run while it stays the same finding)."""
	raw = "|".join([str(rule_id or ""), str(ref_doctype or ""), str(ref_name or "")])
	return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _safe_date(value):
	if not value:
		return None
	try:
		return getdate(value)
	except Exception:
		return None


def _reassign_owner(doctype: str, name: str, owner: str) -> None:
	"""Hand a server-inserted (ignore_permissions) row to the installation owner
	so ``if_owner`` shows it to the right customer only — mirrors macros.py."""
	if owner and owner != frappe.session.user:
		frappe.db.set_value(doctype, name, "owner", owner, update_modified=False)


def record_scrutiny_run(
	installation,
	trigger: str,
	conversation,
	scrutiny_result: dict,
	*,
	run=None,
	truncated: bool = False,
):
	"""Persist one run + its findings deterministically. Returns the Run doc.

	Args:
		installation: name or doc of the ``Jarvis Agent Installation``.
		trigger: ``"scheduled"`` | ``"manual"``.
		conversation: ``Jarvis Conversation`` name (or ``None``).
		scrutiny_result: the dict ``run_scrutiny()`` returned
			(``{findings:[{rule_id, severity, statement, section, effective_date,
			ref_doctype, ref_name, amount, detail}], ...}``).
		run: an existing ``running`` run to finalize (the scheduler creates one
			when it launches the turn); a fresh run is created when omitted.
		truncated: ``True`` when the audit turn hit its envelope -> ``partial``.
	"""
	inst = installation if hasattr(installation, "owner") else frappe.get_doc(INSTALLATION, installation)
	owner = inst.owner
	agent = inst.agent
	result = scrutiny_result or {}
	findings = result.get("findings") or []

	# The run row (create fresh, or reuse the scheduler-created running one).
	if run is None:
		run_doc = frappe.get_doc({
			"doctype": RUN,
			"agent": agent,
			"installation": inst.name,
			"trigger": trigger,
			"conversation": conversation,
			"status": "running",
			"started_at": frappe.utils.now(),
		})
		run_doc.flags.ignore_permissions = True
		run_doc.insert()
		_reassign_owner(RUN, run_doc.name, owner)
	else:
		run_doc = run if hasattr(run, "name") else frappe.get_doc(RUN, run)

	# Collapse this run's findings by fingerprint FIRST: a document flagged
	# twice by the same rule (e.g. one invoice oversized against two income
	# ledgers) is ONE finding — fingerprint is rule+doc identity. Deduping up
	# front keeps findings_count / blocker_count consistent with the rows
	# actually persisted (else a raw count over-reports vs the stored findings).
	by_fp = {}
	for f in findings:
		fp = _fingerprint(f.get("rule_id"), f.get("ref_doctype"), f.get("ref_name"))
		by_fp.setdefault(fp, f)
	seen_fps = set(by_fp)

	# Persist findings.
	counts = {"blocker": 0, "warning": 0, "note": 0}
	for fp, f in by_fp.items():
		sev = f.get("severity") or "note"
		counts[sev] = counts.get(sev, 0) + 1

		existing = frappe.db.get_value(
			FINDING,
			{"owner": owner, "agent": agent, "fingerprint": fp, "state": "open"},
			"name",
		)
		if existing:
			# Recurring finding: bump last_seen_run, keep it open (no dup row).
			frappe.db.set_value(FINDING, existing, "last_seen_run", run_doc.name, update_modified=False)
			continue

		fd = frappe.get_doc({
			"doctype": FINDING,
			"run": run_doc.name,
			"agent": agent,
			"rule_id": f.get("rule_id"),
			"severity": sev,
			"title": (f.get("statement") or f.get("detail") or f.get("rule_id") or "")[:140],
			"detail_md": f.get("detail") or "",
			"section": f.get("section") or "",
			"effective_date": _safe_date(f.get("effective_date")),
			"ref_doctype": f.get("ref_doctype") or "",
			"ref_name": f.get("ref_name") or "",
			"amount": f.get("amount") or 0,
			"disclaimer": f.get("disclaimer") or "",
			"fingerprint": fp,
			"state": "open",
			"first_seen_run": run_doc.name,
			"last_seen_run": run_doc.name,
		})
		fd.flags.ignore_permissions = True
		fd.insert()
		_reassign_owner(FINDING, fd.name, owner)

	# Auto-resolve prior open findings for this (owner, agent) not seen this run.
	stale_filters = {"owner": owner, "agent": agent, "state": "open"}
	if seen_fps:
		stale_filters["fingerprint"] = ["not in", list(seen_fps)]
	for name in frappe.get_all(FINDING, filters=stale_filters, pluck="name"):
		frappe.db.set_value(FINDING, name, "state", "resolved", update_modified=False)

	# Finalize the run.
	status = "partial" if truncated else "completed"
	coverage = result.get("coverage_note") or ""
	if truncated and not coverage:
		coverage = "Scan hit the turn envelope; findings list is incomplete."
	frappe.db.set_value(RUN, run_doc.name, {
		"status": status,
		"findings_count": len(seen_fps),  # distinct persisted findings (fingerprint-deduped)
		"blocker_count": counts.get("blocker", 0),
		"finished_at": frappe.utils.now(),
		"coverage_note": coverage[:140],
	}, update_modified=False)

	# Activity trail (best-effort, Link-free — survives the uninstall cascade).
	# The explicit ``owner`` pins the feed row to the installation owner (today
	# run_scrutiny enforces we ARE the owner, but a future non-owner caller must
	# never misattribute the row).
	log_activity(
		agent=agent,
		agent_title=frappe.db.get_value(LISTING, agent, "title"),
		installation=inst.name,
		action={"completed": "run_completed", "partial": "run_partial"}.get(status, "run_failed"),
		run=run_doc.name,
		detail=f"{len(seen_fps)} findings, {counts.get('blocker', 0)} blockers"
		+ (f"; {coverage}" if coverage else ""),
		owner=owner,
	)

	# Stamp the installation on completion, WHATEVER the trigger: this is the
	# single point where a run flips to completed/partial, so manual Run-Now
	# runs get a real ``last_run_at`` too (the scheduler's ``_advance`` only
	# stamps slot consumption at enqueue time; a manual run never passes it).
	# ``next_run_at`` is recomputed ONLY for scheduled installs — a manual-only
	# install must never grow a bogus next slot.
	inst_values = {"last_run_at": frappe.utils.now()}
	if inst.schedule_enabled:
		inst_values["next_run_at"] = compute_next_run(inst.schedule_frequency, inst.schedule_time)
	frappe.db.set_value(INSTALLATION, inst.name, inst_values, update_modified=False)
	frappe.db.commit()

	run_doc.reload()
	return run_doc
