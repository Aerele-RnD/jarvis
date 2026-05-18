"""Subscription / credits / rate-limit validation seam.

Called by jarvis.chat.api.send_message before enqueuing the agent worker.
Today this is a stub that only rejects empty users and Guest. Phase 3's
jarvis_admin app fills in real subscription gating, credit-balance checks,
and rate limiting by overriding this module's contract.

Returns (True, None) on success or (False, reason: str) on rejection. The
reason is shown to the customer in a UI toast.
"""

from __future__ import annotations


def validate_can_send(user: str) -> tuple[bool, str | None]:
	if not user:
		return False, "no authenticated user"
	if user == "Guest":
		return False, "Guest users cannot use Jarvis chat"
	return True, None
