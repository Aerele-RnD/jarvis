"""Subscription / credits / rate-limit validation seam.

Called by jarvis.chat.api.send_message before enqueuing the agent worker.
It rejects empty users and Guest, and (design section 5) enforces the
per-user monthly token cap set via ``Jarvis User Settings``. Phase 3's
jarvis_admin app may layer real subscription gating on top by overriding
this module's contract.

Returns (True, None) on success or (False, reason: str) on rejection. The
reason is a machine code the SPA maps to a human toast; the enforcement
rejection uses reason ``"usage_limit"`` and the billing one
``"subscription_suspended"``.
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
	if _subscription_suspended():
		return False, "subscription_suspended"
	return True, None


def _subscription_suspended() -> bool:
	"""True iff admin reports the subscription no longer entitles chat. Reuses
	_admin_chat_gate's cache; fails OPEN (a control-plane hiccup must never block
	a paying customer, and self-host has no admin)."""
	try:
		from jarvis.account import _admin_chat_gate

		return _admin_chat_gate().get("reason") == "subscription_suspended"
	except Exception:
		frappe.log_error(
			title="jarvis policy: entitlement check failed (allowing send)",
			message=frappe.get_traceback(),
		)
		return False


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
		# Stale month ⇒ this month's usage hasn't started ⇒ 0 used. One shared
		# bucket-key helper (jarvis.chat.usage) so writer and gate can't drift.
		from jarvis.chat.usage import current_month_key

		used = int(row.month_tokens or 0) if row.usage_month == current_month_key() else 0
		return used >= limit
	except Exception:
		frappe.log_error(
			title="jarvis usage: limit check failed (allowing send)",
			message=frappe.get_traceback(),
		)
		return False
