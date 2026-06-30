"""Scheduled job: clean up abandoned streaming Jarvis Chat Messages.

If an RQ worker is killed (OOM, deploy, host restart) mid-stream, its
Jarvis Chat Message row stays at streaming=1. This scan runs on Frappe's
scheduler every 5 minutes.

Managed rows (with a gateway session_key, on a managed bench) are RECOVERABLE:
openclaw persists the result. They are PROMOTED to the recovering state for
turn_recovery to finalize from the snapshot, but only once they are definitely
past any live worker (a live managed turn self-marks recovering at the WS cap
and never reaches here), so a still-streaming turn is never flipped.

Genuinely unrecoverable rows (self-hosted bench, or a row whose conversation /
session_key is gone) are errored after the short threshold.
"""
from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from jarvis.chat.events import publish_to_user

# Error genuinely-abandoned rows (self-hosted / no session) after this.
STALE_THRESHOLD_SECONDS = 120
# Promote a managed row to recovering only once it is past the RQ worker cap,
# so it is definitely orphaned (no live worker survives past the cap, and a
# live turn self-marks recovering at the 600s WS cap well before this).
MANAGED_RECOVER_AFTER_SECONDS = 720
MSG = "Jarvis Chat Message"
CONV = "Jarvis Conversation"
_ABANDONED = "Run abandoned (worker did not finish within the timeout)."


def scan_and_mark_errored() -> int:
	"""Scan stale streaming rows: promote recoverable managed rows to
	recovering, error the rest. Returns the count of rows ERRORED."""
	from jarvis import selfhost

	now = now_datetime()
	self_hosted = selfhost.is_self_hosted()
	managed_cutoff = now - timedelta(seconds=MANAGED_RECOVER_AFTER_SECONDS)
	error_cutoff = now - timedelta(seconds=STALE_THRESHOLD_SECONDS)

	# LEFT JOIN so a streaming row whose conversation was deleted is still
	# handled (session_key resolves NULL -> errored), not silently dropped.
	rows = frappe.db.sql(
		"""
		SELECT m.name, m.conversation, m.creation, c.owner, c.session_key
		FROM `tabJarvis Chat Message` m
		LEFT JOIN `tabJarvis Conversation` c ON c.name = m.conversation
		WHERE m.streaming = 1 AND m.recovering = 0
		""",
		as_dict=True,
	)

	errored = 0
	for r in rows:
		creation = r.get("creation")
		recoverable = (not self_hosted) and bool((r.get("session_key") or "").strip())
		if recoverable:
			if creation and creation < managed_cutoff:
				frappe.db.set_value(MSG, r["name"], {
					"recovering": 1, "recovery_started_at": now,
				})
			continue
		# Self-hosted / orphaned / no session: genuinely unrecoverable.
		if creation and creation < error_cutoff:
			frappe.db.set_value(MSG, r["name"], {"streaming": 0, "error": _ABANDONED})
			if r.get("owner"):
				publish_to_user(r["owner"], {
					"kind": "run:error",
					"conversation_id": r["conversation"],
					"message_id": r["name"],
					"error": _ABANDONED,
				})
			errored += 1
	frappe.db.commit()
	return errored
