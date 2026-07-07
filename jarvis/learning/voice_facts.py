"""Daily voice-note fact extraction (voice & wiki feature).

``process_daily`` (hooks ``daily``) gates cheaply and enqueues ONE deduped
queue-``long`` worker (``_process_all``, job_id ``jarvis_voice_facts``) that:

  1. runs the lifecycle housekeeping chores best-effort (``snooze_expiry`` +
	 ``retention`` - voice runs daily regardless of the pattern-learning
	 window, so the chores are not left to the nightly engine alone);
  2. batches New Business-context ``Jarvis Voice Note`` rows per owner
	 (<=20 notes/batch, <=5 batches/run - the overflow stays New for the
	 next run) and extracts durable facts with ONE
	 ``jarvis.chat.voice.openrouter_complete`` call per batch (strict-JSON
	 prompt; malformed items are skipped, a failed batch leaves its notes
	 New for retry);
  3. routes ``kind == "rule"`` facts as candidate dicts through
	 ``jarvis.learning.lifecycle.upsert_candidate`` under ONE manual
	 ``Jarvis Pattern Run`` (as Administrator, engine flag set), then surfaces
	 the created/updated rows immediately - a voice fact is an explicit user
	 statement, so it never queues behind the mining surfacing cap;
  4. routes ``kind == "context"`` facts to
	 ``jarvis.chat.wiki.apply_extracted_page_updates`` (lazy import,
	 best-effort - the wiki module owns the merge semantics);
  5. sweeps any New Conversation-context notes into the wiki ingest
	 (``enqueue_ingest_note``) as the backstop for a failed save-time enqueue;
  6. marks processed notes ``Processed`` and stamps the
	 ``voice_notes_last_processed_at`` / ``voice_notes_last_process_status``
	 pair on Jarvis Settings (``update_modified=False`` - a background write
	 must never trip the Settings on_update sync).

Nothing here raises out of the scheduler or the worker: failures are logged
and stamped into the status field.
"""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe.utils import cint, now_datetime

NOTE = "Jarvis Voice Note"
RUN = "Jarvis Pattern Run"
JLP = "Jarvis Learned Pattern"
SETTINGS = "Jarvis Settings"

JOB_METHOD = "jarvis.learning.voice_facts._process_all"
JOB_ID = "jarvis_voice_facts"
LOCK_NAME = "jarvis_voice_facts"
QUEUE = "long"
JOB_TIMEOUT_S = 600

MAX_NOTES_PER_BATCH = 20
MAX_BATCHES_PER_RUN = 5
MAX_CONVERSATION_SWEEP = 50
# Keeps a full 20-note batch inside a sane context window.
MAX_TRANSCRIPT_PROMPT_CHARS = 4000
MAX_STATEMENT_LEN = 500

DETECTOR_ID = "voice-context"
DOMAINS = frozenset({"selling", "buying", "stock", "accounts", "projects", "org"})

_EXTRACTION_SYSTEM = (
	"You extract durable business facts from spoken voice-note transcripts. "
	"Output ONLY a JSON array - no prose, no markdown fences. Each item must be "
	'an object with exactly these keys: "statement" (one plain-English sentence '
	'stating the fact), "domain" (one of "selling", "buying", "stock", '
	'"accounts", "projects", "org"), "names_party" (true when the statement '
	'names a specific customer, supplier or person), "kind" ("rule" for a '
	"standing business rule, default or preference the org should follow; "
	'"context" for background knowledge about a customer, supplier, item or '
	"process). Extract only durable facts about how the business operates; "
	"ignore greetings, one-off tasks and anything transient. "
	"Output [] when there is nothing durable."
)


# Voice & Wiki Single defaults, seeded on migrate (Frappe never backfills
# Single defaults). Kept in sync with jarvis_settings.json field defaults.
_SETTINGS_DEFAULTS = {
	"voice_features_enabled": 1,
	"wiki_enabled": 1,
	"wiki_nudge_cooldown_hours": 24,
}


