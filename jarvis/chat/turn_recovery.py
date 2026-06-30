"""Scheduler-driven recovery for managed chat turns that the bench abandoned.

A long turn can outrun the bench's WS cap, or its RQ worker can be hard-killed
(SIGTERM at the 720s job cap, OOM, crash, deploy). openclaw keeps running the
turn and persists the result regardless. So instead of falsely erroring, the
turn is left `streaming=1, recovering=1` and this job finalizes it from the
gateway's durable transcript.

This is worker/process-INDEPENDENT: everything it needs survives a worker
death (the row, conv.session_key, openclaw's transcript). Completion is the
non-destructive `is_run_active` signal; content comes from `chat.history`.
Mirrors how openclaw's own UI reconciles after a drop (snapshot, not deltas).
"""
from __future__ import annotations

import contextlib
from typing import Iterator

import frappe

from jarvis.chat.events import publish_to_user
from jarvis.chat.openclaw_client import OpenclawSession

MSG = "Jarvis Chat Message"
CONV = "Jarvis Conversation"

# Absolute give-up: a run still "active" past this long is treated as stuck.
_RECOVERY_CEILING_MINUTES = 60
# One extra cycle of grace before declaring a finished-but-empty run a failure
# (covers the brief window where the run just ended and the transcript final
# message has not flushed yet).
_EMPTY_GRACE_MINUTES = 3


@contextlib.contextmanager
def _recovery_connection(gateway_url: str) -> Iterator[OpenclawSession]:
	"""A dedicated short-lived connection for recovery. NEVER the shared pool
	(openclaw_session_pool is single-turn-exclusive and not concurrency-safe)."""
	sess = OpenclawSession.connect(gateway_url)
	try:
		yield sess
	finally:
		sess.close()


def _age_minutes(dt) -> float:
	if not dt:
		return 0.0
	delta = frappe.utils.now_datetime() - frappe.utils.get_datetime(dt)
	return delta.total_seconds() / 60.0


def _latest_assistant_text(messages: list) -> str:
	"""Newest assistant message text from a chat.history snapshot. Handles a
	plain-string content and the {type:"text", text} block list. Sorted by the
	transcript seq so the latest turn wins."""
	def seq(m):
		return ((m or {}).get("__openclaw") or {}).get("seq", 0)

	for m in sorted(messages or [], key=seq, reverse=True):
		if (m.get("role") or "").lower() != "assistant":
			continue
		c = m.get("content")
		if isinstance(c, str) and c.strip():
			return c
		if isinstance(c, list):
			parts = [
				b.get("text", "") for b in c
				if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
			]
			joined = "\n".join(p for p in parts if p.strip())
			if joined.strip():
				return joined
		if isinstance(m.get("text"), str) and m["text"].strip():
			return m["text"]
	return ""


def _finalize(row: dict, text: str) -> None:
	"""Authoritative completion: overwrite content from the snapshot (NOT
	append, so partial streamed content is replaced with no duplication),
	clear the streaming/recovering flags, then publish for any live viewer
	using the existing jarvis:event kinds the SPA already renders."""
	name = row["name"]
	frappe.db.set_value(
		MSG, name, {"content": text, "streaming": 0, "recovering": 0, "error": ""},
	)
	frappe.db.commit()
	conv, owner = row["conversation"], row["owner"]
	publish_to_user(owner, {
		"kind": "assistant:delta", "conversation_id": conv,
		"message_id": name, "text": text, "run_id": "recovered",
	})
	publish_to_user(owner, {
		"kind": "run:end", "conversation_id": conv,
		"message_id": name, "run_id": "recovered",
	})


def _error(row: dict, message: str) -> None:
	name = row["name"]
	frappe.db.set_value(
		MSG, name, {"streaming": 0, "recovering": 0, "error": message},
	)
	frappe.db.commit()
	publish_to_user(row["owner"], {
		"kind": "run:error", "conversation_id": row["conversation"],
		"message_id": name, "run_id": "recovered", "error": message,
	})


def _recover_one(sess: OpenclawSession, row: dict) -> str:
	"""Drive one recovering row to a terminal state. Returns the outcome
	('finalized' | 'active' | 'errored' | 'waiting')."""
	session_key = row["session_key"]
	if sess.is_run_active(session_key):
		if _age_minutes(row["recovery_started_at"]) > _RECOVERY_CEILING_MINUTES:
			_error(row, "Run exceeded the recovery ceiling.")
			return "errored"
		return "active"
	# Not active: openclaw finished (or never started). Reconcile from snapshot.
	hist = sess.get_history(session_key)
	text = _latest_assistant_text(hist.get("messages") or [])
	if text:
		_finalize(row, text)
		return "finalized"
	if _age_minutes(row["recovery_started_at"]) > _EMPTY_GRACE_MINUTES:
		_error(row, "Run finished with no assistant output.")
		return "errored"
	return "waiting"


def recover_pending_turns(limit: int = 20) -> dict:
	"""Scheduler entry: finalize managed turns stuck in the recovering state.
	Self-hosted turns have no gateway transcript to recover from, so they are
	left to stale_scan. Best-effort: a connect or per-row failure logs and the
	next cycle retries."""
	from jarvis import selfhost

	if selfhost.is_self_hosted():
		return {"skipped": "self-hosted"}

	settings = frappe.get_single("Jarvis Settings")
	gateway_url = (settings.agent_url or "").replace(
		"http://", "ws://").replace("https://", "wss://")
	if not gateway_url:
		return {"skipped": "no gateway"}

	rows = frappe.db.sql(
		"""
		SELECT m.name, m.conversation, c.session_key, c.owner,
			   m.recovery_started_at
		FROM `tabJarvis Chat Message` m
		JOIN `tabJarvis Conversation` c ON c.name = m.conversation
		WHERE m.streaming = 1 AND m.recovering = 1
		  AND c.session_key IS NOT NULL AND c.session_key != ''
		ORDER BY m.recovery_started_at ASC
		LIMIT %(limit)s
		""",
		{"limit": limit},
		as_dict=True,
	)
	if not rows:
		return {"checked": 0}

	counts = {"finalized": 0, "active": 0, "errored": 0, "waiting": 0}
	try:
		with _recovery_connection(gateway_url) as sess:
			for row in rows:
				try:
					counts[_recover_one(sess, row)] += 1
				except Exception:
					frappe.log_error(
						title="turn_recovery: row failed",
						message=frappe.get_traceback(),
					)
	except Exception:
		frappe.log_error(
			title="turn_recovery: connect failed",
			message=frappe.get_traceback(),
		)
		return {"checked": len(rows), "connect_failed": True}
	return {"checked": len(rows), **counts}
