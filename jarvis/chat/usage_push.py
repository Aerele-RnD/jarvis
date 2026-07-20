"""Daily month-to-date usage rollup push to admin (Architecture A, fleet usage
spec §3/§5).

The bench holds month-to-date running counters (per user + per model), not a
per-day ledger, so the push is an idempotent month-to-date SNAPSHOT: admin
upserts on (tenant, user, month) and owns history. Best-effort - a push failure
never affects chat. Self-hosted benches (no managed container) and un-onboarded
benches (no admin credentials) simply don't push; admin then shows "no usage".
"""

from __future__ import annotations

import frappe

from jarvis.chat import usage
from jarvis.exceptions import AdminAuthError

USER_SETTINGS = usage.USER_SETTINGS
MODEL_USAGE = usage.MODEL_USAGE
MODEL_USAGE_FIELD = usage.MODEL_USAGE_FIELD

# Hard cap on users per push (spec §7). Bounds payload size; extra users are
# dropped (highest-usage first kept) and the truncation is logged.
_MAX_USERS = 500


def _admin_configured() -> bool:
	"""jarvis_admin_url is set (site config outranks the Settings field). Mirrors
	installed_apps_sync._admin_configured. Credential *presence* is not checked
	here - admin_client raises AdminAuthError when unonboarded, which the caller
	treats as a quiet skip."""
	try:
		if (frappe.conf.get("jarvis_admin_url") or "").strip():
			return True
		settings = frappe.get_cached_doc("Jarvis Settings")
		return bool((settings.get("jarvis_admin_url") or "").strip())
	except Exception:
		return False


def _build_rollup(cap: int = _MAX_USERS) -> tuple[dict, bool]:
	"""Month-to-date snapshot: every settings row on the CURRENT month, highest
	usage first, capped. Returns (rollup, truncated). per_model is a dict keyed by
	model -> {in, out} (the pinned ingest contract)."""
	month = usage.current_month_key()
	rows = frappe.get_all(
		USER_SETTINGS,
		filters={"usage_month": month},
		fields=["name as user", "month_input_tokens", "month_output_tokens", "month_tokens"],
		order_by="month_tokens desc",
	)
	truncated = len(rows) > cap
	rows = rows[:cap]
	users = []
	for s in rows:
		per_model: dict[str, dict] = {}
		for r in frappe.get_all(
			MODEL_USAGE,
			filters={
				"parent": s.user, "parenttype": USER_SETTINGS,
				"parentfield": MODEL_USAGE_FIELD, "month_key": month,
			},
			fields=["model", "month_input_tokens", "month_output_tokens"],
		):
			if not r.model:
				continue
			per_model[r.model] = {
				"in": int(r.month_input_tokens or 0),
				"out": int(r.month_output_tokens or 0),
			}
		users.append({
			"email": s.user,
			"tokens_in": int(s.month_input_tokens or 0),
			"tokens_out": int(s.month_output_tokens or 0),
			"total_tokens": int(s.month_tokens or 0),
			"per_model": per_model,
		})
	return {"month_key": month, "users": users}, truncated


def push_usage_rollup() -> None:
	"""Daily scheduler entry. Self-gating + best-effort; NEVER raises."""
	try:
		from jarvis import selfhost

		if selfhost.is_self_hosted():
			return
		if not _admin_configured():
			return
		rollup, truncated = _build_rollup()
		if truncated:
			frappe.logger("jarvis.usage_push").warning(
				"usage rollup truncated at %s users", _MAX_USERS)
		if not rollup["users"]:
			return
		from jarvis import admin_client

		admin_client.push_usage_rollup(rollup)
	except AdminAuthError:
		# Not onboarded / no admin credentials (self-hosted-ish). Nothing to push;
		# not an error condition, so don't log_error.
		return
	except Exception:
		frappe.log_error(
			title="jarvis usage: rollup push failed",
			message=frappe.get_traceback(),
		)