def after_migrate() -> None:
	"""Seed the Voice & Wiki Settings defaults (best-effort, never blocks a
	migrate).

	Check fields need ROW-EXISTENCE probing, not a value test: a loaded doc
	and v16's ``db.get_single_value`` both coerce an unset Check to 0, which
	is indistinguishable from "operator turned it off"."""
	try:
		existing = {
			r[0]
			for r in frappe.db.sql(
				"select field from tabSingles where doctype=%s and field in %s",
				(SETTINGS, tuple(_SETTINGS_DEFAULTS)),
			)
		}
		updates = {f: v for f, v in _SETTINGS_DEFAULTS.items() if f not in existing}
		if updates:
			frappe.db.set_single_value(SETTINGS, updates, update_modified=False)
			frappe.db.commit()
	except Exception:
		frappe.log_error(
			title="jarvis voice bootstrap failed", message=frappe.get_traceback()
		)


# --------------------------------------------------------------------------- #
# scheduler entry + enqueue
# --------------------------------------------------------------------------- #
def process_daily() -> None:
	"""Hooks ``daily`` entry. Bails on the site_config kill switch, the voice
	feature toggle (NULL=ON) and an empty New backlog; otherwise enqueues the
	deduped worker. Never raises out of the scheduler.

	Deliberately NOT gated on self-host: the sweep's wiki ingest and
	JLP-proposal work is all bench-side; only the learned-skill container
	push is (separately) managed-only."""
	try:
		if frappe.conf.get("jarvis_voice_learning_disabled"):
			return
		if not _flag_on("voice_features_enabled"):
			return
		if not frappe.db.exists(NOTE, {"status": "New"}):
			return
		_enqueue()
	except Exception:
		frappe.log_error(
			title="jarvis voice facts: daily scheduling failed",
			message=frappe.get_traceback(),
		)


def enqueue_process_now() -> dict:
	"""The SM 'process now' path (role gate lives in
	``jarvis.chat.voice_notes_api.process_voice_notes_now``). Refuses while a
	sweep job is already queued or running."""
	from frappe.utils.background_jobs import is_job_enqueued

	try:
		already = bool(is_job_enqueued(JOB_ID))
	except Exception:
		already = False
	if already:
		return {"ok": False, "reason": "voice-note processing is already queued or running"}
	_enqueue()
	return {"ok": True}


def _enqueue() -> None:
	frappe.enqueue(
		JOB_METHOD,
		queue=QUEUE,
		timeout=JOB_TIMEOUT_S,
		job_id=JOB_ID,
		deduplicate=True,
	)


# --------------------------------------------------------------------------- #
# worker
# --------------------------------------------------------------------------- #
def _process_all() -> None:
	"""Queue-``long`` worker: single-flight on a redis lock (a stray double
	enqueue coalesces); every exit path stamps the Settings status pair."""
	from jarvis._redis_lock import redis_lock

	with redis_lock(LOCK_NAME, timeout_s=JOB_TIMEOUT_S, blocking_timeout_s=0) as acquired:
		if not acquired:
			return
		original_user = frappe.session.user
		status = "failed: unexpected error; see Error Log"
		try:
			status = _process_locked()
		except Exception:
			frappe.log_error(
				title="jarvis voice facts: sweep crashed",
				message=frappe.get_traceback(),
			)
		finally:
			try:
				frappe.set_user(original_user)
			except Exception:
				pass
			_stamp_settings(status)


def _process_locked() -> str:
	_housekeeping()

	batches, deferred = _load_business_batches()
	facts, processed, failed_batches = _extract_facts(batches)
	rule_facts = [f for f in facts if f["kind"] == "rule"]
	context_facts = [f for f in facts if f["kind"] == "context"]

	rule_stats = _persist_rule_facts(rule_facts)
	context_applied = _apply_context_facts(context_facts)
	_mark_processed(processed)
	swept = _sweep_conversation_notes()

	if not (processed or failed_batches or deferred or swept):
		return "ok: no new voice notes"
	return _summary(len(processed), failed_batches, deferred, rule_stats, context_applied, swept)


