"""Learned-pattern lifecycle: dedupe, suppression, expiry, retention (plan 6.5).

``upsert_candidate`` REPLACES the engine's minimal inline ``_persist_candidate``
(the engine imports it lazily and delegates when present; its inline version is
the fallback). The candidate-dict contract is the stable boundary - see the
engine module docstring.

Rules (plan section 6.5):
  * dedupe on ``pattern_key`` (unique); non-terminal rows refresh evidence in
    place and bump ``last_seen_run`` - an SM-edited draft (``draft_edited=1``) is
    never overwritten (enforced by ``engine._apply_evidence``);
  * Rejected stays suppressed UNLESS the band rises or ``support_n`` grows >=50%,
    which auto re-proposes it (pattern_key is unique, so the SAME row flips
    Rejected -> Proposed carrying a prior-rejection note, rather than a duplicate
    row);
  * Snoozed / Stale refresh evidence only (status untouched);
  * Superseded / Archived are skipped (last_seen_run stamped as suppression
    memory);
  * ``snooze_expiry`` un-snoozes elapsed rows; ``retention`` archives Rejected
    >180d / Superseded >90d (evidence trimmed, pattern_key kept);
  * ``overlap_warning`` is a warn-only lexical check vs the customer's own
    enabled skills;
  * ``revalidate_active`` (drift -> Stale) is an explicit Phase-1 no-op stub
    (the plan schedules drift for early Phase 2).
"""

from __future__ import annotations

import contextlib
import re

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime, today

JLP = "Jarvis Learned Pattern"
SKILL = "Jarvis Custom Skill"

TERMINAL_SKIP_STATUSES = frozenset({"Superseded", "Archived"})
_REFRESH_STATUSES = frozenset({"Proposed", "Approved", "Active", "Snoozed", "Stale"})

_BAND_RANK = {"High": 0, "Medium": 1, "Low": 2}

REJECTED_TTL_DAYS = 180
SUPERSEDED_TTL_DAYS = 90

_MAX_NOTE_LEN = 500

# Overlap check: ignore short/common words so a warning means real shared wording.
_OVERLAP_MIN_SHARED = 3
_STOPWORDS = frozenset({
	"this", "that", "with", "from", "into", "your", "will", "when", "then",
	"they", "them", "have", "which", "usually", "default", "defaults", "skill",
	"skills", "learned", "these", "those", "about", "over", "under", "each",
	"document", "documents", "always", "never", "should", "there", "their",
})


# --------------------------------------------------------------------------- #
# surfacing order (shared helper; plan section 6.4)
# --------------------------------------------------------------------------- #
def surfacing_sort_key(row) -> tuple:
	"""Ranking for proposal surfacing: **party-specific personalization ranked
	ahead of config-cleanup** (plan section 6.4 - debt-heavy sites must not bury
	the marquee wins), THEN strength band, THEN support_n descending.

	A named-party bullet is escalated to effective sensitivity B/C (A-class never
	names a party), so ``effective_sensitivity in (B, C)`` is the party-specific
	signal and A is config-cleanup. ``row`` is a dict / ``frappe._dict`` carrying
	``effective_sensitivity``, ``strength_band`` and ``support_n``.

	Cross-file coordination: ``engine._promote_surfaced`` (group 2) currently
	orders on band+support only and does NOT fetch ``effective_sensitivity``; it
	should add that field to its ``get_all`` and sort with this helper so the
	party-before-config priority takes effect. Exposed here (a file this fixer
	owns) rather than edited into engine.py to keep the assignments disjoint."""
	get = row.get if hasattr(row, "get") else (lambda k, d=None: getattr(row, k, d))
	eff = (get("effective_sensitivity") or "").strip().upper()
	party_rank = 0 if eff in ("B", "C") else 1
	band_rank = _BAND_RANK.get(get("strength_band"), 3)
	return (party_rank, band_rank, -(get("support_n") or 0))


@contextlib.contextmanager
def _engine_flag():
	"""Bypass the JLP transition guard for engine-driven writes. Restores the
	prior value so nested use (engine already inside a run) is a no-op."""
	prev = frappe.flags.jarvis_pattern_engine
	frappe.flags.jarvis_pattern_engine = True
	try:
		yield
	finally:
		frappe.flags.jarvis_pattern_engine = prev


