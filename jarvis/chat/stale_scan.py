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
	"""Scan for stale streaming messages; mark them errored and publish.

	Returns the count of messages marked.
	"""
	cutoff = now_datetime() - timedelta(seconds=STALE_THRESHOLD_SECONDS)
	stale_names = frappe.db.sql(
		"""
		SELECT name FROM `tabJarvis Chat Message`
		WHERE streaming = 1 AND creation < %s
		""",
		(cutoff,),
		as_dict=False,
	)

	for (name,) in stale_names:
		conv_name = frappe.db.get_value(MSG, name, "conversation")
		owner = frappe.db.get_value(CONV, conv_name, "owner")
		frappe.db.set_value(MSG, name, {
			"streaming": 0,
			"error": "Run abandoned (worker did not finish within the timeout).",
		})
		publish_to_user(owner, {
			"kind": "run:error",
			"conversation_id": conv_name,
			"message_id": name,
			"error": "Run abandoned (worker did not finish within the timeout).",
		})
	frappe.db.commit()
	return len(stale_names)
