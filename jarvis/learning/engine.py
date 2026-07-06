"""Pattern-learning engine: the nightly run driver (plan sections 5.2-5.6).

ONE job per night that loops internally (no mid-run self-re-enqueue: frappe's
job-id dedup drops a STARTED job's own re-enqueue). The orchestrator hands us a
``Jarvis Pattern Run`` name; we single-flight on a redis lock, run as
Administrator with the write fence lifted for our own four doctypes, walk the
work units (company, detector_spec), and pause gracefully at window end / the
worker budget / the row budget, persisting the ordered remaining units so the
next tick continues them.

Fence discipline (plan section 5.4): detectors read ONLY through the SELECT-only
``PatternDB`` inside a ``read_only_transaction()``. That context manager raises
``ImplicitCommitError`` if writes are pending at entry, so every unit is
``commit -> open fence -> read -> close fence (auto ROLLBACK) -> persist writes
-> commit``. Detector reads and engine writes never share a transaction.

--------------------------------------------------------------------------------
CANDIDATE DICT CONTRACT (what a detector emits; what ``_persist_candidate`` and
Wave C's ``lifecycle.upsert_candidate`` consume). Maps 1:1 onto Jarvis Learned
Pattern fields:

    {
      "detector_id":          str,   # registry id, e.g. "buy-supplier-stockness"
      "pattern_key":          str,   # REQUIRED, unique dedupe key (detector + company + antecedent + consequent)
      "domain":               str,   # selling|buying|stock|accounts|projects|org
      "company":              str|None,
      "roles":                list[str],   # detected role names -> Jarvis Learned Pattern Role child rows (insert only)
      "pattern_statement":    str,   # REQUIRED, plain-English sentence
      "skill_draft":          str,   # REQUIRED, deterministic template body (never overwritten once draft_edited=1)
      "support_n":            int,   # n_units (independent units, never child rows)
      "n_rows":               int,   # raw rows (drill-down only)
      "exception_n":          int,
      "confidence_pct":       float, # 0-100
      "wilson_low":           float, # 0-1
      "gap":                  float, # confidence - leave-segment-out base rate
      "strength_band":        str,   # High|Medium|Low
      "temporal_spread":      dict|str|None,   # stored as JSON
      "evidence":             dict|str|None,   # aggregates + exception refs, JSON (never embedded in skill text)
      "exceptions_cluster":   str|None,
      "sensitivity":          str,   # declared A|B|C
      "effective_sensitivity":str,   # escalated A|B|C (defaults to declared when absent)
      "not_applicable":       bool,
    }

DETECTOR RESULT CONTRACT (what ``executor.run_detector(spec, company, patterndb)``
returns; the engine tolerates a bare list of candidates too):

    {
      "candidates":    list[candidate],   # may be empty
      "rows_scanned":  int,               # EXPLAIN-estimated; charged against the row budget
      "skipped":       str|None,          # field-guard / requires_app / not-applicable reason
      "doctypes_read": list[str],
      "not_applicable":bool,              # -> Detector State.not_applicable
      "data_starved":  bool,              # -> Detector State.data_starved
    }

--------------------------------------------------------------------------------
Wave C REPLACES ``_persist_candidate`` (and adds surfacing/compile) via
``jarvis.learning.lifecycle.upsert_candidate``: import it here and delegate when
present. The candidate contract above is the stable boundary between the two.
"""

from __future__ import annotations

import time

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from jarvis.learning.orchestrator import (
	WORKER_TIMEOUT_S,
	_feature_enabled,
	should_pause_for_window,
)
from jarvis.learning.readonly_db import read_only_transaction

RUN = "Jarvis Pattern Run"
JLP = "Jarvis Learned Pattern"
JLP_ROLE = "Jarvis Learned Pattern Role"
DETECTOR_STATE = "Jarvis Pattern Detector State"
SNAPSHOT = "Jarvis Pattern Snapshot"
SETTINGS = "Jarvis Settings"

