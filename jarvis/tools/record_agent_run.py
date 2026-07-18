"""``jarvis__record_agent_run`` — the Phase-3 delegate findings writeback (A16/A17).

An auditor/operator DELEGATE runs its bundled deterministic evaluator over
permission-bounded ERP rollups and passes the evaluator's JSON output here
VERBATIM (the model never authors or edits a finding — A1/A2). This tool is the
bench-side landing:

  * It runs impersonated as the run's ``run_as_user`` (the plugin path resolved
    the caller's ``X-Jarvis-Session`` header to that user), so every ERP read
    below is permission-bounded.
  * It resolves the ``Jarvis Agent Run`` from the CALLER's session_key
    (``Run.session_key`` — never a model-supplied id), and refuses if there is no
    such run. A second call to a run that already finalized is a no-op that
    returns current state (idempotency).
  * It VALIDATES every finding before persisting (A16): the ``token`` must be in
    the agent's bench-held id-only manifest, ``ref_doctype`` in the agent's
    allowed set, ``ref_name`` must exist for the run-as user, ``amount`` numeric,
    ``severity`` ∈ {blocker,warning,note}. Invalid rows are DROPPED (never
    persisted unverifiable) and the run is marked partial with the rejected refs.
  * Persistence, coverage-scoped auto-resolve (A16) and the GL consistency
    watermark recheck (A17) happen in ``agent_runs.record_delegate_run``.

The valid ``token`` set + allowed ``ref_doctype`` set are the ONLY things the
bench holds about the rule pack — opaque tokens + declared doctypes, no rule
bodies, thresholds or predicates (A2 moat).
"""
from __future__ import annotations

import json

import frappe

from jarvis.exceptions import InvalidArgumentError

RUN = "Jarvis Agent Run"
LISTING = "Jarvis Agent Listing"
INSTALLATION = "Jarvis Agent Installation"

_SEVERITIES = {"blocker", "warning", "note"}
# Aggregate-dimension ref doctypes verified by EXISTENCE only, not a read-perm
# gate: ERPNext's Auditor role legitimately holds GL read but only `select` (not
# `read`) on Company, and Account is the same aggregate grain — mirrors
# run_scrutiny's company gate. Every OTHER ref doctype must be readable by the
# run-as user or the row is dropped (a mistranscribed / out-of-scope ref).
_PERM_EXEMPT_REFS = frozenset({"Company", "Account"})


def _as_list(value) -> list:
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except Exception:
			return []
	return value if isinstance(value, list) else []


def _as_dict(value) -> dict:
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except Exception:
			return {}
	return value if isinstance(value, dict) else {}


def _ref_verifiable(ref_doctype: str, ref_name: str) -> tuple[bool, str]:
	"""Existence + (permission-bounded) readability of a finding ref AS the
	run-as user (this tool runs impersonated). Aggregate-dim doctypes are checked
	for existence only (see _PERM_EXEMPT_REFS)."""
	if not frappe.db.exists(ref_doctype, ref_name):
		return False, "ref does not exist"
	if ref_doctype in _PERM_EXEMPT_REFS:
		return True, ""
	try:
		if not frappe.has_permission(ref_doctype, "read", doc=ref_name):
			return False, "ref not readable by run-as user"
	except frappe.PermissionError:
		return False, "ref not readable by run-as user"
	return True, ""


def _validate_findings(raw_findings: list, token_set: set, allowed_refs: set):
	"""Split evaluator findings into (valid, dropped). A row is valid iff its
	token is a known agent token, its ref_doctype is allowed, its ref exists for
	the run-as user, amount is numeric and severity is known. Dropped rows carry a
	reason so the Run coverage names the rejected refs (A16 — never a silent zero
	pass, never persist an unverifiable row)."""
	valid, dropped = [], []
	for f in raw_findings:
		if not isinstance(f, dict):
			dropped.append({"ref_doctype": "?", "ref_name": "?", "reason": "not an object"})
			continue
		token = f.get("token") or f.get("rule_id")
		rdt = f.get("ref_doctype") or ""
		rname = f.get("ref_name") or ""
		reason = None
		if token not in token_set:
			reason = "unknown rule token"
		elif rdt not in allowed_refs:
			reason = f"ref_doctype {rdt!r} not allowed for this agent"
		elif f.get("severity") not in _SEVERITIES:
			reason = f"bad severity {f.get('severity')!r}"
		else:
			try:
				float(f.get("amount") or 0)
			except (TypeError, ValueError):
				reason = "amount is not numeric"
			if reason is None:
				ok, why = _ref_verifiable(rdt, rname)
				if not ok:
					reason = why
		if reason:
			dropped.append({"ref_doctype": rdt, "ref_name": rname, "reason": reason,
							"token": token})
		else:
			valid.append(f)
	return valid, dropped


