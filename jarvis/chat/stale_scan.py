"""Scheduled job: mark abandoned streaming Jarvis Chat Messages as errored.

If an RQ worker is killed (OOM, deploy, host restart) mid-stream, its
Jarvis Chat Message row stays at streaming=1 forever. This scan runs on
Frappe's scheduler every 5 minutes and times out any streaming message
older than the threshold, publishing a run:error so the browser can react.
"""

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from jarvis.chat.events import publish_to_user

STALE_THRESHOLD_SECONDS = 120
MSG = "Jarvis Chat Message"
CONV = "Jarvis Conversation"


def scan_and_mark_errored() -> int:
	"""Scan for stale streaming messages.

	Managed rows (with a gateway session_key) are RECOVERABLE - openclaw
	persists the result - so instead of erroring we promote them to the
	recovering state for turn_recovery to finalize from the snapshot. This
	also catches workers hard-killed BEFORE they could mark recovering. Only
	genuinely unrecoverable rows (self-hosted, no session_key) are errored
	here; rows already recovering are skipped (turn_recovery owns them).

	Returns the count of rows ERRORED (not promoted).
	"""
	cutoff = now_datetime() - timedelta(seconds=STALE_THRESHOLD_SECONDS)
	rows = frappe.db.sql(
		"""
		SELECT m.name, m.conversation, c.owner, c.session_key
		FROM `tabJarvis Chat Message` m
		JOIN `tabJarvis Conversation` c ON c.name = m.conversation
		WHERE m.streaming = 1 AND m.recovering = 0 AND m.creation < %s
		""",
		(cutoff,),
		as_dict=True,
	)

	errored = 0
	for r in rows:
		if (r.get("session_key") or "").strip():
			# Recoverable: hand off to turn_recovery rather than error.
			frappe.db.set_value(MSG, r["name"], {
				"recovering": 1,
				"recovery_started_at": now_datetime(),
			})
			continue
		frappe.db.set_value(MSG, r["name"], {
			"streaming": 0,
			"error": "Run abandoned (worker did not finish within the timeout).",
		})
		publish_to_user(r["owner"], {
			"kind": "run:error",
			"conversation_id": r["conversation"],
			"message_id": r["name"],
			"error": "Run abandoned (worker did not finish within the timeout).",
		})
		errored += 1
	frappe.db.commit()
	return errored