LOCK_NAME = "jarvis_pattern_run"

# Write fence (plan §5.4, defense-in-depth). Engine persistence may target ONLY
# these doctypes; JLP_ROLE is the child table the JLP insert writes as part of
# the same document. The READ ONLY transaction already blocks detector writes at
# the database - this asserts the ENGINE never persists anywhere unexpected. The
# Settings status backstop and failure Notification Logs are deliberately NOT
# routed through the fence: they are not pattern persistence.
ALLOWED_WRITE_DOCTYPES = frozenset({RUN, DETECTOR_STATE, JLP, JLP_ROLE, SNAPSHOT})


class PatternWriteFenceError(Exception):
	"""Engine tried to persist to a doctype outside the §5.4 allowlist."""


def _fenced_write(doctype: str) -> None:
	"""Assert an engine write targets an allowlisted doctype (plan §5.4)."""
	if doctype not in ALLOWED_WRITE_DOCTYPES:
		raise PatternWriteFenceError(
			f"pattern engine write to non-allowlisted doctype: {doctype!r}"
		)

# Stop this far before the RQ worker timeout so a unit's writes finish cleanly.
_RUN_BUDGET_BUFFER_S = 120
MAX_RUN_SECONDS = WORKER_TIMEOUT_S - _RUN_BUDGET_BUFFER_S

DEFAULT_ROW_BUDGET = 500000
DORMANT_DAYS = 180
ERROR_BUDGET_FRACTION = 0.30

# Rows created and evidence-refreshed here; Rejected/Archived/Superseded rows
# are durable suppression memory and are NOT resurrected by the engine (Wave C
# lifecycle re-proposes on band rise / n +50%).
TERMINAL_STATUSES = frozenset({"Rejected", "Archived", "Superseded"})

# Cheap dormant-shell probe: any ONE submitted core transaction in the window.
CORE_TXN_DOCTYPES = (
	"Sales Invoice",
	"Purchase Invoice",
	"Stock Entry",
	"Journal Entry",
	"Payment Entry",
)

_BAND_RANK = {"High": 0, "Medium": 1, "Low": 2}


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def run_pattern_analysis(run_name: str) -> None:
	"""Drive one nightly run to completion or a graceful pause. Single-flight:
	no-op if another run holds the lock. Enqueued by the orchestrator on queue
	``long`` under job_id ``jarvis_pattern_run::<run>``."""
	from jarvis._redis_lock import redis_lock

	with redis_lock(LOCK_NAME, timeout_s=WORKER_TIMEOUT_S, blocking_timeout_s=0) as acquired:
		if not acquired:
			# Another worker is already running the night's job (or a stray
			# hop). Coalesce and move on.
			return
		_run_locked(run_name)