def _housekeeping() -> None:
	"""Best-effort lifecycle chores (the nightly engine runs them too; running
	them here keeps snooze/retention honest on benches where the nightly
	mining window never fires)."""
	try:
		from jarvis.learning import lifecycle

		lifecycle.snooze_expiry()
		lifecycle.retention()
	except Exception:
		frappe.log_error(
			title="jarvis voice facts: lifecycle housekeeping failed",
			message=frappe.get_traceback(),
		)


# --------------------------------------------------------------------------- #
# extraction
# --------------------------------------------------------------------------- #
def _load_business_batches() -> tuple[list[dict], int]:
	"""New Business notes grouped per owner into <=MAX_NOTES_PER_BATCH chunks,
	capped at MAX_BATCHES_PER_RUN batches per run. Returns ``(batches,
	deferred_count)``; deferred notes stay New for the next run."""
	rows = frappe.get_all(
		NOTE,
		filters={"status": "New", "context_type": "Business"},
		fields=["name", "owner", "transcript", "creation"],
		order_by="creation asc",
	)
	by_owner: dict[str, list] = {}
	for r in rows:
		by_owner.setdefault(r.owner, []).append(r)

	batches: list[dict] = []
	for owner in sorted(by_owner):
		notes = by_owner[owner]
		for i in range(0, len(notes), MAX_NOTES_PER_BATCH):
			if len(batches) >= MAX_BATCHES_PER_RUN:
				break
			batches.append({"owner": owner, "notes": notes[i : i + MAX_NOTES_PER_BATCH]})
		if len(batches) >= MAX_BATCHES_PER_RUN:
			break
	deferred = len(rows) - sum(len(b["notes"]) for b in batches)
	return batches, deferred


def _extract_facts(batches: list[dict]) -> tuple[list[dict], list[tuple[str, str]], int]:
	"""One LLM call per batch. Returns ``(aggregated facts, [(note, processed
	note text)], failed_batch_count)``. A failed batch leaves its notes New."""
	facts: dict[str, dict] = {}
	processed: list[tuple[str, str]] = []
	failed = 0
	for batch in batches:
		items = _extract_batch(batch)
		if items is None:
			failed += 1
			continue
		kept = 0
		for item in items:
			fact = _clean_item(item)
			if fact is None:
				continue
			kept += 1
			_merge_fact(facts, fact, batch)
		note_text = (
			f"Daily voice sweep: {kept} durable fact(s) extracted from this batch."
			if kept
			else "Daily voice sweep: no durable facts found."
		)
		for row in batch["notes"]:
			processed.append((row.name, note_text))
	return list(facts.values()), processed, failed


def _extract_batch(batch: dict) -> list | None:
	"""ONE strict-JSON extraction call for a batch. None on call/parse failure
	(NOT evidence of 'no facts' - the batch is retried next run)."""
	try:
		from jarvis.chat import voice

		raw = voice.openrouter_complete(
			[
				{"role": "system", "content": _EXTRACTION_SYSTEM},
				{"role": "user", "content": _batch_prompt(batch["notes"])},
			]
		)
	except Exception:
		frappe.log_error(
			title="jarvis voice facts: extraction call failed",
			message=frappe.get_traceback(),
		)
		return None
	items = _parse_json_array(raw)
	if items is None:
		frappe.log_error(
			title="jarvis voice facts: unparseable extraction output",
			message=(raw or "")[:2000] if isinstance(raw, str) else repr(raw)[:2000],
		)
		return None
	return items


def _batch_prompt(notes: list) -> str:
	parts = []
	for i, r in enumerate(notes, 1):
		transcript = (r.transcript or "")[:MAX_TRANSCRIPT_PROMPT_CHARS]
		parts.append(f"Voice note {i} (recorded {str(r.creation)[:10]}):\n{transcript}")
	return "Extract the durable business facts from these voice notes.\n\n" + "\n\n".join(parts)