# --------------------------------------------------------------------------- #
# upsert (engine delegates here)
# --------------------------------------------------------------------------- #
def upsert_candidate(candidate: dict, run) -> str:
	"""Dedupe + persist one candidate. Returns 'created' | 'updated' |
	'duplicate' (the engine's per-unit counters key off these)."""
	from jarvis.learning import engine as eng

	pattern_key = candidate.get("pattern_key")
	if not pattern_key:
		# Unkeyed candidates cannot be deduped safely; drop (suppressed).
		return "duplicate"

	existing = frappe.db.exists(JLP, {"pattern_key": pattern_key})
	if not existing:
		return _insert_new(candidate, run, eng)

	status = frappe.db.get_value(JLP, existing, "status")
	if status in TERMINAL_SKIP_STATUSES:
		frappe.db.set_value(JLP, existing, {"last_seen_run": run.name}, update_modified=False)
		return "duplicate"
	if status == "Rejected":
		return _handle_rejected(existing, candidate, run, eng)

	# Proposed / Approved / Active / Snoozed / Stale: refresh evidence in place.
	doc = frappe.get_doc(JLP, existing)
	with _engine_flag():
		eng._apply_evidence(doc, candidate, run, is_new=False)
		_set_overlap(doc)
		doc.save(ignore_permissions=True)
	return "updated"


def _insert_new(candidate: dict, run, eng, *, status: str = "Proposed", note: str | None = None) -> str:
	doc = frappe.get_doc({"doctype": JLP, "pattern_key": candidate["pattern_key"], "status": status})
	with _engine_flag():
		eng._apply_evidence(doc, candidate, run, is_new=True)
		_set_overlap(doc)
		if note:
			doc.review_note = note[:_MAX_NOTE_LEN]
		doc.insert(ignore_permissions=True)
	return "created"


def _handle_rejected(existing: str, candidate: dict, run, eng) -> str:
	"""Durable suppression, reversible on strengthening (plan section 6.5)."""
	prev = frappe.db.get_value(
		JLP, existing, ["strength_band", "support_n", "review_note"], as_dict=True
	) or frappe._dict()
	new_rank = _BAND_RANK.get(candidate.get("strength_band"), 3)
	old_rank = _BAND_RANK.get(prev.strength_band, 3)
	band_rose = new_rank < old_rank
	old_n = prev.support_n or 0
	new_n = candidate.get("support_n") or 0
	n_grew = old_n > 0 and new_n >= old_n * 1.5

	if not (band_rose or n_grew):
		# Still weak: remember we saw it again, stay Rejected (suppression memory).
		frappe.db.set_value(JLP, existing, {"last_seen_run": run.name}, update_modified=False)
		return "duplicate"

	# Re-propose. pattern_key is UNIQUE, so we reuse THIS row (Rejected ->
	# Proposed) rather than a literally-new row, preserving the prior note.
	reason = "band rose" if band_rose else f"support grew to {new_n}"
	note = f"Auto re-proposed ({reason} since rejection)."
	prior = (prev.review_note or "").strip()
	if prior:
		note = f"{note} Prior note: {prior}"

	doc = frappe.get_doc(JLP, existing)
	with _engine_flag():
		doc.status = "Proposed"
		eng._apply_evidence(doc, candidate, run, is_new=False)
		doc.surfaced = 0
		doc.surfaced_at = None
		doc.reviewed_by = None
		doc.reviewed_at = None
		doc.review_note = note[:_MAX_NOTE_LEN]
		_set_overlap(doc)
		doc.save(ignore_permissions=True)
	return "created"


# --------------------------------------------------------------------------- #
# snooze expiry + retention (cheap; implemented per assignment)
# --------------------------------------------------------------------------- #
def snooze_expiry() -> dict:
	"""Snoozed rows whose ``snoozed_until`` has passed return to Proposed and
	re-enter surfacing. Null ``snoozed_until`` is excluded by the filter."""
	names = frappe.get_all(
		JLP, filters={"status": "Snoozed", "snoozed_until": ["<=", today()]}, pluck="name"
	)
	moved = 0
	for name in names:
		try:
			doc = frappe.get_doc(JLP, name)
			with _engine_flag():
				doc.status = "Proposed"
				doc.snoozed_until = None
				doc.surfaced = 0
				doc.surfaced_at = None
				doc.save(ignore_permissions=True)
			moved += 1
		except Exception:
			frappe.log_error(
				title=f"jarvis pattern learning: un-snooze failed for {name}",
				message=frappe.get_traceback(),
			)
	if moved:
		frappe.db.commit()
	return {"unsnoozed": moved}


