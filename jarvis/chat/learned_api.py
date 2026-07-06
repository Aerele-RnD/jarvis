"""Learning board API: SM-gated endpoints for the Skills-page "Learning" tab.

Sibling of ``approvals_api.py`` / ``agents_api.py`` - every endpoint is
``@frappe.whitelist()`` + ``frappe.only_for("System Manager")`` and, because
behavioural pattern learning is a MANAGED-ONLY feature (plan sections 13 /
7 T5 / 6.4), additionally refuses on self-hosted benches. Two exceptions:
``get_learning_status`` is the probe the tab uses to decide whether to render
the managed-only empty state, so it stays reachable on self-host and simply
reports ``self_hosted=True``; and ``flag_learned_default`` (the plan-6.5
correction loop) is deliberately open to ANY authenticated System User (the
chat user who just watched a learned default misfire), though still
self-host-gated and refused for Guest / portal (Website User) sessions.

Board lifecycle (plan section 6.5) runs through the ``Jarvis Learned Pattern``
state machine (``validate_transition`` in the controller). These are HUMAN
System-Manager actions, so they go through the controller normally (SM has
read+write) - we do NOT set ``frappe.flags.jarvis_pattern_engine`` (that bypass
is for the engine's own inserts/refreshes). Writes are TOCTOU-safe: every
transition re-reads the row and guards the source status before saving, and
``Document.save`` adds the modified-timestamp concurrency check on top (mirrors
``approvals_api.decide``'s conditional flip).

Raw statistics (support_n, confidence, wilson_low, gap) never ride the list
payload - the cards are plain English; the numbers live in the drill-down
(``get_learned_pattern``) only.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime, today

JLP = "Jarvis Learned Pattern"
RUN = "Jarvis Pattern Run"
SETTINGS = "Jarvis Settings"

_DOMAINS = ("selling", "buying", "stock", "accounts", "projects", "org")
_STRENGTHS = ("High", "Medium", "Low")
_STATUSES = (
	"Proposed", "Approved", "Active", "Rejected",
	"Snoozed", "Stale", "Superseded", "Archived",
)
_SNOOZE_DAYS = (7, 30, 90)

# The config fields the in-tab settings surface may write. The engine status
# quartet (pattern_last_run_at / pattern_last_run_status / pattern_next_run_at /
# pattern_scan_mode) is engine-owned and NOT writable here (plan section 5.1).
_SETTINGS_FIELDS = (
	"pattern_learning_enabled",
	"pattern_window_start",
	"pattern_window_end",
	"pattern_max_proposals_per_run",
	"pattern_row_budget_per_night",
)

# Server-side defaults for the pattern_* config. Frappe does NOT backfill Single
# field defaults on migrate, so a pre-existing Jarvis Settings row reads null
# for these (bootstrap.after_migrate seeds them; this coalesces reads too - plan
# sections 5.1 / 6.4).
_SETTINGS_DEFAULTS = {
	"pattern_window_start": "01:00:00",
	"pattern_window_end": "05:00:00",
	"pattern_max_proposals_per_run": 10,
	"pattern_row_budget_per_night": 500000,
}

# The terminal disposition recorded for a B/C insight-only pattern the SM has
# read and dismissed (Acknowledge). Stored as Rejected + this exact note so it is
# durably suppressed from re-proposal AND excluded from the pending-apply count;
# the board renders it as "Acknowledged" (not a real rejection) by matching this
# note. Keep the string stable - the frontend keys off it.
ACK_NOTE = "Acknowledged - insight only"

# Rendered on the board when an SM edited the draft before approving: the
# evidence line is frozen (plan section 6.5) - it still reflects the ORIGINALLY
# detected pattern, not the human edit, which was not re-measured.
FROZEN_EVIDENCE_LABEL = (
	"Evidence reflects the originally detected pattern; your edit was not re-measured."
)

# Card fields only - plain English, no raw statistics (those are drill-down).
# stale_reason / last_validated_at / flags_count / materialized_skill ride the
# card so the board can render the Stale banner ("will be removed on next
# Apply" needs the live-skill pointer) and the correction-loop flag badge.
_CARD_FIELDS = [
	"name", "pattern_statement", "skill_draft", "strength_band", "domain",
	"company", "sensitivity", "effective_sensitivity", "exceptions_cluster",
	"exception_n", "not_applicable", "draft_edited", "overlap_warning",
	"status", "surfaced", "reviewed_by", "approved_by", "creation",
	"stale_reason", "last_validated_at", "flags_count", "materialized_skill",
]

# Correction loop (plan 6.5): note cap, the distinct-user demotion quorum, and
# the per-user re-flag cooldown. Demotion requires >= 2 DISTINCT users (never a
# same-user event tally - one desk user must not be able to ratchet a shared
# default to the floor), and a re-flag inside the cooldown window neither
# re-demotes nor re-notifies.
_FLAG_NOTE_MAX = 280
_FLAG_DISTINCT_USERS = 2
_FLAG_COOLDOWN_HOURS = 24
_BAND_DEMOTE = {"High": "Medium", "Medium": "Low", "Low": "Low"}
# stale_reason prefix stamped by flag-driven demotions. approve_learned_pattern
# clears reasons with this prefix (drift-origin reasons stay - the drift pass
# owns those).
_FLAG_STALE_PREFIX = "flagged by"


# --------------------------------------------------------------------------- #
# gating
# --------------------------------------------------------------------------- #
def _is_self_hosted() -> bool:
	try:
		from jarvis.selfhost import is_self_hosted

		return bool(is_self_hosted())
	except Exception:
		# A missing/broken selfhost probe on a managed bench must not block the
		# feature; the tick/orchestrator make the same fail-open choice.
		return False


def _guard() -> None:
	"""System-Manager-only AND managed-only. Every board endpoint calls this
	first, except ``get_learning_status`` (which reports self-host instead)."""
	frappe.only_for("System Manager")
	if _is_self_hosted():
		frappe.throw(
			_("Pattern learning is not available on self-hosted benches."),
			frappe.ValidationError,
		)


# --------------------------------------------------------------------------- #
# small SQL helpers (self-contained; approvals_api has its own copies)
# --------------------------------------------------------------------------- #
def _lk(s: str) -> str:
	"""Escape LIKE wildcards in user search input."""
	return (s or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _clamp_page(start, page_length) -> tuple[int, int]:
	try:
		start = max(0, int(start or 0))
	except (TypeError, ValueError):
		start = 0
	try:
		pl = int(page_length or 20)
	except (TypeError, ValueError):
		pl = 20
	return start, max(1, min(pl, 100))


def _surfaced_cond(surfaced):
	"""Tri-state: 1/0 -> filter that value; None/''/'all' -> no filter."""
	if surfaced in (None, "", "all", "All"):
		return None
	try:
		return 1 if int(surfaced) else 0
	except (TypeError, ValueError):
		return None


def _parse_json(raw, default):
	if raw in (None, ""):
		return default
	if isinstance(raw, (dict, list)):
		return raw
	try:
		return json.loads(raw)
	except Exception:
		try:
			return frappe.parse_json(raw)
		except Exception:
			return default


# --------------------------------------------------------------------------- #
# list (frozen envelope + domain facets + board counters)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def list_learned_patterns_page(
	domain: str | None = None,
	status: str = "Proposed",
	strength: str | None = None,
	search: str | None = None,
	surfaced=1,
	start: int = 0,
	page_length: int = 20,
) -> dict:
	"""Paginated learning-board list. Envelope ``{rows, total, has_more, start,
	page_length, facets, queued_count, pending_apply_count, review_activity}``
	(shape parity with ``list_approvals_page`` / ``list_custom_skills_page``).

	``facets['domain']`` counts per domain UNDER the current status/surfaced/
	strength/search view but DROPPING the domain filter itself (so the tab strip
	stays populated as you click between domains - the approvals-facet idiom).
	Cards carry plain-English fields only; raw stats are drill-down (section 6.4)."""
	_guard()
	start, pl = _clamp_page(start, page_length)

	if status and status != "All" and status not in _STATUSES:
		frappe.throw(_("Invalid status filter."))
	if strength and strength not in _STRENGTHS:
		frappe.throw(_("Invalid strength filter."))
	if domain and domain not in _DOMAINS:
		frappe.throw(_("Invalid domain filter."))

	params: dict = {"start": start, "page_length": pl}
	# `base` = status + surfaced + strength + search (shared with the facet
	# query). The domain condition applies to the row/total query only.
	base: list[str] = []
	if status and status != "All":
		params["status"] = status
		base.append("status = %(status)s")
	sc = _surfaced_cond(surfaced)
	if sc is not None:
		params["surfaced"] = sc
		base.append("surfaced = %(surfaced)s")
	if strength:
		params["strength"] = strength
		base.append("strength_band = %(strength)s")
	if search:
		params["q"] = f"%{_lk(search)}%"
		base.append("(pattern_statement LIKE %(q)s OR skill_draft LIKE %(q)s)")

	domain_cond = None
	if domain:
		params["domain"] = domain
		domain_cond = "domain = %(domain)s"

	main_where = " AND ".join(base + ([domain_cond] if domain_cond else [])) or "1=1"
	base_where = " AND ".join(base) or "1=1"

	col_list = ", ".join(f"`{c}`" for c in _CARD_FIELDS)
	total = frappe.db.sql(
		f"SELECT COUNT(*) FROM `tab{JLP}` WHERE {main_where}", params
	)[0][0]
	rows = frappe.db.sql(
		f"""SELECT {col_list}
		FROM `tab{JLP}`
		WHERE {main_where}
		ORDER BY CASE `strength_band`
			WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 WHEN 'Low' THEN 2 ELSE 3 END,
			`creation` DESC, `name` ASC
		LIMIT %(page_length)s OFFSET %(start)s""",
		params, as_dict=True,
	)
	for r in rows:
		# normalize the check fields to ints for the client
		for k in ("not_applicable", "draft_edited", "surfaced"):
			r[k] = int(r.get(k) or 0)
		r["exception_n"] = int(r.get("exception_n") or 0)
		r["flags_count"] = int(r.get("flags_count") or 0)
		r["has_overlap_warning"] = 1 if (r.get("overlap_warning") or "").strip() else 0
		r["creation"] = str(r.get("creation") or "")
		r["last_validated_at"] = str(r.get("last_validated_at") or "")
		r["stale_reason"] = r.get("stale_reason") or ""
		r["materialized_skill"] = r.get("materialized_skill") or ""

	facet_rows = frappe.db.sql(
		f"""SELECT domain AS dv, COUNT(*) AS n
		FROM `tab{JLP}`
		WHERE {base_where}
		GROUP BY domain
		ORDER BY n DESC""",
		params, as_dict=True,
	)
	facets = {"domain": [{"value": x.dv, "count": x.n} for x in facet_rows]}

	return {
		"rows": rows,
		"total": total,
		"has_more": start + len(rows) < total,
		"start": start,
		"page_length": pl,
		"facets": facets,
		"queued_count": _queued_count(),
		"pending_apply_count": _pending_apply_count(),
		"stale_pending_removal": _stale_pending_removal_count(),
		"review_activity": _review_activity(),
	}


def _queued_count() -> int:
	"""Proposed but not yet surfaced (the "N more queued" escape hatch)."""
	return frappe.db.count(JLP, {"status": "Proposed", "surfaced": 0})


def _pending_apply_count() -> int:
	"""A-class Approved-not-yet-Active PLUS Stale rows still compiled into a live
	skill (both change the pushed skills on the next Apply) - plan section
	6.2/6.5. B/C are insight-only: the compiler is A-only, so a B/C Approved row
	would NEVER activate and would wedge this bar permanently. Approve refuses B/C
	(they go through Acknowledge instead), but the effective_sensitivity filter is
	the belt-and-suspenders so the bar can never stick."""
	approved = frappe.db.count(
		JLP, {"status": "Approved", "effective_sensitivity": "A"}
	)
	return approved + _stale_pending_removal_count()


def _stale_pending_removal_count() -> int:
	"""Stale rows still compiled into a live learned skill: their bullet is
	removed on the next Apply (plan 6.5 - never silently). Surfaced separately
	so the Apply bar can say "N stale will be removed"; ``apply_learned_skills``
	clears the pointer after a successful Apply so the count drains."""
	return frappe.db.count(JLP, {"status": "Stale", "materialized_skill": ["is", "set"]})


def _review_activity() -> dict:
	""""X of Y decided, last by <SM>" over the surfaced batch (section 6.4)."""
	total = frappe.db.count(
		JLP,
		{
			"surfaced": 1,
			"status": ["in", ["Proposed", "Approved", "Rejected", "Snoozed"]],
		},
	)
	decided = frappe.db.count(
		JLP,
		{"surfaced": 1, "status": ["in", ["Approved", "Rejected", "Snoozed"]]},
	)
	last = frappe.get_all(
		JLP,
		filters={"surfaced": 1, "reviewed_by": ["is", "set"]},
		fields=["reviewed_by", "reviewed_at"],
		order_by="reviewed_at desc",
		limit=1,
	)
	last_by = last[0].reviewed_by if last else None
	return {
		"decided": decided,
		"total": total,
		"last_by": last_by or "",
		"last_by_name": (
			(frappe.db.get_value("User", last_by, "full_name") or last_by)
			if last_by
			else ""
		),
	}


# --------------------------------------------------------------------------- #
# detail (full row + drill-down stats, section 6.4)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def get_learned_pattern(name: str) -> dict:
	"""One pattern with everything the drill-down renders: parsed evidence +
	temporal-spread JSON, detected roles, the exact compiled-bullet preview, run
	links, and the exceptions list (SM may see named parties)."""
	_guard()
	doc = frappe.get_doc(JLP, name)
	evidence = _parse_json(doc.evidence, {})
	exceptions = evidence.get("exceptions") if isinstance(evidence, dict) else None

	return {
		"name": doc.name,
		"detector_id": doc.detector_id,
		"pattern_key": doc.pattern_key,
		"domain": doc.domain,
		"company": doc.company or "",
		"roles": [r.role for r in (doc.roles or [])],
		"pattern_statement": doc.pattern_statement or "",
		"skill_draft": doc.skill_draft or "",
		"draft_edited": int(doc.draft_edited or 0),
		"draft_polished": int(doc.get("draft_polished") or 0),
		"compiled_preview": _compiled_preview(doc),
		"frozen_evidence_label": FROZEN_EVIDENCE_LABEL if doc.draft_edited else "",
		# raw statistics (drill-down only)
		"support_n": int(doc.support_n or 0),
		"n_rows": int(doc.n_rows or 0),
		"exception_n": int(doc.exception_n or 0),
		"confidence_pct": float(doc.confidence_pct or 0),
		"wilson_low": float(doc.wilson_low or 0),
		"gap": float(doc.gap or 0),
		"strength_band": doc.strength_band or "",
		"temporal_spread": _parse_json(doc.temporal_spread, {}),
		"evidence": evidence,
		"exceptions": exceptions if isinstance(exceptions, list) else [],
		"exceptions_cluster": doc.exceptions_cluster or "",
		"sensitivity": doc.sensitivity or "",
		"effective_sensitivity": doc.effective_sensitivity or "",
		"not_applicable": int(doc.not_applicable or 0),
		"overlap_warning": doc.overlap_warning or "",
		# review state
		"status": doc.status,
		"surfaced": int(doc.surfaced or 0),
		"reviewed_by": doc.reviewed_by or "",
		"approved_by": doc.approved_by or "",
		"reviewed_at": str(doc.reviewed_at or ""),
		"review_note": doc.review_note or "",
		"snoozed_until": str(doc.snoozed_until or ""),
		"stale_reason": doc.stale_reason or "",
		"last_validated_at": str(doc.last_validated_at or ""),
		# correction loop (plan 6.5)
		"flags_count": int(doc.flags_count or 0),
		"flag_band_cap": doc.get("flag_band_cap") or "",
		"counter_evidence": _counter_evidence_list(doc.counter_evidence),
		# run links
		"first_seen_run": doc.first_seen_run or "",
		"last_seen_run": doc.last_seen_run or "",
		"superseded_by": doc.superseded_by or "",
		"materialized_skill": doc.materialized_skill or "",
	}


def _compiled_preview(doc) -> str:
	"""The exact bullet THIS pattern would compile into (drill-down preview).
	Uses ``compiler.preview_bullet(pattern_name)`` - the single-bullet renderer;
	``compile_preview(domain)`` returns the whole domain body and takes a DOMAIN,
	not a pattern name, so calling it here always fell back to the raw draft.
	Falls back to the stored draft when the compiler is unavailable."""
	try:
		from jarvis.learning import compiler

		fn = getattr(compiler, "preview_bullet", None)
		if callable(fn):
			out = fn(doc.name)
			if out:
				return out
	except Exception:
		pass
	return doc.skill_draft or ""


# --------------------------------------------------------------------------- #
# lifecycle transitions (section 6.5) - human SM actions, TOCTOU-safe
# --------------------------------------------------------------------------- #
def _load_for_transition(name: str, allowed_sources: tuple, action: str):
	"""Re-read the row and guard its source status (the TOCTOU re-read). The
	subsequent ``doc.save`` adds the modified-timestamp concurrency check."""
	doc = frappe.get_doc(JLP, name)
	if doc.status not in allowed_sources:
		frappe.throw(
			_("Pattern {0} is {1}; cannot {2}.").format(name, doc.status, action)
		)
	return doc


@frappe.whitelist()
def approve_learned_pattern(name: str, edited_skill_draft: str | None = None) -> dict:
	"""Proposed->Approved (or Stale->Approved). Optional edit freezes the
	evidence line (section 6.5): ``draft_edited=1`` and the frozen label is shown
	on the board. Stamps reviewed_by / approved_by / reviewed_at."""
	_guard()
	doc = _load_for_transition(name, ("Proposed", "Stale"), "approve")

	# A-class only. B/C are insight-only in Phase 1 (the compiler is A-only, so a
	# B/C Approved row never activates and would wedge the pending-apply bar).
	# Mirrors batch_approve's gate; points the SM to Acknowledge instead.
	if (doc.effective_sensitivity or "") != "A":
		frappe.throw(
			_(
				"Pattern {0} is {1}-class (insight only in Phase 1) and cannot be approved; "
				"use Acknowledge to record that you have reviewed it."
			).format(name, doc.effective_sensitivity or "B/C")
		)

	edited = (edited_skill_draft or "").strip()
	if edited and edited != (doc.skill_draft or "").strip():
		doc.skill_draft = edited
		doc.draft_edited = 1

	# Correction-loop reset (shared contract): a human approval overrides a
	# flag-driven demotion. Clear the durable band cap (pipeline strength_band
	# writes clamp to it) and a flag-origin stale_reason; drift-origin reasons
	# are left for the drift pass to manage.
	doc.flag_band_cap = ""
	if (doc.stale_reason or "").startswith(_FLAG_STALE_PREFIX):
		doc.stale_reason = None

	now = now_datetime()
	doc.status = "Approved"
	doc.reviewed_by = frappe.session.user
	doc.approved_by = frappe.session.user
	doc.reviewed_at = now
	doc.save()
	frappe.db.commit()
	return {"ok": True, "status": doc.status, "draft_edited": int(doc.draft_edited or 0)}


@frappe.whitelist()
def reject_learned_pattern(name: str, reason: str) -> dict:
	"""Proposed->Rejected (or Stale->Rejected). ``reason`` is mandatory and is
	stored in ``review_note`` (durable, reversible via restore)."""
	_guard()
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A rejection reason is required."))
	doc = _load_for_transition(name, ("Proposed", "Stale"), "reject")
	doc.status = "Rejected"
	doc.review_note = reason
	doc.reviewed_by = frappe.session.user
	doc.reviewed_at = now_datetime()
	doc.save()
	frappe.db.commit()
	return {"ok": True, "status": doc.status}


@frappe.whitelist()
def acknowledge_learned_pattern(name: str) -> dict:
	"""B/C insight-only disposition (plan section 6.4: C is insight-only; B is
	insight-only in Phase 1 pushed text). B/C patterns never compile into the
	pushed body, so there is nothing to Apply - Acknowledge records that the SM
	read the insight and dismisses it. Recorded as a terminal Rejected + the
	stable ``ACK_NOTE`` so it is durably suppressed from re-proposal AND excluded
	from the pending-apply count (unlike an Approved row). A-class rows are
	refused (they must be Approved to reach the container)."""
	_guard()
	doc = _load_for_transition(name, ("Proposed", "Stale"), "acknowledge")
	if (doc.effective_sensitivity or "") == "A":
		frappe.throw(
			_(
				"Pattern {0} is A-class; approve it to apply, rather than acknowledging it."
			).format(name)
		)
	doc.status = "Rejected"
	doc.review_note = ACK_NOTE
	doc.reviewed_by = frappe.session.user
	doc.reviewed_at = now_datetime()
	doc.save()
	frappe.db.commit()
	return {"ok": True, "status": doc.status, "acknowledged": True}


@frappe.whitelist()
def unapprove_learned_pattern(name: str) -> dict:
	"""Approved->Proposed (the multi-SM disagreement window, section 6.5). Any
	SM, but ONLY while the pattern has not yet been compiled into a push - so it
	is refused once the row is Active, and while an Apply is in flight."""
	_guard()
	if _apply_pending() or _apply_in_progress():
		frappe.throw(
			_("An Apply is in progress; wait for it to finish before un-approving.")
		)
	doc = _load_for_transition(name, ("Approved",), "un-approve")
	doc.status = "Proposed"
	doc.approved_by = None
	doc.save()
	frappe.db.commit()
	return {"ok": True, "status": doc.status}


@frappe.whitelist()
def restore_rejected_pattern(name: str) -> dict:
	"""Rejected->Proposed (the Rejected-tab restore, section 6.5)."""
	_guard()
	doc = _load_for_transition(name, ("Rejected",), "restore")
	doc.status = "Proposed"
	doc.review_note = None
	doc.save()
	frappe.db.commit()
	return {"ok": True, "status": doc.status}


@frappe.whitelist()
def snooze_learned_pattern(name: str, days=30) -> dict:
	"""Proposed->Snoozed for 7/30/90 days (dismiss-for-now, section 6.4)."""
	_guard()
	try:
		days = int(days)
	except (TypeError, ValueError):
		days = 0
	if days not in _SNOOZE_DAYS:
		frappe.throw(
			_("Snooze duration must be one of: {0} days.").format(
				", ".join(str(d) for d in _SNOOZE_DAYS)
			)
		)
	doc = _load_for_transition(name, ("Proposed",), "snooze")
	doc.status = "Snoozed"
	doc.snoozed_until = add_days(today(), days)
	doc.reviewed_by = frappe.session.user
	doc.reviewed_at = now_datetime()
	doc.save()
	frappe.db.commit()
	return {"ok": True, "status": doc.status, "snoozed_until": str(doc.snoozed_until)}


@frappe.whitelist()
def batch_approve(names) -> dict:
	"""Approve many at once - A-class ONLY. If ANY named row has an effective
	sensitivity of B or C, the WHOLE batch is refused (B needs individual
	disclosure; C is insight-only) - plan sections 4.1 / 6.4."""
	_guard()
	if isinstance(names, str):
		names = _parse_json(names, None)
	if not isinstance(names, list) or not names:
		frappe.throw(_("Provide a non-empty list of pattern names."))
	names = [str(n) for n in names]

	# Validate the whole set FIRST so a mixed batch approves nothing.
	rows = frappe.get_all(
		JLP,
		filters={"name": ["in", names]},
		fields=["name", "effective_sensitivity", "status"],
	)
	found = {r.name for r in rows}
	missing = [n for n in names if n not in found]
	if missing:
		frappe.throw(_("Unknown pattern(s): {0}.").format(", ".join(missing)))
	blocked = [r.name for r in rows if (r.effective_sensitivity or "") in ("B", "C")]
	if blocked:
		frappe.throw(
			_("Batch approve is A-class only; these need individual review: {0}.").format(
				", ".join(blocked)
			)
		)

	approved: list[str] = []
	for r in rows:
		approve_learned_pattern(r.name)
		approved.append(r.name)
	return {"ok": True, "approved": approved, "count": len(approved)}


def _apply_pending() -> bool:
	"""True while a learned-skills push is between enqueue and its terminal
	status (Phase-2 namespace: the un-approve gate keys off the LEARNED push -
	learned skills no longer ride the custom-skills push)."""
	try:
		from jarvis.chat.learned_skills_api import get_learned_skills_sync_status

		return bool(get_learned_skills_sync_status().get("pending"))
	except Exception:
		return False


def _apply_in_progress() -> bool:
	"""Compiler's apply-in-progress marker (set BEFORE compile_domain_skills, so
	it closes the compile -> flip TOCTOU window that the sync-status ``pending``
	flag alone misses)."""
	try:
		from jarvis.learning import compiler

		return bool(compiler.apply_in_progress())
	except Exception:
		return False


# --------------------------------------------------------------------------- #
# LLM polish (plan 5.5 Phase 2): optional one-turn draft rewrite
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def polish_learned_draft(name: str) -> dict:
	"""Rewrite a Proposed/Stale pattern's ``skill_draft`` for clarity via one
	silent gateway turn (``jarvis.learning.polish``). Requires the
	``pattern_llm_polish`` Settings flag (default off). The turn runs AS the
	calling System Manager - S1: never Administrator; polish re-asserts the
	identity on top of ``_guard``.

	A-class only, like approve/batch_approve: B/C drafts embed raw party names,
	and the polish prompt is A-class-clean BY CONSTRUCTION (``polish.py``) -
	party-named text must never reach the model turn (B/C are insight-only
	anyway, so polishing them would only burn the monthly budget).

	On success the polished text replaces ``skill_draft`` with
	``draft_edited=0`` and ``draft_polished=1``: it is still MACHINE text
	validated to keep the measured Evidence sentence verbatim, so the evidence
	line is NOT frozen (only a human edit freezes it) - but the polish marker
	stops the nightly mining/drift refresh from overwriting the polished
	wording with the deterministic template. On any not-ok outcome (budget
	exhausted, rejected output, gateway error) nothing is written and
	``{ok: False, text: None, reason}`` is returned - the stored template draft
	stands. The LearningTab "Polish with AI" button is a UI follow-up; this
	endpoint is the contract."""
	_guard()
	if not frappe.utils.cint(frappe.db.get_single_value(SETTINGS, "pattern_llm_polish")):
		frappe.throw(
			_("LLM polish is not enabled (Jarvis Settings, Behavioural Learning)."),
			frappe.ValidationError,
		)
	doc = _load_for_transition(name, ("Proposed", "Stale"), "polish")

	# A-class gate, mirroring approve_learned_pattern / batch_approve.
	if (doc.effective_sensitivity or "") != "A":
		frappe.throw(
			_(
				"Pattern {0} is {1}-class (insight only); only A-class (org-level) "
				"drafts can be polished."
			).format(name, doc.effective_sensitivity or "B/C")
		)

	from jarvis.learning import polish

	out = polish.polish_skill_draft(name, frappe.session.user)
	if not out.get("ok"):
		return {"ok": False, "text": None, "reason": out.get("reason") or ""}

	# The gateway turn above takes seconds: never doc.save() the pre-turn
	# snapshot (a full-document save would silently revert any concurrent
	# update_modified=False write to this row - e.g. the stale-pointer clear in
	# _clear_stale_materialized_pointers, or a mining re-persist). Re-verify
	# the status still allows polish, then write ONLY the changed columns.
	# update_modified stays at its default so a genuine concurrent SM edit is
	# still caught by the modified-timestamp concurrency check.
	status = frappe.db.get_value(JLP, name, "status")
	if status not in ("Proposed", "Stale"):
		return {
			"ok": False,
			"text": None,
			"reason": f"pattern is now {status}; polish discarded",
		}
	frappe.db.set_value(
		JLP,
		name,
		{"skill_draft": out["text"], "draft_edited": 0, "draft_polished": 1},
	)
	frappe.db.commit()
	return {"ok": True, "text": out["text"]}


# --------------------------------------------------------------------------- #
# correction loop (plan 6.5): chat users flag a learned default as wrong
# --------------------------------------------------------------------------- #
def _system_user_guard() -> None:
	"""Any authenticated DESK user may flag (deliberately NOT SM-only - the
	whole point is the chat user's feedback); Guest and portal (Website User)
	sessions are refused."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(
			_("You must be signed in to flag a learned default."),
			frappe.PermissionError,
		)
	if frappe.db.get_value("User", user, "user_type") != "System User":
		frappe.throw(
			_("Only desk users can flag learned defaults."),
			frappe.PermissionError,
		)