def _parse_json_array(raw) -> list | None:
	if not raw or not isinstance(raw, str):
		return None
	text = raw.strip()
	if text.startswith("```"):
		text = text.strip("`").strip()
		if "\n" in text:
			first, rest = text.split("\n", 1)
			if first.strip().lower() in ("json", ""):
				text = rest
	try:
		parsed = json.loads(text)
	except Exception:
		lo, hi = text.find("["), text.rfind("]")
		if lo == -1 or hi <= lo:
			return None
		try:
			parsed = json.loads(text[lo : hi + 1])
		except Exception:
			return None
	return parsed if isinstance(parsed, list) else None


def _clean_item(item) -> dict | None:
	"""Tolerant per-item validation: skip anything without a usable statement,
	coerce an unknown domain to 'org' and an unknown kind to 'context' (the
	safer route - context never mints a learned-pattern row)."""
	if not isinstance(item, dict):
		return None
	statement = item.get("statement")
	if not isinstance(statement, str):
		return None
	statement = " ".join(statement.split())
	if not statement:
		return None
	statement = statement[:MAX_STATEMENT_LEN]
	domain = item.get("domain")
	kind = item.get("kind")
	return {
		"statement": statement,
		"domain": domain if domain in DOMAINS else "org",
		"names_party": bool(item.get("names_party")),
		"kind": kind if kind in ("rule", "context") else "context",
	}


def _merge_fact(facts: dict, fact: dict, batch: dict) -> None:
	"""Aggregate identical statements across batches on ``pattern_key``.
	Attribution is batch-granular (the strict item schema carries no note id):
	``notes`` is the union of the batches' note sets, ``users`` the batch
	owners. 'rule' outranks 'context' when the same statement gets both."""
	key = _pattern_key(fact["statement"])
	note_names = [r.name for r in batch["notes"]]
	last_date = max(str(r.creation)[:10] for r in batch["notes"])
	agg = facts.get(key)
	if agg is None:
		facts[key] = {
			"pattern_key": key,
			"statement": fact["statement"],
			"domain": fact["domain"],
			"names_party": fact["names_party"],
			"kind": fact["kind"],
			"notes": set(note_names),
			"users": {batch["owner"]},
			"last_date": last_date,
		}
		return
	agg["notes"].update(note_names)
	agg["users"].add(batch["owner"])
	agg["last_date"] = max(agg["last_date"], last_date)
	agg["names_party"] = agg["names_party"] or fact["names_party"]
	if fact["kind"] == "rule":
		agg["kind"] = "rule"


def _pattern_key(statement: str, company: str | None = None) -> str:
	normalized = " ".join((statement or "").split()).lower()
	raw = f"voice|{normalized}|{company or ''}"
	return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:40]


# --------------------------------------------------------------------------- #
# rule facts -> learned-pattern candidates
# --------------------------------------------------------------------------- #
def _candidate_from_fact(f: dict) -> dict:
	"""Map one aggregated voice fact onto the engine's candidate dict contract
	(see the ``jarvis.learning.engine`` module docstring)."""
	n = len(f["notes"])
	m = len(f["users"])
	eff = "B" if f["names_party"] else "A"
	return {
		"detector_id": DETECTOR_ID,
		"pattern_key": f["pattern_key"],
		"domain": f["domain"],
		"company": None,
		"roles": [],
		"pattern_statement": f["statement"],
		"skill_draft": _skill_draft(f["statement"], n, m, f["last_date"]),
		"support_n": n,
		"n_rows": n,
		"exception_n": 0,
		"confidence_pct": 100.0,
		"wilson_low": 0.0,
		"gap": 0.0,
		"strength_band": "Medium",
		"temporal_spread": None,
		"evidence": {"source": "voice", "notes": sorted(f["notes"]), "users": sorted(f["users"])},
		"exceptions_cluster": None,
		"sensitivity": eff,
		"effective_sensitivity": eff,
		"not_applicable": False,
	}


