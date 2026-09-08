"""Mirror the operator's resolved upgrade-maintenance hold locally and expose it to chat.

The control plane resolves the hold (tenant -> host -> cell) and the bench stores +
renders it. Pure toggle owned by the CP -- there is NO local TTL / self-clear.

Key discipline (Stream E decision 3): a PRESENT notice dict is authoritative (it sets
OR clears the mirror); an ABSENT notice (``None``) means the CP could not resolve one
(a transient / partial payload -- e.g. the destroy+reprovision window) -> KEEP the
last-known state, so a brief unresolved poll can't flip a live hold off and dump the
customer into a raw error mid-teardown.

Clearing happens on the CP (operator / roll ``clear_maintenance`` or the fleet-wide
``disable_maintenance_hold`` kill-switch); the bench reflects it on the next refresh.
"""

import frappe

SETTINGS = "Jarvis Settings"
_FIELDS = ("maintenance_active", "maintenance_message")
# One maintenance check refreshes BOTH notices (release + maintenance) from a single
# get_connection, so an active hold doesn't add a second admin round-trip. This throttle
# is INDEPENDENT of release_notice's own (different key) - the two check endpoints don't
# share a window, so polling both within 30s can still make two calls.
_CHECK_CACHE_KEY = "jarvis:maintenance_checked"
_CHECK_CACHE_TTL_S = 30


def persist(notice: dict | None) -> None:
	"""Mirror the admin-sent maintenance notice onto Jarvis Settings.

	``notice`` is a dict (authoritative: ``active`` True sets, False/`{}` clears) or
	``None`` (unknown -> keep the last-known mirror; see the module docstring). Skips a
	no-op write so it doesn't churn ``modified`` under an operator editing the form."""
	try:
		if notice is None:
			return
		fresh = {
			"maintenance_active": 1 if notice.get("active") else 0,
			"maintenance_message": notice.get("message") or "",
		}
		current = frappe.db.get_value(SETTINGS, SETTINGS, list(_FIELDS), as_dict=True) or {}
		if (
			frappe.utils.cint(current.get("maintenance_active")) == fresh["maintenance_active"]
			and (current.get("maintenance_message") or "") == fresh["maintenance_message"]
		):
			return
		frappe.db.set_value(SETTINGS, SETTINGS, fresh, update_modified=False)
	except Exception:
		frappe.log_error(title="maintenance_notice.persist failed", message=frappe.get_traceback())


def boot_payload() -> dict:
	"""``maintenance`` for context.boot and the send gate. active iff the mirror flag is
	set (pure toggle -- the CP owns clearing it; this bench reflects the last-known state
	until the next poll refreshes it). Fails to not-held on any read error."""
	try:
		row = frappe.get_cached_value(SETTINGS, SETTINGS, list(_FIELDS), as_dict=True) or {}
		return {
			"active": bool(frappe.utils.cint(row.get("maintenance_active"))),
			"message": row.get("maintenance_message") or "",
		}
	except Exception:
		frappe.log_error(title="maintenance_notice.boot_payload failed", message=frappe.get_traceback())
		return {"active": False, "message": ""}


@frappe.whitelist(methods=["POST"])
def check() -> dict:
	"""Re-pull the connection from admin and refresh the local maintenance mirror, so an
	open chat tab lifts the hold promptly when the operator/roll clears it. One admin
	round-trip refreshes BOTH notices (release + maintenance) -- an active maintenance
	poll therefore keeps the release mirror fresh too, not a wasted second call. The
	round-trip is cached briefly so many gated tabs cost one call."""
	from jarvis import admin_client, release_notice

	cache = frappe.cache()
	if not cache.get_value(_CHECK_CACHE_KEY, expires=True):
		cache.set_value(_CHECK_CACHE_KEY, "1", expires_in_sec=_CHECK_CACHE_TTL_S)
		try:
			conn = admin_client.get_connection(timeout_s=8) or {}
			release_notice.persist(conn.get("release_notice") or {})
			# Present key = authoritative; absent = unknown -> keep last-known (decision 3).
			persist(conn["maintenance"] if "maintenance" in conn else None)
		except Exception:
			frappe.log_error(title="maintenance_notice.check failed", message=frappe.get_traceback())
	return boot_payload()