def _run_locked(run_name: str) -> None:
	original_user = frappe.session.user
	engine_flag_prev = frappe.flags.jarvis_pattern_engine
	status_summary = "Failed: run did not start"
	scan_mode = "full"
	try:
		frappe.set_user("Administrator")
		frappe.flags.jarvis_pattern_engine = True
		status_summary, scan_mode = _execute(run_name)
	except Exception:
		frappe.log_error(
			title=f"jarvis pattern learning: engine crashed on {run_name}",
			message=frappe.get_traceback(),
		)
		status_summary = f"Failed: unhandled engine error on {run_name} (see Error Log)"
		try:
			_finalize_run(
				run_name,
				status="Failed",
				counts=None,
				skipped=None,
				errors=None,
				doctypes=None,
				remaining=None,
				note="Unhandled engine error; see the Error Log.",
			)
		except Exception:
			pass
	finally:
		# Terminal status-quartet backstop (plan section 5.6). set_value with
		# update_modified=False so the Settings on_update LLM classifier never
		# fires (never doc.save() here).
		try:
			frappe.db.set_value(
				SETTINGS,
				SETTINGS,
				{
					"pattern_last_run_at": now_datetime(),
					"pattern_last_run_status": status_summary,
					"pattern_scan_mode": scan_mode,
				},
				update_modified=False,
			)
			frappe.db.commit()
		except Exception:
			pass
		frappe.flags.jarvis_pattern_engine = engine_flag_prev
		try:
			frappe.set_user(original_user)
		except Exception:
			pass


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #
def _execute(run_name: str) -> tuple[str, str]:
	run = frappe.get_doc(RUN, run_name)
	scan_mode = run.scan_mode or "full"
	now = now_datetime()

	# Mark Running + heartbeat, keep the original started_at across a resume.
	start_update = {"status": "Running", "heartbeat_at": now}
	if not run.started_at:
		start_update["started_at"] = now
	_write_run(run_name, start_update)
	frappe.db.commit()  # clean transaction before the first fence

	# Registry is provided by the parallel builder; import lazily so this
	# module still imports standalone. Missing registry -> Failed, not a crash.
	try:
		from jarvis.learning import registry
	except Exception:
		note = "Detector registry is not available; run could not start."
		_finalize_run(run_name, status="Failed", counts=None, skipped=None,
					  errors=None, doctypes=None, remaining=None, note=note)
		return (f"Failed: {note}", scan_mode)

	companies = frappe.get_all("Company", pluck="name")
	active_companies = skip_dormant_companies(companies)

	units = _load_work_units(run, active_companies, registry)
	_write_run(run_name, {"detectors_total": len(units)})
	frappe.db.commit()

	if not units:
		note = _no_units_note(companies, active_companies)
		_finalize_run(run_name, status="Completed", counts=_zero_counts(),
					  skipped=None, errors=None, doctypes=None, remaining=None, note=note)
		return (f"Completed: {note}", scan_mode)

	row_budget = int(_settings_value("pattern_row_budget_per_night") or DEFAULT_ROW_BUDGET)
	started_mono = time.monotonic()

	counts = _zero_counts()
	skipped: list = []
	errors: list = []
	doctypes: set = set()
	attempted = 0
	error_count = 0
	paused_note = None
	remaining: list | None = None

	for idx, (company, spec) in enumerate(units):
		reason = _pause_reason(run, started_mono, counts["rows"], row_budget)
		if reason:
			paused_note = reason
			remaining = _serialize_remaining(units[idx:])
			break

		detector_id = _spec_id(spec)
		attempted += 1
		try:
			unit = _read_and_persist(spec, company, run)
		except Exception:
			error_count += 1
			frappe.log_error(
				title=f"jarvis pattern detector failed: {detector_id} / {company}",
				message=frappe.get_traceback(),
			)
			errors.append({
				"detector_id": detector_id,
				"company": company,
				"error": _short_error(),
			})
			_touch_detector_state(detector_id, last_error=_short_error(), last_run_at=now_datetime())
			continue

		counts["completed"] += 1
		counts["rows"] += unit["rows"]
		counts["candidates"] += unit["candidates"]
		counts["created"] += unit["created"]
		counts["updated"] += unit["updated"]
		counts["duplicates"] += unit["duplicates"]
		if unit["skipped"]:
			skipped.append({"detector_id": detector_id, "company": company, "reason": unit["skipped"]})
		doctypes.update(unit["doctypes"])
		_touch_detector_state(
			detector_id,
			last_run_at=now_datetime(),
			last_full_scan_at=now_datetime(),
			rows_scanned_add=unit["rows"],
			data_starved=1 if unit["data_starved"] else 0,
			not_applicable=1 if unit["not_applicable"] else 0,
			last_error=None,
		)

		# Heartbeat + running counters every unit (stale-run watch keys off it).
		_write_run(
			run_name,
			{
				"heartbeat_at": now_datetime(),
				"detectors_completed": counts["completed"],
				"rows_scanned": counts["rows"],
				"candidates_found": counts["candidates"],
				"proposals_created": counts["created"],
				"proposals_updated": counts["updated"],
				"duplicates_suppressed": counts["duplicates"],
			},
		)
		frappe.db.commit()

	# Surfacing (band-then-support, >=1 per domain). Wave C may override.
	try:
		_promote_surfaced(run_name)
	except Exception:
		frappe.log_error(
			title=f"jarvis pattern learning: surfacing failed on {run_name}",
			message=frappe.get_traceback(),
		)

	status, note = _resolve_status(paused_note, attempted, error_count, skipped, errors)
	_finalize_run(
		run_name,
		status=status,
		counts=counts,
		skipped=skipped or None,
		errors=errors or None,
		doctypes=doctypes or None,
		remaining=remaining,
		note=note,
	)
	if status == "Failed":
		_notify_system_managers(run_name, error_count, attempted)

	summary = (
		f"{status}: run {run_name} - {counts['completed']}/{len(units)} detectors, "
		f"{counts['created']} new / {counts['updated']} updated proposals, "
		f"{counts['rows']} rows scanned."
	)
	if note:
		summary += f" {note}"
	return (summary, scan_mode)