def _skill_draft(statement: str, n: int, m: int, last_date: str) -> str:
	statement = (statement or "").strip()
	sep = "" if statement.endswith((".", "!", "?")) else "."
	return (
		f"- {statement}{sep} Evidence: stated in {n} voice note(s) "
		f"by {m} user(s), last {last_date}."
	)


def _persist_rule_facts(rule_facts: list[dict]) -> dict:
	"""Upsert rule facts under ONE manual ``Jarvis Pattern Run`` via
	``lifecycle.upsert_candidate``, as Administrator with the engine flag set
	(the JLP transition guard), then surface the touched rows."""
	stats = {"total": len(rule_facts), "created": 0, "updated": 0, "duplicates": 0, "run": None}
	if not rule_facts:
		return stats
	from jarvis.learning import lifecycle

	original_user = frappe.session.user
	prev_flag = frappe.flags.jarvis_pattern_engine
	try:
		frappe.set_user("Administrator")
		frappe.flags.jarvis_pattern_engine = True
		run = frappe.get_doc(
			{
				"doctype": RUN,
				"status": "Running",
				"trigger": "manual",
				"started_at": now_datetime(),
				"scan_mode": "voice",
				"coverage_note": "Voice-note fact extraction (daily sweep).",
			}
		)
		run.flags.ignore_permissions = True
		run.insert()
		stats["run"] = run.name

		for fact in rule_facts:
			cand = _candidate_from_fact(fact)
			try:
				outcome = lifecycle.upsert_candidate(cand, run)
			except Exception:
				frappe.log_error(
					title="jarvis voice facts: candidate upsert failed",
					message=frappe.get_traceback(),
				)
				continue
			if outcome == "created":
				stats["created"] += 1
			elif outcome == "updated":
				stats["updated"] += 1
			else:
				stats["duplicates"] += 1
			if outcome in ("created", "updated"):
				_surface(cand["pattern_key"])

		frappe.db.set_value(
			RUN,
			run.name,
			{
				"status": "Completed",
				"ended_at": now_datetime(),
				"candidates_found": stats["total"],
				"proposals_created": stats["created"],
				"proposals_updated": stats["updated"],
				"duplicates_suppressed": stats["duplicates"],
				"coverage_note": (
					f"Voice-note fact extraction: {stats['total']} rule fact(s) from "
					f"the daily voice sweep ({stats['created']} created, "
					f"{stats['updated']} updated, {stats['duplicates']} suppressed)."
				),
			},
			update_modified=False,
		)
		frappe.db.commit()
	finally:
		frappe.flags.jarvis_pattern_engine = prev_flag
		frappe.set_user(original_user)
	return stats


def _surface(pattern_key: str) -> None:
	"""A voice fact is an explicit user statement: surface it immediately
	instead of leaving it to the nightly mining's capped surfacing pass."""
	row = frappe.db.get_value(JLP, {"pattern_key": pattern_key}, ["name", "surfaced"], as_dict=True)
	if row and not row.surfaced:
		frappe.db.set_value(
			JLP, row.name, {"surfaced": 1, "surfaced_at": now_datetime()}, update_modified=False
		)


# --------------------------------------------------------------------------- #
# context facts + conversation notes -> wiki (best-effort seams)
# --------------------------------------------------------------------------- #
def _apply_context_facts(context_facts: list[dict]) -> int:
	"""Append context facts to per-domain Org wiki pages via
	``jarvis.chat.wiki.apply_extracted_page_updates`` (which owns the merge /
	contradiction semantics). Best-effort: any failure is logged and the run
	continues - the facts' notes are still marked Processed."""
	if not context_facts:
		return 0
	if not _flag_on("wiki_enabled"):
		return 0
	try:
		from jarvis.chat import wiki
	except Exception:
		return 0

	applied = 0
	grouped: dict[tuple[str, str], list[dict]] = {}
	for f in context_facts:
		# One representative author per fact (batches are per-owner, so a
		# single-batch fact attributes exactly).
		user = sorted(f["users"])[0]
		grouped.setdefault((user, f["domain"]), []).append(f)
	for (user, domain), fs in sorted(grouped.items()):
		updates = [
			{
				"slug": f"org-notes--{domain}",
				"title": f"Org notes ({domain})",
				"page_type": "Org",
				"append_md": "\n".join(f"- {x['statement']}" for x in fs),
			}
		]
		try:
			wiki.apply_extracted_page_updates(updates, "voice", user)
			applied += len(fs)
		except Exception:
			frappe.log_error(
				title="jarvis voice facts: wiki context routing failed",
				message=frappe.get_traceback(),
			)
	return applied


