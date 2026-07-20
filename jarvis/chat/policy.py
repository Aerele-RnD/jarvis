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


def validate_can_send(user: str, model: str | None = None) -> tuple[bool, str | None]:
	if not user:
		return False, "no authenticated user"
	if user == "Guest":
		return False, "Guest users cannot use Jarvis chat"
	# Aggregate monthly cap is the OUTER gate — checked first (fleet spec §7).
	if _over_monthly_limit(user):
		return False, "usage_limit"
	# Per-model cap: only when a concrete model is known. ``model`` is resolved
	# in chat.api (which knows the conversation) and passed in as a plain string,
	# so policy never imports turn_handler (no import cycle). Pool "Auto" resolves
	# to "" -> per-model gate skipped (accepted enforcement gap, spec §2).
	if model and _over_model_limit(user, model):
		return False, "usage_limit"
	return True, None


def _over_model_limit(user: str, model: str) -> bool:
	"""True iff ``user`` has a positive per-model cap for ``model`` this month and
	this month's per-model usage has reached it. Rollover-aware: the lookup is
	scoped to the current month_key, so a stale row reads as no cap. Fails open on
	any error — an accounting lookup bug must never block a legitimate send (G2).

	SUMs across all matching rows rather than reading one via
	``frappe.db.get_value`` — a write-side race in
	``jarvis.chat.usage._upsert_model_usage`` (closed by an atomic upsert +
	unique index, but pre-existing duplicates or any future anomaly must
	still be tolerated here) could otherwise leave two child rows for the
	same (user, model, month); reading one arbitrary row could silently
	under-count usage and let a per-model cap be exceeded."""
	try:
		if not model:
			return False
		from jarvis.chat.usage import (
			MODEL_USAGE,
			MODEL_USAGE_FIELD,
			current_month_key,
		)

		row = frappe.db.sql(
			"""
			SELECT MAX(monthly_token_limit) AS limit_,
				   SUM(month_input_tokens) AS in_,
				   SUM(month_output_tokens) AS out_
			FROM `tabJarvis User Model Usage`
			WHERE parent = %(user)s AND parenttype = %(ptype)s
			  AND parentfield = %(pfield)s AND model = %(model)s
			  AND month_key = %(month)s
			""",
			{
				"user": user,
				"ptype": "Jarvis User Settings",
				"pfield": MODEL_USAGE_FIELD,
				"model": model,
				"month": current_month_key(),
			},
			as_dict=True,
		)
		# MAX()/SUM() over zero matching rows returns one row of NULLs, not an
		# empty result set — a NULL limit means "no row" (no cap).
		if not row or row[0].limit_ is None:
			return False
		limit = int(row[0].limit_ or 0)
		if limit <= 0:
			return False
		used = int(row[0].in_ or 0) + int(row[0].out_ or 0)
		return used >= limit
	except Exception:
		# The logging call itself touches the DB (Error Log controller
		# resolution) - if the triggering failure is DB-wide, log_error can
		# raise too. Never let a logging failure defeat fail-open (G2).
		try:
			frappe.log_error(
				title="jarvis usage: per-model limit check failed (allowing send)",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass
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
		# See _over_model_limit: don't let a logging failure defeat fail-open.
		try:
			frappe.log_error(
				title="jarvis usage: limit check failed (allowing send)",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass
		return False