# --------------------------------------------------------------------------- #
# per-unit read (fenced) + persist (unfenced)
# --------------------------------------------------------------------------- #
def _read_and_persist(spec, company, run) -> dict:
	from jarvis.learning.executor import run_detector

	frappe.db.commit()  # no pending writes before opening the READ ONLY fence
	with read_only_transaction() as pdb:
		raw = run_detector(spec, company, pdb)
	# Fence closed (auto ROLLBACK); the connection is writable again.
	norm = _normalize_detector_result(raw)

	created = updated = duplicates = 0
	for cand in norm["candidates"]:
		outcome = _persist_candidate(cand, run)
		if outcome == "created":
			created += 1
		elif outcome == "updated":
			updated += 1
		else:
			duplicates += 1

	# Read-audit: the executor does not report doctypes_read, so derive it from
	# the spec (base doctype + field-guard doctypes) for the run's audit record.
	doctypes = norm["doctypes"] or _spec_doctypes(spec)

	return {
		"rows": norm["rows"],
		"candidates": len(norm["candidates"]),
		"created": created,
		"updated": updated,
		"duplicates": duplicates,
		"skipped": norm["skipped"],
		"doctypes": doctypes,
		"not_applicable": norm["not_applicable"],
		"data_starved": norm["data_starved"],
	}


def _normalize_detector_result(raw) -> dict:
	if raw is None:
		return _empty_result()
	# DetectorResult dataclass (executor.run_detector): .candidates +
	# .skipped_reason. Duck-typed so a future richer result still works.
	if not isinstance(raw, (dict, list)) and hasattr(raw, "candidates"):
		cands = list(getattr(raw, "candidates", None) or [])
		return {
			"candidates": cands,
			"rows": _rows_from_candidates(cands, getattr(raw, "rows_scanned", None)),
			"skipped": getattr(raw, "skipped_reason", None) or getattr(raw, "skipped", None),
			"doctypes": list(getattr(raw, "doctypes_read", None) or []),
			"not_applicable": bool(getattr(raw, "not_applicable", False)),
			"data_starved": bool(getattr(raw, "data_starved", False)),
		}
	if isinstance(raw, list):
		return {
			"candidates": raw,
			"rows": sum(int(c.get("n_rows") or 0) for c in raw),
			"skipped": None,
			"doctypes": [],
			"not_applicable": False,
			"data_starved": False,
		}
	if isinstance(raw, dict):
		cands = raw.get("candidates") or []
		rows = raw.get("rows_scanned")
		if rows is None:
			rows = sum(int(c.get("n_rows") or 0) for c in cands)
		return {
			"candidates": cands,
			"rows": int(rows or 0),
			"skipped": raw.get("skipped"),
			"doctypes": list(raw.get("doctypes_read") or []),
			"not_applicable": bool(raw.get("not_applicable")),
			"data_starved": bool(raw.get("data_starved")),
		}
	return _empty_result()