@frappe.whitelist()
def flag_learned_default(name: str, note: str = "") -> dict:
	"""Record "this default was wrong here" against an Active/Approved learned
	pattern (plan 6.5 correction loop - the JLP ref in every compiled bullet is
	the address a chat user quotes).

	One counter-evidence entry per user ({user, note, ts}; a re-flag updates
	that user's entry instead of stacking), and ``flags_count`` counts one flag
	PER USER (a same-user re-flag updates the note, never the tally). Demotion
	needs a genuine quorum: flags from >= 2 DISTINCT users demote
	``strength_band`` one level, stamp the durable ``flag_band_cap`` (every
	pipeline strength_band write clamps to the weaker of computed band and cap,
	so the nightly mining/drift refresh cannot silently undo the demotion),
	annotate ``stale_reason`` and send System Managers a Notification Log. A
	re-flag inside the per-user cooldown neither re-demotes nor re-notifies, so
	a single user can never ratchet a shared default to the floor alone. When
	the quorum lands the pattern at Low, the row flips to Stale - the
	compiler's existing stale exclusion stops serving it on the next Apply and
	the board shows "will be removed"; re-approving restores it (and clears the
	cap + reason).

	TOCTOU-safe: the row is read FOR UPDATE, so concurrent flags serialize on
	the row lock instead of losing counter increments. The chat-side UI
	affordance on the skill badge is a follow-up; this endpoint is the
	contract."""
	_system_user_guard()
	if _is_self_hosted():
		frappe.throw(
			_("Pattern learning is not available on self-hosted benches."),
			frappe.ValidationError,
		)

	note = frappe.utils.strip_html_tags(note or "").strip()[:_FLAG_NOTE_MAX]

	row = frappe.db.get_value(
		JLP,
		name,
		["name", "status", "counter_evidence", "flags_count", "strength_band"],
		as_dict=True,
		for_update=True,
	)
	if not row:
		frappe.throw(_("Unknown learned pattern: {0}.").format(name))
	if row.status not in ("Approved", "Active"):
		frappe.throw(
			_(
				"Pattern {0} is {1}; only Active or Approved learned defaults can be flagged."
			).format(name, row.status)
		)

	user = frappe.session.user
	entries = [
		e for e in (_parse_json(row.counter_evidence, []) or [])
		if isinstance(e, dict)
	]
	now = now_datetime()
	mine = next((e for e in entries if e.get("user") == user), None)
	in_cooldown = False
	if mine is not None:  # dedupe: update this user's flag in place
		in_cooldown = _within_flag_cooldown(mine.get("ts"), now)
		mine["note"] = note
		mine["ts"] = str(now)
	else:
		entries.append({"user": user, "note": note, "ts": str(now)})

	# One count per user (mirrors the entry dedupe): a same-user re-flag must
	# not inch the tally toward any threshold.
	flags_count = int(row.flags_count or 0) + (0 if mine is not None else 1)
	distinct_users = len({e.get("user") for e in entries if e.get("user")})

	update = {"counter_evidence": frappe.as_json(entries), "flags_count": flags_count}
	band = row.strength_band
	status = row.status
	demoted = False
	if distinct_users >= _FLAG_DISTINCT_USERS and not in_cooldown:
		new_band = _BAND_DEMOTE.get(band or "Low", "Low")
		if new_band != band or new_band == "Low":
			update["strength_band"] = new_band
			# Durable cap (shared contract): mining/drift clamp their band
			# writes to it; approve_learned_pattern clears it.
			update["flag_band_cap"] = new_band
			update["stale_reason"] = f"{_FLAG_STALE_PREFIX} {distinct_users} users"
			band = new_band
			demoted = True
			if new_band == "Low":
				# Floored: stop serving it. Stale rows are excluded from the
				# next compile (Active -> Stale and Approved -> Stale are both
				# legal transitions); an SM re-approve restores the pattern.
				update["status"] = "Stale"
				status = "Stale"
	frappe.db.set_value(JLP, name, update, update_modified=False)
	frappe.db.commit()

	if demoted:
		_notify_flag_demotion(
			name, distinct_users, flags_count, band, staled=(status == "Stale")
		)

	return {
		"ok": True,
		"flags_count": flags_count,
		"distinct_users": distinct_users,
		"strength_band": band or "",
		"status": status,
		"demoted": demoted,
	}