def retention() -> dict:
	"""Archive Rejected >180d / Superseded >90d: trim evidence, keep pattern_key
	(suppression memory persists). Age is measured from ``modified`` - a
	re-detection stamps last_seen_run with update_modified=False, so a
	still-seen Rejected row ages from its rejection, not its last sighting."""
	now = now_datetime()
	archived = 0
	for status, ttl in (("Rejected", REJECTED_TTL_DAYS), ("Superseded", SUPERSEDED_TTL_DAYS)):
		cutoff = str(get_datetime(add_to_date(now, days=-ttl)))
		names = frappe.get_all(
			JLP, filters={"status": status, "modified": ["<", cutoff]}, pluck="name"
		)
		for name in names:
			try:
				doc = frappe.get_doc(JLP, name)
				with _engine_flag():
					doc.status = "Archived"
					doc.evidence = None  # trimmed; pattern_key stays for suppression
					doc.save(ignore_permissions=True)
				archived += 1
			except Exception:
				frappe.log_error(
					title=f"jarvis pattern learning: archive failed for {name}",
					message=frappe.get_traceback(),
				)
	if archived:
		frappe.db.commit()
	return {"archived": archived}


# --------------------------------------------------------------------------- #
# re-validation / drift (Phase-1 no-op stub)
# --------------------------------------------------------------------------- #
def revalidate_active(run=None) -> dict:
	"""Phase-1 no-op. TODO(Phase 2 drift): re-run each Approved/Active pattern's
	source checker through the READ ONLY fence, refresh stats, and move rows
	whose ``wilson_low`` drops below threshold to Stale (+ a Notification Log to
	the reviewing SMs); stale rules drop out of the next compile, never silently.
	The plan schedules drift for early Phase 2; the driver may call this
	unconditionally today and get a clean no-op."""
	return {"revalidated": 0, "staled": 0, "stub": True}


# --------------------------------------------------------------------------- #
# overlap warning (warn-only, lexical, vs the customer's own enabled skills)
# --------------------------------------------------------------------------- #
def compute_overlap_warning(pattern_statement, skill_draft) -> str | None:
	"""Return a warn-only note if this pattern's wording lexically overlaps an
	enabled customer-authored (non-managed) skill, else None."""
	index = _skill_token_index()
	if not index:
		return None
	pat = _tokens(f"{pattern_statement or ''} {skill_draft or ''}")
	if not pat:
		return None
	best_name = None
	best_score = 0
	for sname, toks in index:
		score = len(pat & toks)
		if score >= _OVERLAP_MIN_SHARED and score > best_score:
			best_name, best_score = sname, score
	if best_name:
		return (
			f"May overlap with your custom skill '{best_name}' (shared wording); "
			"review before applying."
		)
	return None


def _set_overlap(doc) -> None:
	warning = compute_overlap_warning(doc.get("pattern_statement"), doc.get("skill_draft"))
	# Only clear an existing warning to None if we recomputed (avoids churn).
	doc.overlap_warning = warning


def _skill_token_index():
	"""Job-scoped token index of enabled non-managed skills (avoids an N+1 across
	a run's many candidates). Stashed on frappe.local for the job's lifetime."""
	cached = getattr(frappe.local, "_jarvis_overlap_index", None)
	if cached is not None:
		return cached
	index: list = []
	try:
		rows = frappe.get_all(
			SKILL,
			filters={"enabled": 1, "managed_by_learning": 0},
			fields=["skill_name", "description"],
		)
	except Exception:
		rows = []
	for r in rows:
		toks = _tokens(f"{(r.get('skill_name') or '').replace('-', ' ')} {r.get('description') or ''}")
		if toks:
			index.append((r.get("skill_name"), toks))
	try:
		frappe.local._jarvis_overlap_index = index
	except Exception:
		pass
	return index


def _tokens(text: str) -> set:
	return {
		w for w in re.findall(r"[a-z0-9]{4,}", (text or "").lower())
		if w not in _STOPWORDS
	}