def _empty_result() -> dict:
	return {
		"candidates": [],
		"rows": 0,
		"skipped": None,
		"doctypes": [],
		"not_applicable": False,
		"data_starved": False,
	}


# --------------------------------------------------------------------------- #
# persistence (Wave B minimal; Wave C lifecycle.upsert_candidate REPLACES it)
# --------------------------------------------------------------------------- #
def _persist_candidate(candidate: dict, run) -> str:
	"""Dedupe on pattern_key. Returns 'created' | 'updated' | 'duplicate'.

	Existing non-terminal row: refresh evidence + last_seen_run (never overwrite
	an edited skill_draft). Terminal row (Rejected/Archived/Superseded): stamp
	last_seen_run only (suppression memory), report as a duplicate. No row: insert
	a new Proposed pattern with its roles child rows.

	Wave C delegates here to ``jarvis.learning.lifecycle.upsert_candidate`` once
	that module exists; the boundary is the candidate dict contract in the module
	docstring."""
	try:
		from jarvis.learning.lifecycle import upsert_candidate as _lifecycle_upsert
	except Exception:
		_lifecycle_upsert = None
	if _lifecycle_upsert is not None:
		return _lifecycle_upsert(candidate, run)

	pattern_key = candidate.get("pattern_key")
	if not pattern_key:
		# Cannot dedupe safely; drop rather than risk an unbounded churn of
		# unkeyed rows. Reported as a duplicate (suppressed).
		return "duplicate"

	_fenced_write(JLP)
	existing = frappe.db.exists(JLP, {"pattern_key": pattern_key})
	if existing:
		status = frappe.db.get_value(JLP, existing, "status")
		if status in TERMINAL_STATUSES:
			frappe.db.set_value(JLP, existing, {"last_seen_run": run.name}, update_modified=False)
			return "duplicate"
		doc = frappe.get_doc(JLP, existing)
		_apply_evidence(doc, candidate, run, is_new=False)
		doc.save(ignore_permissions=True)
		return "updated"

	doc = frappe.get_doc({"doctype": JLP, "pattern_key": pattern_key, "status": "Proposed"})
	_apply_evidence(doc, candidate, run, is_new=True)
	doc.insert(ignore_permissions=True)
	return "created"


def _apply_evidence(doc, cand: dict, run, *, is_new: bool) -> None:
	doc.detector_id = cand.get("detector_id")
	doc.domain = cand.get("domain")
	doc.company = cand.get("company")
	doc.pattern_statement = (cand.get("pattern_statement") or "").strip() or "(pattern statement pending)"

	# Never overwrite an SM-edited draft (draft_edited freezes it, plan 6.5).
	if is_new or not doc.draft_edited:
		doc.skill_draft = (cand.get("skill_draft") or "").strip() or doc.pattern_statement

	doc.support_n = _as_int(cand.get("support_n"))
	doc.n_rows = _as_int(cand.get("n_rows"))
	doc.exception_n = _as_int(cand.get("exception_n"))
	doc.confidence_pct = _as_float(cand.get("confidence_pct"))
	doc.wilson_low = _as_float(cand.get("wilson_low"))
	doc.gap = _as_float(cand.get("gap"))
	doc.strength_band = cand.get("strength_band")
	doc.temporal_spread = _as_json(cand.get("temporal_spread"))
	doc.evidence = _as_json(cand.get("evidence"))
	doc.exceptions_cluster = cand.get("exceptions_cluster")
	doc.sensitivity = cand.get("sensitivity")
	doc.effective_sensitivity = cand.get("effective_sensitivity") or cand.get("sensitivity")
	doc.not_applicable = 1 if cand.get("not_applicable") else 0
	doc.last_seen_run = run.name

	if is_new:
		doc.first_seen_run = run.name
		for role in (cand.get("roles") or []):
			if role:
				doc.append("roles", {"role": role})


