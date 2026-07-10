"""Subscription / credits / rate-limit validation seam.

Called by jarvis.chat.api.send_message before enqueuing the agent worker.
It rejects empty users and Guest, and (design section 5) enforces the
per-user monthly token cap set via ``Jarvis User Settings``. Phase 3's
jarvis_admin app may layer real subscription gating on top by overriding
this module's contract.

Returns (True, None) on success or (False, reason: str) on rejection. The
reason is a machine code the SPA maps to a human toast; the enforcement
rejection uses reason ``"usage_limit"``.
"""

from __future__ import annotations

import frappe


def validate_can_send(user: str) -> tuple[bool, str | None]:
	if not user:
		return False, "no authenticated user"
	if user == "Guest":
		return False, "Guest users cannot use Jarvis chat"
	if _over_monthly_limit(user):
		return False, "usage_limit"
	return True, None


def _over_monthly_limit(user: str) -> bool:
	"""True iff ``user`` has a positive monthly token cap and this month's
	recorded usage has reached it. Dependency-light: one ``db.get_value`` on the
	settings row, no lazy create (a missing row = no limit). Rollover-aware: a
	stale ``usage_month`` means this month's usage is effectively 0. Fails open
	on any error — an accounting lookup bug must never block a legitimate send."""
	try:
		row = frappe.db.get_value(
			"Jarvis User Settings",
			{"user": user},
			["monthly_token_limit", "usage_month", "month_tokens"],
			as_dict=True,
		)
		if not row:
			return False
		limit = int(row.monthly_token_limit or 0)
		if limit <= 0:
			return False
		# Stale month ⇒ this month's usage hasn't started ⇒ 0 used.
		current_month = frappe.utils.now_datetime().strftime("%Y-%m")
		used = int(row.month_tokens or 0) if row.usage_month == current_month else 0
		return used >= limit
	except Exception:
		frappe.log_error(
			title="jarvis usage: limit check failed (allowing send)",
			message=frappe.get_traceback(),
		)
		return False
