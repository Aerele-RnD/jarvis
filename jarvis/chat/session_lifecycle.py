"""Session lifecycle Phase 1: dormant-session rotation + orphan sweep.

Every Jarvis Conversation maps to one openclaw session, created lazily on
the first turn and - before this module - never rotated or deleted. Two
kinds of gateway state accumulate forever:

- Dormant conversation sessions: the user stopped chatting weeks ago but
  the session (and its growing working context) sits on the container.
- Orphaned throwaway sessions: every auto-title generation and every
  prefix prewarm creates a single-use session, and deleted conversations
  leave their sessions behind. The dev tenant had 81 session state files
  after one month.

The bench is the durable owner of chat history (Jarvis Chat Message
rows); the openclaw session is a cache of working context, not the
record. Deleting one is safe: the gateway archives the transcript first
(sessions.delete deleteTranscript=true default), canvas/media artifacts
were pulled to ERP Files at turn end, and the next message in a rotated
conversation lazily creates a fresh session through the existing
``_ensure_session_key`` path - same UX, empty working context.

The daily ``rotate_dormant_sessions`` cron:

1. EXPIRE: conversations idle past the configured retention window
   (Jarvis Settings.conversation_retention_days; 0 disables) and not
   starred, with no in-flight rows -> free the openclaw session (delete
   gateway session, clear ``conv.session_key``, drop ``Jarvis Chat
   Session`` lookup rows) and, for still-``Active`` chats, archive them:
   set ``status = Archived`` + ``auto_expired`` + ``expired_at`` and push
   a ``conversation:expired`` realtime event so an open tab drops the row.
   A reversible soft-delete - a separate follow-on purge permanently
   deletes archived chats later. (Reason we don't hard-delete here: a
   Jarvis Conversation is referenced by five doctypes + File blobs, so a
   safe delete needs a full dependency cascade we keep out of the cron.)
   Already user-archived chats that still hold a session are session-freed
   only (no status change, no event) so their working context is reclaimed
   too. Starred chats are fully exempt - kept, session and all.
2. ORPHANS: gateway sessions in the chat namespace that no conversation
   references (title/prewarm throwaways, deleted conversations) and that
   have been inactive past ``ORPHAN_GRACE_HOURS`` -> delete, plus any
   stale lookup rows.

Everything is best-effort on a dedicated connection (never the pool - a
sweep must not contend with live turns), batch-capped so a backlog
drains over days instead of stampeding a gateway, and managed-mode only.
"""
from __future__ import annotations

import logging
import time

import frappe

logger = logging.getLogger(__name__)

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"
CHAT_SESSION = "Jarvis Chat Session"

# Retention: a conversation idle this long is archived (hidden) and its
# openclaw session freed. Configurable per-tenant via
# Jarvis Settings.conversation_retention_days; these are the fallbacks a
# reader applies. DEFAULT is used when the Single field is unset (Single
# defaults are NOT backfilled on migrate, so None must read as 30, not 0 -
# 0 means "keep forever"). MIN is a defensive floor mirroring the settings
# validator, so a value that slipped in below it can't mass-archive.
DEFAULT_RETENTION_DAYS = 30
MIN_RETENTION_DAYS = 7


def _retention_days() -> int:
	"""Effective idle-retention window in days. 0 => disabled (keep forever).

	Read the RAW tabSingles value, not ``get_single_value``: the latter casts an
	unset Int Single field to 0, which is indistinguishable from an explicit 0
	(=disabled). The raw value is None when the field was never set (Single
	defaults are not backfilled on migrate) -> the 30-day default (on by
	default). An explicit '0' stays 0 (never)."""
	rows = frappe.db.sql(
		"SELECT value FROM `tabSingles` "
		"WHERE doctype = 'Jarvis Settings' AND field = 'conversation_retention_days'"
	)
	raw = rows[0][0] if rows else None
	if raw is None or raw == "":
		return DEFAULT_RETENTION_DAYS
	days = frappe.utils.cint(raw)
	if days <= 0:
		return 0
	return max(days, MIN_RETENTION_DAYS)

# An unreferenced gateway session younger than this is skipped: it may be
# an in-flight title/prewarm throwaway, or a conversation whose freshly
# created session_key has not committed yet.
ORPHAN_GRACE_HOURS = 24

# Per-run cap across BOTH parts, so a month of backlog drains over a few
# days instead of hammering the gateway in one cron tick.
BATCH_MAX = 25