def _promote_surfaced(run_name: str) -> None:
	"""Promote up to (cap - already-surfaced) Proposed rows to surfaced, ordered
	band-then-support_n, with a >=1-per-domain quota (party personalization is
	ranked ahead of config cleanup by the band/support order)."""
	cap = int(_settings_value("pattern_max_proposals_per_run") or 10)
	surfaced_now = frappe.db.count(JLP, {"status": "Proposed", "surfaced": 1})
	slots = cap - surfaced_now
	if slots <= 0:
		return

	rows = frappe.get_all(
		JLP,
		filters={"status": "Proposed", "surfaced": 0},
		fields=["name", "domain", "strength_band", "support_n", "effective_sensitivity"],
	)
	if not rows:
		return
	# Party-specific personalization is ranked ahead of config cleanup, then band,
	# then support_n (plan 6.4 - debt-heavy sites must not bury the marquee wins).
	from jarvis.learning import lifecycle
	rows.sort(key=lifecycle.surfacing_sort_key)

	chosen_names: list = []
	seen = set()
	seen_domains = set()
	# Domain quota pass: the top row of each domain, in global order.
	for r in rows:
		if len(chosen_names) >= slots:
			break
		if r.domain not in seen_domains:
			chosen_names.append(r.name)
			seen.add(r.name)
			seen_domains.add(r.domain)
	# Fill remaining slots by global band/support order.
	for r in rows:
		if len(chosen_names) >= slots:
			break
		if r.name in seen:
			continue
		chosen_names.append(r.name)
		seen.add(r.name)

	now = now_datetime()
	_fenced_write(JLP)
	for name in chosen_names[:slots]:
		frappe.db.set_value(JLP, name, {"surfaced": 1, "surfaced_at": now}, update_modified=False)
	frappe.db.commit()


# --------------------------------------------------------------------------- #
# work units + dormant-company skip
# --------------------------------------------------------------------------- #
def skip_dormant_companies(companies, cutoff_days: int = DORMANT_DAYS) -> list:
	"""Drop companies with no submitted core transaction in the trailing
	``cutoff_days`` (dormant-shell guard; Company has no disabled flag). When no
	core doctype exists we cannot tell, so we keep every company (fail open)."""
	if not companies:
		return []
	existing = [dt for dt in CORE_TXN_DOCTYPES if frappe.db.exists("DocType", dt)]
	if not existing:
		return list(companies)
	cutoff_date = str(get_datetime(add_to_date(now_datetime(), days=-cutoff_days)).date())
	active = []
	for company in companies:
		if _company_has_recent_txn(company, existing, cutoff_date):
			active.append(company)
	return active


def _company_has_recent_txn(company: str, doctypes, cutoff_date: str) -> bool:
	for dt in doctypes:
		try:
			if frappe.db.exists(
				dt, {"company": company, "docstatus": 1, "posting_date": [">=", cutoff_date]}
			):
				return True
		except Exception:
			continue
	return False


def _load_work_units(run, active_companies, registry) -> list:
	"""Resume-aware unit list: last night's unfinished units FIRST (rehydrated by
	id), else a fresh ordered scan from the registry."""
	remaining = _parse_json_list(run.get("remaining_units"))
	if remaining:
		return _rehydrate_units(remaining, registry)
	try:
		return list(registry.iter_work_units(active_companies))
	except Exception:
		frappe.log_error(
			title="jarvis pattern learning: iter_work_units failed",
			message=frappe.get_traceback(),
		)
		return []


