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

1. DORMANT: conversations idle past ``DORMANT_DAYS`` with a session_key
   and no in-flight rows -> delete the gateway session, clear
   ``conv.session_key``, drop the ``Jarvis Chat Session`` lookup rows.
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

# A conversation idle this long gets its session rotated. Matches the
# fleet's archive_retention_days default so there is one retention story.
DORMANT_DAYS = 30

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
	"""Daily cron: rotate dormant conversation sessions and reap orphaned
	throwaway sessions. Returns a summary dict (also logged) so a manual
	``bench execute`` run shows what happened."""
	from jarvis import selfhost

	if selfhost.is_self_hosted():
		return {"skipped": "self-hosted"}

	settings = frappe.get_single("Jarvis Settings")
	gateway_url = (settings.agent_url or "").replace(
		"http://", "ws://").replace("https://", "wss://")
	if not gateway_url:
		return {"skipped": "no agent_url"}

	from jarvis.chat.openclaw_client import OpenclawSession

	summary = {"dormant_rotated": 0, "orphans_reaped": 0, "skipped": 0, "errors": 0}
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
		budget = _rotate_dormant(sess, budget, summary)
		if budget > 0:
			_reap_orphans(sess, budget, summary)
	finally:
		try:
			sess.close()
		except Exception:
			pass
	logger.info("session_lifecycle: %s", summary)
	return summary


def _rotate_dormant(sess, budget: int, summary: dict) -> int:
	"""Part 1: conversations idle past DORMANT_DAYS. Returns leftover
	budget for the orphan sweep."""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-DORMANT_DAYS)
	rows = frappe.db.sql(
		"""
		SELECT c.name, c.session_key
		FROM `tabJarvis Conversation` c
		WHERE c.session_key IS NOT NULL AND c.session_key != ''
		  AND c.last_active_at IS NOT NULL AND c.last_active_at < %(cutoff)s
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
	for row in rows:
		if budget <= 0:
			break
		budget -= 1
		if _delete_gateway_session(sess, row.session_key, summary):
			# Only detach the bench side once the gateway side is gone,
			# so a failed delete retries on the next run. NULL, not "":
			# session_key is UNIQUE and two "" rows would collide.
			frappe.db.set_value(CONV, row.name, "session_key", None)
			frappe.db.delete(CHAT_SESSION, {"session_key": row.session_key})
			frappe.db.commit()
			summary["dormant_rotated"] += 1
	return budget


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
		if _delete_gateway_session(sess, key, summary):
			# Deleted-conversation case: the lookup row may still exist.
			frappe.db.delete(CHAT_SESSION, {"session_key": key})
			frappe.db.commit()
			summary["orphans_reaped"] += 1


def _delete_gateway_session(sess, session_key: str, summary: dict) -> bool:
	"""Best-effort sessions.delete. False (and an Error Log) on failure so
	the caller leaves the bench pointers intact for a retry next run. The
	gateway's refusal to delete the main session lands here as a normal
	failure - logged once per run at most per key, never fatal."""
	try:
		sess.delete_session(session_key)
		return True
	except Exception:
		frappe.log_error(
			title="session_lifecycle: sessions.delete failed",
			message=f"session_key={session_key}\n{frappe.get_traceback()}",
		)
		summary["errors"] += 1
		return False