# Only sessions in the chat namespace are ever considered for the orphan
# sweep; the agent's main session is additionally refused server-side.
_CHAT_NAMESPACE_MARKER = ":dashboard:"


def rotate_dormant_sessions() -> dict:
	"""Daily cron: archive conversations past the idle-retention window (freeing
	their openclaw session) and reap orphaned throwaway sessions. Returns a
	summary dict (also logged) so a manual ``bench execute`` run shows what
	happened. (Name kept for the scheduler entry in hooks.py.)"""
	from jarvis import selfhost

	if selfhost.is_self_hosted():
		return {"skipped": "self-hosted"}

	settings = frappe.get_single("Jarvis Settings")
	gateway_url = (settings.agent_url or "").replace(
		"http://", "ws://").replace("https://", "wss://")
	if not gateway_url:
		return {"skipped": "no agent_url"}

	from jarvis.chat.openclaw_client import OpenclawSession

	summary = {"archived": 0, "sessions_freed": 0, "orphans_reaped": 0, "skipped": 0, "errors": 0}
	budget = BATCH_MAX
	try:
		sess = OpenclawSession.connect(gateway_url)
	except Exception:
		frappe.log_error(
			title="session_lifecycle: connect failed",
			message=frappe.get_traceback(),
		)
		return {"skipped": "connect failed"}
	try:
		budget = _expire_dormant(sess, budget, summary)
		if budget > 0:
			_reap_orphans(sess, budget, summary)
	finally:
		try:
			sess.close()
		except Exception:
			pass
	logger.info("session_lifecycle: %s", summary)
	return summary


def _expire_dormant(sess, budget: int, summary: dict) -> int:
	"""Part 1: conversations idle past the retention window. Frees the openclaw
	session and archives still-``Active`` chats (marking ``auto_expired`` +
	``expired_at`` and pushing a ``conversation:expired`` event); already
	user-archived chats that still hold a session are session-freed only.
	Starred chats are exempt entirely. Returns leftover budget for the orphan
	sweep. Retention disabled (0) is a no-op that keeps the whole budget."""
	days = _retention_days()
	if days <= 0:
		return budget  # retention disabled - keep chats forever
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-days)
	rows = frappe.db.sql(
		"""
		SELECT c.name, c.owner, c.session_key, c.status
		FROM `tabJarvis Conversation` c
		WHERE c.starred = 0
		  AND c.last_active_at IS NOT NULL AND c.last_active_at < %(cutoff)s
		  AND (c.status = 'Active'
		       OR (c.session_key IS NOT NULL AND c.session_key != ''))
		  AND NOT EXISTS (
			SELECT 1 FROM `tabJarvis Chat Message` m
			WHERE m.conversation = c.name
			  AND (m.streaming = 1 OR m.recovering = 1)
		  )
		ORDER BY c.last_active_at ASC
		LIMIT %(limit)s
		""",
		{"cutoff": cutoff, "limit": budget},
		as_dict=True,
	)
	now = frappe.utils.now_datetime()
	for row in rows:
		if budget <= 0:
			break  # defensive; the SQL LIMIT already bounds rows to budget
		budget -= 1
		# Per-row isolation (turn_recovery's loop pattern): one bad row must
		# never abort the batch, and a failure between the gateway delete and
		# the local commit must not strand the sweep - the idempotent not-found
		# handling in _delete_gateway_session lets the next run finish cleanup.
		try:
			has_session = bool(row.session_key)
			# Free the openclaw session FIRST; only detach the bench side once
			# the gateway side is gone, else a crash would strand a live session
			# under a nulled key. A gateway-delete failure leaves the row intact
			# for next run (do NOT archive it - archiving would hide it from the
			# only sweep that re-selects it, stranding the session forever).
			if has_session and not _delete_gateway_session(sess, row.session_key, summary):
				# NOTE (follow-up): a row whose gateway delete PERMANENTLY fails is
				# the oldest, so ORDER BY last_active_at ASC re-selects it at the
				# front every run, consuming a batch slot; >= BATCH_MAX such corpses
				# would starve healthy archiving. Inherited from the rotate sweep - a
				# last_expire_error_at cooldown column is the planned guard.
				continue
			# Only Active chats transition to Archived; an already user-archived
			# chat is session-freed only (its status/marker stay the user's).
			archived = row.status == "Active"
			updates = {}
			if has_session:
				# NULL, not "": session_key is UNIQUE and two "" rows collide.
				updates["session_key"] = None
			if archived:
				updates.update({"status": "Archived", "auto_expired": 1, "expired_at": now})
			# Conversation update before the lookup-row delete so a per-row
			# failure at the primary (conversation) write skips cleanly with no
			# partial detach (mirrors the original rotate ordering).
			if updates:
				frappe.db.set_value(CONV, row.name, updates)
			if has_session:
				frappe.db.delete(CHAT_SESSION, {"session_key": row.session_key})
				summary["sessions_freed"] += 1
			frappe.db.commit()
			if archived:
				summary["archived"] += 1
				_notify_expired(row.name, row.owner)
		except Exception:
			# Discard any partial write from this row (e.g. the conversation
			# update landed but the lookup-row delete then failed) so it can't
			# ride to the NEXT row's commit; the idempotent gateway delete lets
			# the next run finish cleanly. Rollback before log_error.
			frappe.db.rollback()
			frappe.log_error(
				title="session_lifecycle: expire row failed",
				message=f"conversation={row.name}\n{frappe.get_traceback()}",
			)
			summary["errors"] += 1
	return budget