def _sweep_conversation_notes() -> int:
	"""Backstop for Conversation-context notes whose save-time ingest enqueue
	failed (or predates the wiki module): hand them to the wiki's own deduped
	ingest worker, which marks them Processed."""
	if not _flag_on("wiki_enabled"):
		return 0
	names = frappe.get_all(
		NOTE,
		filters={"status": "New", "context_type": "Conversation"},
		pluck="name",
		order_by="creation asc",
		limit_page_length=MAX_CONVERSATION_SWEEP,
	)
	if not names:
		return 0
	try:
		from jarvis.chat import wiki
	except Exception:
		return 0
	swept = 0
	for name in names:
		try:
			wiki.enqueue_ingest_note(name)
			swept += 1
		except Exception:
			frappe.log_error(
				title="jarvis voice facts: wiki ingest enqueue failed",
				message=frappe.get_traceback(),
			)
			break
	return swept


# --------------------------------------------------------------------------- #
# bookkeeping
# --------------------------------------------------------------------------- #
def _mark_processed(processed: list[tuple[str, str]]) -> None:
	now = now_datetime()
	for name, note_text in processed:
		try:
			frappe.db.set_value(
				NOTE,
				name,
				{"status": "Processed", "processed_at": now, "processed_note": note_text[:500]},
				update_modified=False,
			)
		except Exception:
			frappe.log_error(
				title=f"jarvis voice facts: could not mark {name} processed",
				message=frappe.get_traceback(),
			)
	if processed:
		frappe.db.commit()


def _summary(
	processed_n: int,
	failed_batches: int,
	deferred: int,
	rule_stats: dict,
	context_applied: int,
	swept: int,
) -> str:
	bits = [f"{processed_n} note(s) processed"]
	if rule_stats["total"]:
		bits.append(
			f"{rule_stats['total']} rule fact(s) ({rule_stats['created']} created, "
			f"{rule_stats['updated']} updated, {rule_stats['duplicates']} suppressed)"
		)
	if context_applied:
		bits.append(f"{context_applied} context fact(s) routed to the wiki")
	if swept:
		bits.append(f"{swept} conversation note(s) queued for wiki ingest")
	if deferred:
		bits.append(f"{deferred} note(s) deferred to the next run (batch cap)")
	if failed_batches:
		bits.append(f"{failed_batches} batch(es) failed extraction (left New; see Error Log)")
	prefix = "partial" if failed_batches else "ok"
	return f"{prefix}: " + ", ".join(bits)


def _stamp_settings(status: str) -> None:
	try:
		frappe.db.set_single_value(
			SETTINGS, "voice_notes_last_processed_at", now_datetime(), update_modified=False
		)
		frappe.db.set_single_value(
			SETTINGS, "voice_notes_last_process_status", (status or "")[:1000], update_modified=False
		)
		frappe.db.commit()
	except Exception:
		frappe.log_error(
			title="jarvis voice facts: status stamp failed",
			message=frappe.get_traceback(),
		)


def _flag_on(field: str) -> bool:
	"""NULL=ON idiom (the ``vision_attachments_enabled`` pattern): Single
	defaults are not backfilled on migrate, so an absent row reads enabled.
	Probes tabSingles row-existence directly: get_single_value coerces an
	unset Check to 0, which is indistinguishable from operator-off."""
	try:
		row = frappe.db.sql(
			"select value from tabSingles where doctype=%s and field=%s",
			(SETTINGS, field),
		)
	except Exception:
		return True
	if not row:
		return True
	return bool(cint(row[0][0]))