def _within_flag_cooldown(prev_ts, now) -> bool:
	"""True when this user's previous flag is younger than the cooldown window.
	A missing/unparsable timestamp counts as recent (fail closed: no demotion
	credit for an entry we cannot age)."""
	if not prev_ts:
		return True
	try:
		prev = frappe.utils.get_datetime(prev_ts)
	except Exception:
		return True
	if not prev:
		return True
	return (now - prev).total_seconds() < _FLAG_COOLDOWN_HOURS * 3600


def _notify_flag_demotion(
	name: str, distinct_users: int, flags_count: int, band, staled: bool = False
) -> None:
	"""Best-effort SM notification when the flag quorum demotes a pattern
	(shares lifecycle's Notification Log helper with drift re-validation)."""
	try:
		from jarvis.learning.lifecycle import notify_system_managers

		statement = frappe.db.get_value(JLP, name, "pattern_statement") or name
		tail = (
			" and it was marked Stale - its bullet is removed from the pushed "
			"learned skills on the next Apply"
			if staled
			else ""
		)
		notify_system_managers(
			f"Learned pattern {name} was flagged as wrong",
			(
				f"Chat users flagged this learned default as wrong "
				f"({distinct_users} user{'s' if distinct_users != 1 else ''}, "
				f"{flags_count} flag{'s' if flags_count != 1 else ''}); its strength "
				f"was demoted to {band}{tail}.\n\n\"{statement}\"\n\n"
				"Review it on the Learning board - approve it again if the habit "
				"still holds, or reject it for good."
			),
		)
	except Exception:
		pass


