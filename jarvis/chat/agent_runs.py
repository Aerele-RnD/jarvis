"""Deterministic Run + Findings persistence for the delegate agents (O2).

``record_delegate_run`` writes ONE ``Jarvis Agent Run`` + N ``Jarvis Agent
Finding`` rows from a delegate evaluator's VALIDATED findings. It is DETERMINISTIC
server code, NOT model-mediated: the delegate narrates the transcript, but the
stored, severity-tagged, deduped finding rows are the reproducibility guarantee
(same evaluator output -> same rows, re-runnable by a peer reviewer).

Findings dedupe across runs on a stable ``fingerprint`` (sha256 of
``rule_id + ref_doctype + ref_name``): a finding still ``open`` from a prior run
has its ``last_seen_run`` bumped instead of being duplicated. ``status=partial``
marks a scan that hit the turn envelope (never masquerades as ``completed``).
Auto-resolve is coverage-scoped (A16) + gated on the GL consistency watermark
(A17), scoped visibility (A12) and row under-read — never an unconditional sweep.
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
DASHBOARD = "Jarvis Dashboard"
SESSION = "Jarvis Chat Session"


# --------------------------------------------------------------------------- #
# Phase 4 — saved dashboard delivery + A8 session teardown
# --------------------------------------------------------------------------- #
_SEV_LABEL = {"blocker": "Blockers", "warning": "Warnings", "note": "Notes"}


def teardown_run_session(session_key: str | None) -> None:
    """A8 (zero-trace): delete the per-run ``Jarvis Chat Session`` row once the
    run is finalized (completed/partial/failed) or reaped.

    The session row is a BEARER CREDENTIAL — ``session_key`` + a valid device id
    resolves the run-as user (``api.py`` → impersonate) — so it must not linger
    past the run. The ``session_key`` string stays stamped on the Run for audit
    (harmless without the row); only the resolvable row is destroyed. Best-effort:
    never breaks finalization.

    TODO(A8 fleet piece): the CONTAINER-side session transcript (its jsonl —
    which embeds MB-scale chunked payloads — and its ``sessions.json`` entry) is
    fleet-owned. It is pruned via the fleet-agent's ``session_hygiene`` (gateway
    RPC when the container is live, else deferred) on the next Apply / uninstall
    or a dedicated prune verb. Do NOT prune the container side from the bench.
    """
    key = (session_key or "").strip()
    if not key:
        return
    try:
        frappe.db.delete(SESSION, {"session_key": key})
    except Exception:
        frappe.log_error(
            title="jarvis agent: run-session teardown failed",
            message=frappe.get_traceback(),
        )


def _default_dashboard_title(run_doc, listing_title: str) -> str:
    """"<agent title> — <period>" (A2-safe: agent name + fiscal period only)."""
    import json as _json

    period = ""
    try:
        scope = _json.loads(run_doc.get("scope_json") or "{}")
        period = str(scope.get("fiscal_year") or scope.get("to_date") or "").strip()
    except Exception:
        period = ""
    if not period:
        period = frappe.utils.today()
    base = (listing_title or "Agent").strip()
    return f"{base} — {period}"[:140]


def _esc(value) -> str:
    from frappe.utils import escape_html

    return escape_html(str(value if value is not None else ""))


def _fallback_dashboard_html(title: str, findings: list, counts: dict, coverage_note: str) -> str:
    """A minimal, self-contained, A2-safe findings summary — the server-generated
    FLOOR used only when the delegate produced findings but authored no dashboard
    (so a completed/partial run always yields ONE saved dashboard). It renders the
    already-persisted, already-lossy finding fields (authored ``note`` + ref +
    amount + severity) — NEVER the opaque token, and never any rule id/threshold.
    Inline styles only (CSP sandbox). The Jarvis theme injects the surrounding CSS
    variables; sane fallbacks keep it legible standalone."""
    total = sum(counts.get(s, 0) for s in ("blocker", "warning", "note"))
    cards = "".join(
        f'<div style="flex:1;min-width:120px;padding:14px 16px;border:1px solid var(--jarvis-border,#e5e7eb);'
        f'border-radius:10px;background:var(--jarvis-surface,#fff)">'
        f'<div style="font-size:26px;font-weight:700;color:var(--jarvis-text,#111827)">{counts.get(sev, 0)}</div>'
        f'<div style="font-size:12px;text-transform:uppercase;letter-spacing:.04em;'
        f'color:var(--jarvis-muted,#6b7280)">{_SEV_LABEL[sev]}</div></div>'
        for sev in ("blocker", "warning", "note")
    )
    rows = ""
    order = {"blocker": 0, "warning": 1, "note": 2}
    for f in sorted(findings or [], key=lambda x: (order.get(x.get("severity"), 3), str(x.get("ref_name")))):
        sev = f.get("severity") or "note"
        amt = f.get("amount") or 0
        try:
            amt = f"{float(amt):,.2f}"
        except (TypeError, ValueError):
            amt = _esc(amt)
        rows += (
            f'<tr style="border-top:1px solid var(--jarvis-border,#e5e7eb)">'
            f'<td style="padding:8px 10px;white-space:nowrap;text-transform:capitalize">{_esc(sev)}</td>'
            f'<td style="padding:8px 10px">{_esc(f.get("note"))}</td>'
            f'<td style="padding:8px 10px;white-space:nowrap;color:var(--jarvis-muted,#6b7280)">'
            f'{_esc(f.get("ref_doctype"))} · {_esc(f.get("ref_name"))}</td>'
            f'<td style="padding:8px 10px;text-align:right;white-space:nowrap">{amt}</td></tr>'
        )
    if not rows:
        rows = (
            '<tr><td colspan="4" style="padding:14px 10px;color:var(--jarvis-muted,#6b7280)">'
            "No exceptions were found for this run.</td></tr>"
        )
    banner = ""
    if coverage_note:
        banner = (
            f'<div style="margin:0 0 16px;padding:10px 14px;border-radius:8px;'
            f'background:var(--jarvis-warn-bg,#fef3c7);color:var(--jarvis-warn-text,#92400e);'
            f'font-size:13px">Partial run — {_esc(coverage_note)}</div>'
        )
    return (
        f"<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{_esc(title)}</title></head>"
        f'<body style="margin:0;font-family:var(--jarvis-font,system-ui,-apple-system,Segoe UI,Roboto,sans-serif);'
        f'color:var(--jarvis-text,#111827);background:var(--jarvis-bg,#f9fafb);padding:24px">'
        f'<h1 style="font-size:20px;margin:0 0 4px">{_esc(title)}</h1>'
        f'<p style="margin:0 0 18px;color:var(--jarvis-muted,#6b7280);font-size:13px">'
        f"{total} finding(s) this run.</p>"
        f"{banner}"
        f'<div style="display:flex;gap:12px;margin:0 0 20px;flex-wrap:wrap">{cards}</div>'
        f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:14px">'
        f'<thead><tr style="text-align:left;color:var(--jarvis-muted,#6b7280);font-size:12px;'
        f'text-transform:uppercase;letter-spacing:.04em">'
        f'<th style="padding:8px 10px">Severity</th><th style="padding:8px 10px">Finding</th>'
        f'<th style="padding:8px 10px">Reference</th>'
        f'<th style="padding:8px 10px;text-align:right">Amount</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div></body></html>"
    )


def persist_agent_dashboard(run_doc, inst, html: str, *, title=None, description=None,
                            set_on_run: bool = True) -> str:
    """Create ONE ``Jarvis Dashboard`` from a self-contained HTML document and
    (by default) link it on the Run.

    Written server-side with ignore_permissions and re-homed to the human
    ``inst.owner`` — the SAME identity convention as the Run/Finding rows (owner =
    the installer, so it appears in THEIR Dashboards list next to the run), not
    the (possibly service-account) run_as_user. User-scoped, Static (no live
    sources → no query specs that could leak rule shape; the summary is
    self-contained). The controller enforces the html/title caps + CSP contract.
    Returns the new dashboard name."""
    owner = inst.owner
    listing_title = frappe.db.get_value(LISTING, run_doc.agent, "title") or run_doc.agent
    dash_title = (title or "").strip()[:140] or _default_dashboard_title(run_doc, listing_title)

    doc = frappe.get_doc({
        "doctype": DASHBOARD,
        "dashboard_title": dash_title,
        "description": (description or "").strip()[:255] or None,
        "html": html,
        "scope": "User",
        "theme": "Jarvis",
        "source_conversation": run_doc.get("conversation") or "",
    })
    # Pre-set owner so the controller pins target_user to the human owner (its
    # _validate_scope reads self.owner, set before insert). ignore_permissions —
    # trusted server infrastructure, exactly like the Finding rows above.
    doc.owner = owner
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    if set_on_run:
        frappe.db.set_value(RUN, run_doc.name, "dashboard", doc.name, update_modified=False)
    return doc.name


def _notify_owner_dashboard(owner: str, run_name: str, dashboard_name: str, agent_title: str,
                            status: str, findings_count: int, blocker_count: int) -> None:
    """Best-effort bell notification to the human owner that a run finished + a
    dashboard is ready to open. Never raises."""
    if not owner or owner in ("Administrator", "Guest"):
        return
    try:
        verb = {"completed": "completed", "partial": "completed (partial)"}.get(status, "finished")
        frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": owner,
            "type": "Alert",
            "subject": f"{agent_title or 'Agent'} run {verb}: {findings_count} finding(s), "
                       f"{blocker_count} blocker(s)",
            "email_content": "Your agent finished a run. Open its findings dashboard from the "
                             "run, or the Dashboards page.",
            "document_type": DASHBOARD,
            "document_name": dashboard_name,
        }).insert(ignore_permissions=True)
    except Exception:
        pass


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


# --------------------------------------------------------------------------- #
# Phase 3 — delegate findings writeback (A16 coverage-scoped auto-resolve +
# A17 watermark recheck). The container evaluator computes the findings; this is
# the DETERMINISTIC bench-side persister the ``record_agent_run`` tool calls once
# the caller's session_key has been resolved to a running Run + validated. Its
# auto-resolve is coverage-scoped and gated (drift / scoped / under-read), so it
# never silently closes real blockers a chunk-scoped/partial run never observed.
# --------------------------------------------------------------------------- #
def _coverage_summary(coverage: dict) -> tuple[set, list]:
	"""(fully-evaluated token set, [not_evaluable/truncated notes]) from the
	per-rule coverage manifest ``{token: "evaluated"|"not_evaluable(reason)"|
	"truncated"}`` the evaluator emits (A16)."""
	evaluated, notes = set(), []
	for token, state in (coverage or {}).items():
		st = str(state or "")
		if st == "evaluated":
			evaluated.add(token)
		elif st:
			notes.append(f"{token}: {st}")
	return evaluated, notes


def _watermark_drift(run_doc, scope: dict) -> bool:
	"""A17: recompute {count, max(modified)} over the scope's GL as-of window and
	compare to the watermark stamped at launch. True when the GL changed mid-scan
	(a backdated JV between two chunk fetches) so the run must NOT read as
	``completed``. No stamped watermark / no scope -> no drift signal (False)."""
	stamped_count = run_doc.get("wm_row_count")
	company = (scope or {}).get("company")
	to_date = (scope or {}).get("to_date")
	if stamped_count is None or not company or not to_date:
		return False
	try:
		wm = frappe.db.sql(
			"""select count(*) n, max(modified) m from `tabGL Entry`
			   where company = %(company)s and posting_date <= %(to_date)s""",
			{"company": company, "to_date": to_date},
			as_dict=True,
		)[0]
	except Exception:
		return False
	if int(wm.n or 0) != int(stamped_count or 0):
		return True
	stamped_mod = run_doc.get("wm_gl_max_modified")
	new_mod = wm.m
	if bool(stamped_mod) != bool(new_mod):
		return True
	if stamped_mod and new_mod:
		from frappe.utils import get_datetime
		return get_datetime(stamped_mod) != get_datetime(new_mod)
	return False


def _scoped_visibility(run_doc, inst) -> bool:
	"""FIX 1 / A12: is this run's run-as identity record-sliced on a GL dimension?

	A User Permission on a GL dimension (Cost Center / Project / Account / party …)
	makes every aggregate the run-as user reads a SLICE — a numerically WRONG total,
	not merely a narrower one — so a scoped run must NEVER auto-resolve findings it
	could not see (closing an unseen blocker on a partial view is a silent
	regression). Derived FRESH from the Run's stamped ``permission_profile`` (the
	run-as user's user_permissions snapshotted AT LAUNCH — the authoritative signal),
	so a User Permission added AFTER install is caught even though the installation's
	``scoped_visibility`` flag (stamped only at map/backfill time) has gone stale.
	Falls back to that stamped flag when the profile is absent (a legacy run, or one
	whose profile computation failed)."""
	import json as _json

	from jarvis.jarvis.doctype.jarvis_agent_installation.jarvis_agent_installation import (
		_GL_SCOPED_DIMENSIONS,
	)

	profile = run_doc.get("permission_profile")
	if profile:
		try:
			ups = (_json.loads(profile) or {}).get("user_permissions") or {}
			# A GL-dimension key present AND carrying at least one value = a live slice.
			if any(ups.get(dt) for dt in _GL_SCOPED_DIMENSIONS):
				return True
		except Exception:
			pass
	return bool(inst.get("scoped_visibility"))


def _rowcount_shortfall(run_doc, rows_consumed) -> bool:
	"""FIX 6: did the evaluator actually READ the ledger? The watermark stamped at
	launch (``wm_row_count`` — count of in-scope GL entries) proves whether the
	ledger is non-empty. If the evaluator reports it consumed ZERO rollup rows while
	the watermark shows rows exist, its fetch under-read: a green, zero-finding run
	that would otherwise auto-resolve real blockers it never observed. Force partial
	+ skip auto-resolve.

	Only the ZERO-read is gated. A per-account rollup count is NOT magnitude-
	comparable to the GL-entry watermark (cancelled + pre-period entries legitimately
	differ), so a non-zero count is deliberately not asserted equal — that would be a
	false-positive machine. ``rows_consumed=None`` (a delegate/evaluator that does not
	yet report it) means "cannot reconcile", never a false shortfall."""
	stamped = run_doc.get("wm_row_count")
	if stamped is None:
		return False
	try:
		if int(stamped) <= 0:
			return False  # empty (or unknown) ledger — nothing to under-read
	except (TypeError, ValueError):
		return False
	if rows_consumed is None:
		return False
	try:
		return int(rows_consumed) <= 0
	except (TypeError, ValueError):
		return False


def record_delegate_run(
	run,
	installation,
	findings: list,
	*,
	coverage: dict | None = None,
	scope: dict | None = None,
	truncated: bool = False,
	dropped: list | None = None,
	canvas_ref: str | None = None,
	integrity_digest: str | None = None,
	dashboard: str | None = None,
	rows_consumed: int | None = None,
):
	"""Persist a delegate's evaluator findings onto its running Run (A16/A17).

	``run`` is the already-resolved ``running`` Jarvis Agent Run (the tool
	resolves it from the caller's session_key). ``findings`` are the VALIDATED
	rows (each ``{token, ref_doctype, ref_name, amount, severity, note}`` —
	invalid rows already dropped by the tool and passed as ``dropped``).
	``coverage`` is the per-rule manifest; ``scope`` the resolved run scope
	(carries ``company`` stamped on every Finding + used to scope auto-resolve and
	recompute the watermark). Returns the reloaded Run doc.
	"""
	import json as _json

	inst = installation if hasattr(installation, "owner") else frappe.get_doc(INSTALLATION, installation)
	run_doc = run if hasattr(run, "name") else frappe.get_doc(RUN, run)
	owner = inst.owner
	agent = inst.agent
	coverage = coverage or {}
	scope = scope or {}
	dropped = dropped or []
	company = (scope.get("company") or "").strip()

	# Collapse this run's findings by fingerprint (token + doc identity), so a doc
	# flagged twice by one rule is ONE finding and counts stay consistent.
	by_fp: dict = {}
	for f in findings or []:
		token = f.get("token") or f.get("rule_id")
		fp = _fingerprint(token, f.get("ref_doctype"), f.get("ref_name"))
		by_fp.setdefault(fp, f)
	seen_fps = set(by_fp)

	counts = {"blocker": 0, "warning": 0, "note": 0}
	for fp, f in by_fp.items():
		token = f.get("token") or f.get("rule_id")
		sev = f.get("severity") or "note"
		counts[sev] = counts.get(sev, 0) + 1
		note = f.get("note") or f.get("detail") or ""

		existing = frappe.db.get_value(
			FINDING,
			{"owner": owner, "agent": agent, "fingerprint": fp, "state": "open"},
			"name",
		)
		if existing:
			frappe.db.set_value(FINDING, existing, "last_seen_run", run_doc.name, update_modified=False)
			continue

		fd = frappe.get_doc({
			"doctype": FINDING,
			"run": run_doc.name,
			"agent": agent,
			# A2: the OPAQUE rule token lives in rule_id — the real rule_id / catalog
			# identifier never reaches the bench; fingerprint dedup keeps working.
			"rule_id": token or "",
			"severity": sev,
			# A2: authored, outcome-level text only (the evaluator's fixed-template
			# note). No as-coded threshold / carve-out text.
			"title": note[:140],
			"detail_md": note,
			"section": "",
			"ref_doctype": f.get("ref_doctype") or "",
			"ref_name": f.get("ref_name") or "",
			# A16: stamp the company scope so a Company-B run never auto-resolves a
			# Company-A finding; empty legacy rows are exempt until re-seen.
			"company": company or None,
			"amount": f.get("amount") or 0,
			"disclaimer": "",
			"fingerprint": fp,
			"state": "open",
			"first_seen_run": run_doc.name,
			"last_seen_run": run_doc.name,
		})
		fd.flags.ignore_permissions = True
		fd.insert()
		_reassign_owner(FINDING, fd.name, owner)

	# --- A17 watermark recheck (FIX 2: HOISTED before the A16 gate) ------------
	# Computed BEFORE the auto-resolve loop so it can gate it: a run that observed an
	# INCONSISTENT GL snapshot (a backdated JV landing between two chunk fetches) must
	# not close prior findings on that drifted view — the same "never close on an
	# inconsistent snapshot" principle already applied to ``truncated``. Depends only
	# on run_doc + scope, so the hoist is side-effect-free.
	wm_drift = _watermark_drift(run_doc, scope)

	# --- A12 scoped-visibility recheck (FIX 1) --------------------------------
	# A record-sliced run-as identity computes numerically WRONG aggregates, so a
	# scoped run must never auto-resolve findings it could not see. Derived FRESH
	# from the run's stamped permission_profile (not the install's stale flag).
	scoped = _scoped_visibility(run_doc, inst)

	# --- ledger under-read reconciliation (FIX 6) -----------------------------
	# The watermark proves the ledger is non-empty; a zero-read means the evaluator
	# fetched nothing — a green "zero findings" run that would otherwise auto-resolve
	# real blockers. Gate it.
	row_shortfall = _rowcount_shortfall(run_doc, rows_consumed)

	# --- A16 coverage-scoped auto-resolve --------------------------------------
	# HARD RULE: a run that is truncated, drift-inconsistent (A17), scope-sliced (A12)
	# or under-read auto-resolves NOTHING — its findings list is not a trustworthy
	# full view of the books, and closing an unseen blocker would be a silent
	# regression. Only findings whose token was FULLY EVALUATED this run AND that
	# belong to THIS run's company scope are eligible; empty-company legacy rows are
	# exempt.
	evaluated_tokens, coverage_notes = _coverage_summary(coverage)
	if not truncated and not wm_drift and not scoped and not row_shortfall and evaluated_tokens:
		candidates = frappe.get_all(
			FINDING,
			filters={
				"owner": owner,
				"agent": agent,
				"state": "open",
				"rule_id": ["in", list(evaluated_tokens)],
			},
			fields=["name", "fingerprint", "company"],
		)
		for c in candidates:
			if c.fingerprint in seen_fps:
				continue  # still present this run
			# Company scope gate: only resolve a finding whose company matches this
			# run's company (both non-empty). A scopeless run, or an empty-company
			# legacy row, is left untouched (exempt) — never cross-company resolved.
			if not company or not c.company or c.company != company:
				continue
			frappe.db.set_value(FINDING, c.name, "state", "resolved", update_modified=False)

	# --- status + coverage note ------------------------------------------------
	dropped_notes = [
		f"rejected {d.get('ref_doctype','?')}/{d.get('ref_name','?')} ({d.get('reason','invalid')})"
		for d in dropped
	]
	partial = (
		bool(truncated) or wm_drift or scoped or row_shortfall
		or bool(dropped) or bool(coverage_notes)
	)
	status = "partial" if partial else "completed"

	note_parts = []
	if truncated:
		note_parts.append("scan truncated; findings incomplete")
	if wm_drift:
		note_parts.append("GL changed during scan — re-run advised")
	if scoped:
		note_parts.append("scoped visibility — findings not auto-resolved")
	if row_shortfall:
		note_parts.append("ledger under-read vs watermark — re-run advised")
	if coverage_notes:
		note_parts.append("not evaluable: " + "; ".join(coverage_notes))
	if dropped_notes:
		note_parts.append("dropped: " + "; ".join(dropped_notes))
	coverage_note = " | ".join(note_parts)

	# Full, machine-readable coverage manifest for the Findings board / Phase 4:
	# the per-rule coverage + not_evaluable + dropped refs + every auto-resolve-gate
	# verdict (drift / scoped / under-read) so the board can explain WHY a run held
	# findings open. When scoped, the fully-evaluated tokens are surfaced as
	# not-evaluable-scoped (their container verdicts ran on a sliced view).
	coverage_blob = _json.dumps({
		"coverage": coverage,
		"not_evaluable": coverage_notes,
		"not_evaluable_scoped": sorted(evaluated_tokens) if scoped else [],
		"dropped": dropped,
		"watermark_drift": wm_drift,
		"scoped_visibility": scoped,
		"row_shortfall": row_shortfall,
		"rows_consumed": rows_consumed,
		"wm_row_count": run_doc.get("wm_row_count"),
		"truncated": bool(truncated),
	}, sort_keys=True, default=str)

	run_values = {
		"status": status,
		"findings_count": len(seen_fps),
		"blocker_count": counts.get("blocker", 0),
		"finished_at": frappe.utils.now(),
		"coverage_note": coverage_note[:140],
		"coverage_json": coverage_blob[:60000],
	}
	if scope:
		run_values["scope_json"] = frappe.as_json(scope)[:60000]
	if integrity_digest:
		run_values["integrity_digest"] = str(integrity_digest)[:64]
	if canvas_ref:
		run_values["canvas_ref"] = str(canvas_ref)[:255]
	frappe.db.set_value(RUN, run_doc.name, run_values, update_modified=False)

	# --- Phase 4: exactly ONE saved Jarvis Dashboard per run ------------------
	# Precedence: (1) a dashboard the delegate already authored via
	# jarvis__save_agent_dashboard this turn (Run.dashboard already set — richer,
	# model-authored HTML wins); (2) an explicit ``dashboard`` name reported at
	# writeback; (3) a server-generated A2-safe FLOOR built from the persisted
	# findings, so a findings-only run (no canvas) STILL yields an openable
	# dashboard. Best-effort: a dashboard hiccup must never fail the writeback.
	agent_title = frappe.db.get_value(LISTING, agent, "title")
	dashboard_name = frappe.db.get_value(RUN, run_doc.name, "dashboard")
	if not dashboard_name and dashboard and frappe.db.exists(DASHBOARD, dashboard):
		frappe.db.set_value(RUN, run_doc.name, "dashboard", dashboard, update_modified=False)
		dashboard_name = dashboard
	if not dashboard_name:
		try:
			title = _default_dashboard_title(run_doc, agent_title)
			html = _fallback_dashboard_html(title, list(by_fp.values()), counts, coverage_note)
			dashboard_name = persist_agent_dashboard(run_doc, inst, html, title=title)
		except Exception:
			frappe.log_error(
				title="jarvis agent: fallback dashboard build failed",
				message=frappe.get_traceback(),
			)

	# Activity trail (best-effort, owner-scoped, Link-free) + owner notification.
	log_activity(
		agent=agent,
		agent_title=agent_title,
		installation=inst.name,
		action={"completed": "run_completed", "partial": "run_partial"}.get(status, "run_failed"),
		run=run_doc.name,
		detail=f"{len(seen_fps)} findings, {counts.get('blocker', 0)} blockers"
		+ (f"; {coverage_note}" if coverage_note else "")
		+ (f"; dashboard {dashboard_name}" if dashboard_name else ""),
		owner=owner,
	)
	if dashboard_name:
		_notify_owner_dashboard(owner, run_doc.name, dashboard_name, agent_title, status,
								len(seen_fps), counts.get("blocker", 0))

	# A8 (zero-trace): the per-run session bearer must not outlive the run.
	teardown_run_session(run_doc.get("session_key"))

	# Stamp the installation completion: last_run_at whatever the trigger;
	# next_run_at only for a scheduled install.
	inst_values = {"last_run_at": frappe.utils.now()}
	if inst.schedule_enabled:
		inst_values["next_run_at"] = compute_next_run(inst.schedule_frequency, inst.schedule_time)
	frappe.db.set_value(INSTALLATION, inst.name, inst_values, update_modified=False)
	frappe.db.commit()

	run_doc.reload()
	return run_doc