def _rehydrate_units(remaining, registry) -> list:
	by_id = {}
	for spec in getattr(registry, "TIER1_DETECTORS", []) or []:
		sid = _spec_id(spec)
		if sid:
			by_id[sid] = spec
	units = []
	for item in remaining:
		if not isinstance(item, dict):
			continue
		spec = by_id.get(item.get("detector_id"))
		if spec is not None:
			units.append((item.get("company"), spec))
	return units


def _serialize_remaining(units) -> list:
	return [{"company": company, "detector_id": _spec_id(spec)} for company, spec in units]


# --------------------------------------------------------------------------- #
# pause / status resolution
# --------------------------------------------------------------------------- #
def _pause_reason(run, started_mono: float, rows_scanned: int, row_budget: int):
	now = now_datetime()
	# Window end (scheduled only; manual bypasses the window, plan 5.2).
	if run.trigger != "manual" and should_pause_for_window(
		run.window_start_used, run.window_end_used, now
	):
		return "Reached the analysis-window boundary; remaining detectors deferred to the next run."
	# Enabled flag applies to both scheduled and manual runs.
	if not _feature_enabled():
		return "Pattern learning was disabled mid-run; remaining detectors deferred."
	if (time.monotonic() - started_mono) >= MAX_RUN_SECONDS:
		return "Approaching the worker time budget; remaining detectors deferred to the next run."
	if row_budget and rows_scanned >= row_budget:
		return (
			f"Nightly row budget ({row_budget}) exhausted; remaining detectors "
			f"deferred to the next run."
		)
	return None


def _resolve_status(paused_note, attempted: int, error_count: int, skipped, errors) -> tuple[str, str]:
	if paused_note:
		return ("Paused", paused_note)
	if attempted and (error_count / attempted) > ERROR_BUDGET_FRACTION:
		return (
			"Failed",
			f"{error_count} of {attempted} detectors errored (over the "
			f"{int(ERROR_BUDGET_FRACTION * 100)}% budget). System Managers notified.",
		)
	if skipped or errors:
		bits = []
		if skipped:
			bits.append(f"{len(skipped)} detector(s) skipped")
		if errors:
			bits.append(f"{len(errors)} detector(s) errored")
		return ("Partial", "Partial run: " + ", ".join(bits) + " (see the run row).")
	return ("Completed", "")


# --------------------------------------------------------------------------- #
# run + detector-state + settings writes
# --------------------------------------------------------------------------- #
def _finalize_run(run_name, *, status, counts, skipped, errors, doctypes, remaining, note) -> None:
	counts = counts or _zero_counts()
	update = {
		"status": status,
		"ended_at": now_datetime(),
		"heartbeat_at": now_datetime(),
		"detectors_completed": counts["completed"],
		"detectors_skipped": frappe.as_json(skipped) if skipped else None,
		"doctypes_read": frappe.as_json(sorted(doctypes)) if doctypes else None,
		"rows_scanned": counts["rows"],
		"candidates_found": counts["candidates"],
		"proposals_created": counts["created"],
		"proposals_updated": counts["updated"],
		"duplicates_suppressed": counts["duplicates"],
		"errors": frappe.as_json(errors) if errors else None,
		"remaining_units": frappe.as_json(remaining) if remaining else None,
		"coverage_note": ((note or "")[:1000] or None),
	}
	_write_run(run_name, update)
	frappe.db.commit()


def _write_run(run_name, update: dict) -> None:
	"""Fenced ``Jarvis Pattern Run`` update (plan §5.4)."""
	_fenced_write(RUN)
	frappe.db.set_value(RUN, run_name, update, update_modified=False)