def _notify_expired(conversation: str, owner: str) -> None:
	"""Best-effort realtime nudge so an open tab drops the archived row instead
	of showing a ghost that 404s on click. Never fatal to the sweep."""
	try:
		from jarvis.chat.events import publish_to_user

		publish_to_user(owner, {"kind": "conversation:expired", "conversation_id": conversation})
	except Exception:
		pass


def _reap_orphans(sess, budget: int, summary: dict) -> None:
	"""Part 2: chat-namespace gateway sessions no conversation references
	(title/prewarm throwaways, deleted conversations), inactive past the
	grace window and with no active run."""
	try:
		entries = sess.list_sessions()
	except Exception:
		frappe.log_error(
			title="session_lifecycle: sessions.list failed",
			message=frappe.get_traceback(),
		)
		summary["errors"] += 1
		return
	known = {
		k for (k,) in frappe.db.sql(
			"SELECT session_key FROM `tabJarvis Conversation` "
			"WHERE session_key IS NOT NULL AND session_key != ''"
		)
	}
	grace_ms = ORPHAN_GRACE_HOURS * 3600 * 1000
	now_ms = int(time.time() * 1000)
	for entry in entries:
		if budget <= 0:
			return
		key = entry.get("key") or ""
		if _CHAT_NAMESPACE_MARKER not in key or key in known:
			continue
		if entry.get("hasActiveRun"):
			summary["skipped"] += 1
			continue
		updated = entry.get("updatedAt")
		if not isinstance(updated, (int, float)) or (now_ms - updated) < grace_ms:
			# No usable activity timestamp -> conservative skip; a fresh
			# throwaway or a just-created conversation session survives.
			summary["skipped"] += 1
			continue
		budget -= 1
		try:
			if _delete_gateway_session(sess, key, summary):
				# Deleted-conversation case: the lookup row may still exist.
				frappe.db.delete(CHAT_SESSION, {"session_key": key})
				frappe.db.commit()
				summary["orphans_reaped"] += 1
		except Exception:
			frappe.log_error(
				title="session_lifecycle: orphan cleanup failed",
				message=f"session_key={key}\n{frappe.get_traceback()}",
			)
			summary["errors"] += 1


def _delete_gateway_session(sess, session_key: str, summary: dict) -> bool:
	"""Best-effort sessions.delete. False (and an Error Log) on failure so
	the caller leaves the bench pointers intact for a retry next run. The
	gateway's refusal to delete the main session lands here as a normal
	failure - logged once per run at most per key, never fatal."""
	try:
		sess.delete_session(session_key)
		return True
	except Exception as e:
		# Idempotent: a session that is ALREADY gone counts as success.
		# This self-heals the crashed-between-delete-and-commit window -
		# the next run's delete "fails" as not-found and the bench
		# pointers finally get cleared instead of sticking forever.
		if "not found" in str(e).lower() or "unknown session" in str(e).lower():
			return True
		frappe.log_error(
			title="session_lifecycle: sessions.delete failed",
			message=f"session_key={session_key}\n{frappe.get_traceback()}",
		)
		summary["errors"] += 1
		return False