def _counter_evidence_list(raw) -> list:
	parsed = _parse_json(raw, [])
	if not isinstance(parsed, list):
		return []
	return [e for e in parsed if isinstance(e, dict)]


# --------------------------------------------------------------------------- #
# apply / sync (dedicated learned-skills push - Phase-2 namespace, plan 13 Q5)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def apply_learned_skills() -> dict:
	"""Recompile approved patterns into the ``learned-<domain>`` skills and push
	them (delegates to ``jarvis.learning.compiler.apply_learned_skills`` - Wave
	C1). Returns the compiler's sync-status handle; poll with
	``get_learned_apply_status``."""
	_guard()
	from jarvis.learning import compiler

	out = compiler.apply_learned_skills()
	# Stale rows are excluded from compile, so after this Apply their old
	# materialized_skill pointer is no longer live in the pushed body. Clearing
	# it here (the compiler only stamps rows it compiled) is what drains the
	# "N stale will be removed on Apply" count instead of wedging the bar.
	_clear_stale_materialized_pointers()
	return out


def _clear_stale_materialized_pointers() -> None:
	names = frappe.get_all(
		JLP,
		filters={"status": "Stale", "materialized_skill": ["is", "set"]},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value(JLP, name, {"materialized_skill": None}, update_modified=False)
	if names:
		frappe.db.commit()


@frappe.whitelist()
def get_learned_apply_status() -> dict:
	"""Poll the Apply - learned skills ride their OWN dedicated push (Phase-2
	namespace), so this proxies the learned sync-status poller
	(``learned_skills_sync_status`` / ``learned_skills_synced_at``). Same
	envelope shape as before ({last_sync_at, last_sync_status, pending}) plus
	``custom_sync``: the one-time namespace-cutover Apply also enqueues a
	custom-skills reconcile (stale ``custom-learned-*`` dir cleanup) that
	reports to the SEPARATE custom sync pair - included here so a failed
	cutover reconcile is visible on the board instead of fire-and-forget."""
	_guard()
	from jarvis.chat.learned_skills_api import get_learned_skills_sync_status

	out = get_learned_skills_sync_status()
	out["custom_sync"] = _cutover_custom_sync_status(out)
	return out


# How long after a learned push the board still surfaces the custom pair (the
# cutover's custom reconcile lands within minutes of the learned push).
_CUTOVER_SURFACE_HOURS = 24


def _cutover_custom_sync_status(learned: dict):
	"""The cutover's custom reconcile outcome, or None when no recent Apply
	could have run one. Until the compiler stamps a dedicated cutover marker in
	Jarvis Settings, key off recency: include the custom pair whenever the
	learned push is pending or finished inside the surface window (the polls
	that can belong to a cutover Apply). Best-effort - never fails the poll."""
	try:
		if not learned.get("pending"):
			last_raw = (learned.get("last_sync_at") or "").strip()
			if not last_raw:
				return None
			last = frappe.utils.get_datetime(last_raw)
			if not last:
				return None
			age = (now_datetime() - last).total_seconds()
			if age > _CUTOVER_SURFACE_HOURS * 3600:
				return None
		from jarvis.chat.custom_skills_api import get_custom_skills_sync_status

		return get_custom_skills_sync_status()
	except Exception:
		return None


@frappe.whitelist()
def pending_learned_count() -> int:
	"""Board badge: surfaced patterns still awaiting a decision (the sibling of
	``approvals_api.pending_count``)."""
	_guard()
	return frappe.db.count(JLP, {"status": "Proposed", "surfaced": 1})


# --------------------------------------------------------------------------- #
# run now (section 5.1 / 5.2 manual bypass)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def run_pattern_analysis_now() -> dict:
	"""Enqueue a manual pattern-analysis run (bypasses the analysis window, keeps
	the row budget + statement timeouts). Returns the orchestrator's
	``{ok, run, reason}``. The business-hours load warning is a UI concern."""
	_guard()
	from jarvis.learning import orchestrator

	return orchestrator.run_now(frappe.session.user)


# --------------------------------------------------------------------------- #
# settings + status (the in-tab config surface, section 6.4)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def get_learning_settings(include_preflight=0) -> dict:
	"""Read the ``pattern_*`` config the tab exposes (SM only). ``include_preflight``
	runs the (potentially expensive) enablement readiness probe lazily - only when
	the caller asks (e.g. the enable modal)."""
	_guard()
	s = frappe.get_single(SETTINGS)
	settings = {}
	for f in _SETTINGS_FIELDS:
		val = s.get(f)
		# Coalesce a null Single field (never seeded) to its default so the card
		# never shows a blank window / 0 max / 0 budget.
		if val in (None, "") and f in _SETTINGS_DEFAULTS:
			val = _SETTINGS_DEFAULTS[f]
		settings[f] = val
	settings["pattern_learning_enabled"] = int(settings.get("pattern_learning_enabled") or 0)
	for tf in ("pattern_window_start", "pattern_window_end"):
		settings[tf] = str(settings.get(tf) or "")

	preflight = None
	if frappe.utils.cint(include_preflight):
		try:
			from jarvis.learning.bootstrap import enablement_preflight

			preflight = enablement_preflight()
		except Exception:
			preflight = {"supported": False, "error": True}

	return {"settings": settings, "preflight": preflight}


@frappe.whitelist()
def set_learning_settings(payload=None) -> dict:
	"""Write the ``pattern_*`` config via the Settings doc so window validation
	runs (>=1h, wrap-aware - plan section 5.1). Only the config fields are
	writable; the engine status quartet is engine-owned. Unknown keys are
	refused. Returns the fresh ``get_learning_settings``."""
	_guard()
	if isinstance(payload, str):
		payload = _parse_json(payload, None)
	if not isinstance(payload, dict) or not payload:
		frappe.throw(_("Provide a settings object to write."))

	unknown = [k for k in payload if k not in _SETTINGS_FIELDS]
	if unknown:
		frappe.throw(_("Unknown settings field(s): {0}.").format(", ".join(unknown)))

	# Merge the payload onto the current values IN MEMORY and run the SAME
	# >=1h wrap-aware window validator - but do NOT doc.save(): a full save fires
	# Jarvis Settings.on_update (LLM pool re-sync), an unrelated side effect for a
	# pattern_* write. The config fields are then written directly via
	# frappe.db.set_value(update_modified=False), so on_update never fires (plan
	# section 5.1). The enabled + zero/blank-window guard rides the same
	# validator (it throws when enabled with no/sub-1h window).
	doc = frappe.get_single(SETTINGS)
	for k, v in payload.items():
		doc.set(k, v)
	doc._validate_pattern_window()

	values = {k: doc.get(k) for k in payload}
	# set_single_value (not set_value on the Single, which Frappe deprecates):
	# a direct write that never fires on_update. Wrap-aware validation ran above.
	frappe.db.set_single_value(SETTINGS, values, update_modified=False)
	frappe.db.commit()
	return get_learning_settings()


@frappe.whitelist()
def get_learning_status() -> dict:
	"""Last-run summary + next-run pointer + self-host flag. Deliberately NOT
	self-host-gated (SM-only still): it is the probe the tab uses to render the
	managed-only empty state, so it must stay reachable on self-host."""
	frappe.only_for("System Manager")
	self_hosted = _is_self_hosted()
	s = frappe.get_single(SETTINGS)

	latest = frappe.get_all(
		RUN,
		fields=[
			"name", "status", "trigger", "started_at", "ended_at",
			"proposals_created", "proposals_updated", "candidates_found",
			"coverage_note", "creation",
		],
		order_by="creation desc",
		limit=1,
	)
	latest_run = latest[0] if latest else None
	if latest_run:
		for k in ("started_at", "ended_at", "creation"):
			latest_run[k] = str(latest_run.get(k) or "")

	return {
		"self_hosted": int(self_hosted),
		"enabled": int(s.get("pattern_learning_enabled") or 0),
		"last_run_at": str(s.get("pattern_last_run_at") or ""),
		"last_run_status": s.get("pattern_last_run_status") or "",
		"next_run_at": str(s.get("pattern_next_run_at") or ""),
		"scan_mode": s.get("pattern_scan_mode") or "",
		"latest_run": latest_run,
	}