def _touch_detector_state(detector_id, *, rows_scanned_add: int = 0, **fields) -> None:
	"""Idempotent per-detector state update (name == detector_id). Creates the
	row if the after_migrate seed has not run yet. Best-effort; never crashes a
	run."""
	if not detector_id:
		return
	try:
		_fenced_write(DETECTOR_STATE)
		payload = {k: v for k, v in fields.items() if v is not None or k == "last_error"}
		if frappe.db.exists(DETECTOR_STATE, detector_id):
			if rows_scanned_add:
				current = frappe.db.get_value(DETECTOR_STATE, detector_id, "rows_scanned_total") or 0
				payload["rows_scanned_total"] = int(current) + int(rows_scanned_add)
			if payload:
				frappe.db.set_value(DETECTOR_STATE, detector_id, payload, update_modified=False)
		else:
			doc = frappe.get_doc({
				"doctype": DETECTOR_STATE,
				"detector_id": detector_id,
				"enabled": 1,
				"rows_scanned_total": int(rows_scanned_add or 0),
				**{k: v for k, v in payload.items() if k != "rows_scanned_total"},
			})
			doc.insert(ignore_permissions=True)
	except Exception:
		# State bookkeeping must never fail the analysis run.
		pass


def _notify_system_managers(run_name, error_count: int, attempted: int) -> None:
	try:
		from frappe.utils.user import get_users_with_role

		recipients = get_users_with_role("System Manager")
	except Exception:
		return
	subject = f"Pattern learning run {run_name} failed"
	msg = (
		f"The nightly pattern-learning run {run_name} failed: {error_count} of "
		f"{attempted} detectors errored (over the error budget). See the run row "
		f"and the Error Log."
	)
	for user in recipients:
		if not user or user in ("Administrator", "Guest"):
			continue
		try:
			frappe.get_doc({
				"doctype": "Notification Log",
				"for_user": user,
				"type": "Alert",
				"subject": subject,
				"email_content": msg,
			}).insert(ignore_permissions=True)
		except Exception:
			pass
	try:
		frappe.db.commit()
	except Exception:
		pass


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _settings_value(field: str):
	return frappe.db.get_single_value(SETTINGS, field)


def _zero_counts() -> dict:
	return {"completed": 0, "rows": 0, "candidates": 0, "created": 0, "updated": 0, "duplicates": 0}


def _no_units_note(companies, active_companies) -> str:
	if not companies:
		return "No companies on this site; nothing to analyze."
	if not active_companies:
		return (
			f"All {len(companies)} companies are dormant (no submitted transaction in "
			f"{DORMANT_DAYS} days); nothing to analyze."
		)
	return "No detectors produced work units for the active companies."


def _spec_id(spec):
	if isinstance(spec, dict):
		return spec.get("id")
	return getattr(spec, "id", None)


def _spec_doctypes(spec) -> list:
	"""Base doctype + field-guard doctypes a detector reads (read-audit)."""
	if not isinstance(spec, dict):
		return []
	out = set()
	if spec.get("doctype"):
		out.add(spec["doctype"])
	for guard in spec.get("field_guards") or []:
		if isinstance(guard, (list, tuple)) and guard:
			out.add(guard[0])
	return sorted(out)


def _rows_from_candidates(candidates, reported) -> int:
	if reported is not None:
		try:
			return int(reported)
		except (TypeError, ValueError):
			pass
	return sum(int(c.get("n_rows") or 0) for c in candidates)


def _parse_json_list(value):
	if not value:
		return []
	if isinstance(value, (list, tuple)):
		return list(value)
	try:
		parsed = frappe.parse_json(value)
	except Exception:
		return []
	return parsed if isinstance(parsed, list) else []


def _as_json(value):
	if value is None:
		return None
	if isinstance(value, str):
		return value
	try:
		return frappe.as_json(value)
	except Exception:
		return None


def _as_int(value):
	try:
		return int(value) if value is not None else 0
	except (TypeError, ValueError):
		return 0


def _as_float(value):
	try:
		return float(value) if value is not None else 0.0
	except (TypeError, ValueError):
		return 0.0


def _short_error() -> str:
	err = frappe.get_traceback() or ""
	last = err.strip().splitlines()[-1] if err.strip() else "error"
	return last[:500]
