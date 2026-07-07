"""SPA-facing endpoints for Jarvis Voice Note (Business tab + chat nudge).

Owner-scoped CRUD over ``Jarvis Voice Note`` rows plus the Business-tab status
card and the SM-only "process now" trigger for the daily voice-facts sweep
(``jarvis.learning.voice_facts``). Speech-to-text itself lives in
``jarvis.chat.voice.transcribe_audio``; these endpoints only persist and list
the resulting transcripts.

All endpoints reject Guest and require a System User (the feature is Desk-SPA
only, mirroring the ``jarvis.chat.voice`` gate). ``Jarvis Wiki Page`` /
``jarvis.chat.wiki`` integration is best-effort lazy-imported: a Conversation
note whose immediate ingest enqueue fails is picked up by the daily sweep.
"""

from __future__ import annotations

import frappe
from frappe import _

NOTE = "Jarvis Voice Note"
CONV = "Jarvis Conversation"
_SETTINGS = "Jarvis Settings"

_EXCERPT_LEN = 300
_CONTEXT_TYPES = ("Business", "Conversation")
_SOURCES = ("Business Tab", "Chat Nudge")
_STATUSES = ("New", "Processed", "Archived")
_MAX_ENTITIES = 20
_SEARCH_MAX = 140


def _require_system_user() -> None:
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	if user == "Administrator":
		return
	if frappe.db.get_value("User", user, "user_type") != "System User":
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _single(field: str):
	"""``get_single_value`` throws on a field missing from meta (a bench mid-
	deploy before the Settings fields land); treat that as unset."""
	try:
		return frappe.db.get_single_value(_SETTINGS, field)
	except Exception:
		return None


def _lk(s: str) -> str:
	"""Escape LIKE wildcards in user search input (self-contained copy; the
	learned/approvals APIs keep their own)."""
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


def _clean_entities(entities) -> str | None:
	"""Normalize the viewing-context entities to ``[{doctype, name}]`` JSON.
	Unknown shapes are dropped rather than rejected (the note text is the
	payload; entities are best-effort context)."""
	if isinstance(entities, str):
		if not entities.strip():
			return None
		try:
			entities = frappe.parse_json(entities)
		except Exception:
			return None
	if not isinstance(entities, list):
		return None
	cleaned = []
	for item in entities[:_MAX_ENTITIES]:
		if not isinstance(item, dict):
			continue
		doctype = str(item.get("doctype") or "").strip()
		name = str(item.get("name") or "").strip()
		if doctype and name:
			cleaned.append({"doctype": doctype, "name": name})
	return frappe.as_json(cleaned) if cleaned else None


@frappe.whitelist()
def save_voice_note(
	transcript: str,
	context_type: str = "Business",
	conversation: str | None = None,
	entities: list | str | None = None,
	duration_s: int = 0,
	source: str = "Business Tab",
) -> dict:
	"""Persist one transcribed voice note owned by the caller.

	Conversation-context notes must reference a conversation the caller owns
	and are handed to the wiki ingest immediately (best-effort; the daily
	sweep is the backstop). Returns ``{"name": <note>}``."""
	_require_system_user()

	transcript = (transcript or "").strip()
	if not transcript:
		frappe.throw(_("Transcript is required."))
	if context_type not in _CONTEXT_TYPES:
		frappe.throw(_("Invalid context type."))
	if source not in _SOURCES:
		frappe.throw(_("Invalid source."))
	try:
		duration_s = max(0, int(duration_s or 0))
	except (TypeError, ValueError):
		duration_s = 0

	conversation = (conversation or "").strip() or None
	if context_type == "Conversation":
		if not conversation:
			frappe.throw(_("A Conversation-context voice note must link a conversation."))
	if conversation:
		owner = frappe.db.get_value(CONV, conversation, "owner")
		if not owner:
			frappe.throw(_("Unknown conversation."))
		if owner != frappe.session.user:
			frappe.throw(_("Not your conversation."), frappe.PermissionError)

	doc = frappe.get_doc(
		{
			"doctype": NOTE,
			"transcript": transcript,
			"duration_s": duration_s,
			"context_type": context_type,
			"conversation": conversation,
			"entities": _clean_entities(entities),
			"source": source,
			"status": "New",
		}
	)
	doc.insert(ignore_permissions=True)

	if context_type == "Conversation":
		# Best-effort immediate ingest; on any failure the note stays New and
		# the daily voice_facts sweep picks it up.
		try:
			from jarvis.chat import wiki

			wiki.enqueue_ingest_note(doc.name)
		except Exception:
			pass

	return {"name": doc.name}


