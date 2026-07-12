"""Migrate the business-note greeting from a once-ever fire to a recurring cadence.

The greeting used to be a once-ever event: a blank state meant "never greeted",
"Sent" meant "already fired", and "Snoozed" meant "Maybe later" (backed by a
7-day Redis key). That whole state machine is gone. The greeting is now a
recurring banner driven by ``business_greeting_chat_count`` (shown on every
third genuinely-new chat), so the only meaningful states left are blank
(eligible for the cadence) and "Dismissed" ("Don't ask again", permanent).

This patch retires the two dead states: any user previously left at "Sent" or
"Snoozed" is reset to blank so they re-enter the cadence, matching the new
intent (they will see the card again on their next multiple-of-three chat).
"Dismissed" is never touched - it is the durable, permanent opt-out and must
survive this migration untouched.

The obsolete columns ``business_greeting_sent_at`` /
``business_greeting_conversation`` are dropped from the DocType schema but the
leftover DB columns are harmless and are intentionally NOT dropped here.
"""

import frappe


def execute() -> None:
	frappe.db.sql(
		"UPDATE `tabJarvis User Preference` "
		"SET business_greeting_state = '' "
		"WHERE business_greeting_state IN ('Sent', 'Snoozed')"
	)