def record_agent_run(
	findings=None,
	coverage=None,
	scope=None,
	truncated: bool = False,
	canvas_ref: str | None = None,
	integrity_digest: str | None = None,
	dashboard: str | None = None,
) -> dict:
	"""Land a delegate's evaluator output on its running Jarvis Agent Run.

	Args (all from the evaluator's JSON, passed verbatim by the delegate):
	  findings: list of ``{token, ref_doctype, ref_name, amount, severity, note}``.
	  coverage: per-rule manifest ``{token: "evaluated"|"not_evaluable(reason)"|
	    "truncated"}`` — gates coverage-scoped auto-resolve (A16).
	  scope: the resolved run scope ``{company, fiscal_year, from_date, to_date,
	    ...}`` — company is stamped on each Finding + scopes auto-resolve + the
	    watermark recompute.
	  truncated: True when the delegate's fetch hit its budget — auto-resolve is
	    skipped entirely and the run is partial (A16).
	  canvas_ref: the delegate's saved canvas/dashboard ref (stored for Phase 4).
	  integrity_digest: the evaluator's sha256 over canonicalized findings.
	  dashboard: the ``Jarvis Dashboard`` name the delegate got back from
	    ``jarvis__save_agent_dashboard`` — linked on the Run. When omitted (and the
	    delegate authored none), a minimal A2-safe dashboard is built server-side
	    from the persisted findings so every run yields one openable dashboard.

	Returns ``{run, status, findings_count, blocker_count, dropped, coverage_note,
	dashboard}``.
	"""
	from jarvis.chat import agent_runs
	from jarvis.tools._agent_run_ctx import get_session_key

	# The Run is resolved from the CALLER's session_key (the delegate's opaque
	# bearer), NEVER a model-supplied id — so a delegate can only ever write back
	# to its own run.
	session_key = get_session_key()
	if not session_key:
		raise InvalidArgumentError(
			"record_agent_run must be called by an agent delegate over its run "
			"session (no session_key in context)")

	run_row = frappe.db.get_value(
		RUN, {"session_key": session_key},
		["name", "status", "installation", "agent"], as_dict=True,
	)
	if not run_row:
		raise InvalidArgumentError("no agent run is bound to this session")
	if run_row.status != "running":
		# Idempotency: the run already finalized (a retried / duplicate writeback).
		# Return current state without touching anything.
		return {
			"run": run_row.name,
			"status": run_row.status,
			"idempotent": True,
			"note": "run already finalized; writeback ignored",
		}
	if not run_row.installation:
		raise InvalidArgumentError("run has no installation")

	inst = frappe.get_doc(INSTALLATION, run_row.installation)
	run_doc = frappe.get_doc(RUN, run_row.name)

	# The agent's bench-held id-only token manifest + allowed ref doctypes. Tokens
	# are opaque (A2); allowed refs = the agent's declared doctypes_required plus
	# the aggregate dims (Company/Account) an evaluator may key a finding on.
	listing = frappe.db.get_value(
		LISTING, run_row.agent, ["rule_tokens", "doctypes_required"], as_dict=True,
	) or {}
	token_set = set(_as_list(listing.get("rule_tokens")))
	allowed_refs = set(_as_list(listing.get("doctypes_required"))) | {"Company", "Account"}

	raw_findings = _as_list(findings)
	coverage = _as_dict(coverage)
	scope = _as_dict(scope)
	truncated = bool(truncated)

	valid, dropped = _validate_findings(raw_findings, token_set, allowed_refs)

	run_doc = agent_runs.record_delegate_run(
		run_doc,
		inst,
		valid,
		coverage=coverage,
		scope=scope,
		truncated=truncated,
		dropped=dropped,
		canvas_ref=canvas_ref,
		integrity_digest=integrity_digest,
		dashboard=(str(dashboard).strip() or None) if dashboard else None,
	)

	return {
		"run": run_doc.name,
		"status": run_doc.status,
		"findings_count": run_doc.findings_count,
		"blocker_count": run_doc.blocker_count,
		"dropped": dropped,
		"coverage_note": run_doc.coverage_note or "",
		"dashboard": run_doc.get("dashboard") or None,
	}