@frappe.whitelist()
def list_my_voice_notes_page(
	start: int = 0,
	page_length: int = 20,
	status: str | None = None,
	search: str | None = None,
) -> dict:
	"""The caller's own voice notes, newest first. ``search`` filters on the
	transcript (wildcard-escaped LIKE, silently truncated to 140 chars - the
	notes-pane search box, not a query language). Envelope:
	``{rows, total, has_more, start, page_length}``; each row carries the full
	``transcript`` plus a 300-char ``excerpt`` for list rendering."""
	_require_system_user()
	start, pl = _clamp_page(start, page_length)

	filters: dict = {"owner": frappe.session.user}
	if status:
		if status not in _STATUSES:
			frappe.throw(_("Invalid status filter."))
		filters["status"] = status
	search = (search or "").strip()[:_SEARCH_MAX]
	if search:
		filters["transcript"] = ["like", f"%{_lk(search)}%"]

	total = frappe.db.count(NOTE, filters)
	rows = frappe.get_all(
		NOTE,
		filters=filters,
		fields=["name", "transcript", "context_type", "status", "creation", "conversation"],
		order_by="creation desc, name asc",
		limit_start=start,
		limit_page_length=pl,
	)
	for r in rows:
		r["excerpt"] = (r.get("transcript") or "")[:_EXCERPT_LEN]

	return {
		"rows": rows,
		"total": total,
		"has_more": start + len(rows) < total,
		"start": start,
		"page_length": pl,
	}


@frappe.whitelist()
def update_voice_note(name: str, transcript: str) -> dict:
	"""Edit the transcript of one of the caller's own notes while it is still
	``New`` (owner-only): the edited text re-feeds the daily sweep untouched.
	Processed/Archived notes are frozen history and cannot be edited. The save
	goes through the doctype controller, so the same required/length validation
	as ``save_voice_note`` applies."""
	_require_system_user()
	transcript = (transcript or "").strip()
	if not transcript:
		frappe.throw(_("Transcript is required."))

	# Row lock (the learned_api.flag_learned_default idiom): the sweep marks
	# notes Processed via db.set_value(update_modified=False), which defeats
	# Document.save's modified-timestamp conflict check — so a save from a
	# stale snapshot would silently revert a just-Processed note to New and
	# wipe its processed bookkeeping. FOR UPDATE serializes the sweep's UPDATE
	# behind this transaction; the status check below is then authoritative.
	row = frappe.db.get_value(
		NOTE, name, ["owner", "status"], as_dict=True, for_update=True
	)
	if not row:
		frappe.throw(_("Voice note not found."))
	if row.owner != frappe.session.user:
		frappe.throw(_("Not your voice note."), frappe.PermissionError)
	if row.status != "New":
		frappe.throw(_("Only New voice notes can be edited."))

	doc = frappe.get_doc(NOTE, name)
	doc.transcript = transcript
	doc.save(ignore_permissions=True)
	return {"ok": True}


@frappe.whitelist()
def delete_voice_note(name: str) -> dict:
	"""Delete one of the caller's own voice notes (owner-only)."""
	_require_system_user()
	owner = frappe.db.get_value(NOTE, name, "owner")
	if not owner:
		frappe.throw(_("Voice note not found."))
	if owner != frappe.session.user:
		frappe.throw(_("Not your voice note."), frappe.PermissionError)
	frappe.delete_doc(NOTE, name, ignore_permissions=True)
	return {"ok": True}


@frappe.whitelist()
def get_business_status() -> dict:
	"""Business-tab status card: STT availability, the caller's note count and
	(for System Managers) the org-wide New backlog + last sweep outcome."""
	_require_system_user()
	me = frappe.session.user
	is_sm = "System Manager" in frappe.get_roles(me)

	stt_enabled = False
	try:
		from jarvis.chat import voice

		stt_enabled = bool(voice.stt_config())
	except Exception:
		stt_enabled = False

	last_processed_at = _single("voice_notes_last_processed_at")
	last_process_status = _single("voice_notes_last_process_status")

	return {
		"stt_enabled": stt_enabled,
		"my_notes": frappe.db.count(NOTE, {"owner": me}),
		"org_new_notes": frappe.db.count(NOTE, {"status": "New"}) if is_sm else None,
		"last_processed_at": str(last_processed_at) if last_processed_at else None,
		"last_process_status": last_process_status or None,
		"can_process": is_sm,
	}


@frappe.whitelist()
def process_voice_notes_now() -> dict:
	"""SM-only: run the daily voice-facts sweep now (same deduped background
	job). Returns ``{"ok": True}`` or ``{"ok": False, "reason": ...}`` when a
	sweep is already queued or running."""
	frappe.only_for("System Manager")
	from jarvis.learning import voice_facts

	return voice_facts.enqueue_process_now()
