"""Mirror the operator's per-host release notice locally and expose it to the SPA.

The control plane decides which notice (if any) applies to this tenant; the bench
stores what it is given and renders it.
"""

import frappe

SETTINGS = "Jarvis Settings"
_FIELDS = (
	"release_notice_active",
	"latest_jarvis_version",
	"release_notice_message",
)


def persist(notice: dict) -> None:
	"""Mirror the admin-sent notice onto Jarvis Settings so boot reads it with no
	round-trip. Best-effort; an empty dict clears it."""
	try:
		n = notice or {}
		s = frappe.get_single(SETTINGS)
		s.db_set("release_notice_active", 1 if n.get("active") else 0)
		s.db_set("latest_jarvis_version", n.get("version") or "")
		s.db_set("release_notice_message", n.get("message") or "")
	except Exception:
		pass


def boot_payload() -> dict:
	"""``release_notice`` for context.boot. The SPA gates on `active`."""
	row = frappe.get_cached_value(SETTINGS, SETTINGS, list(_FIELDS), as_dict=True) or {}
	return {
		"active": bool(row.get("release_notice_active")),
		"version": (row.get("latest_jarvis_version") or "").strip(),
		"message": row.get("release_notice_message") or "",
	}


@frappe.whitelist()
def check() -> dict:
	"""Re-pull the notice from admin and return the refreshed payload.

	The gate calls this so an updated tenant unblocks straight away instead of
	waiting for the daily sync - the mobile PWA has no other refresh path, and an
	already-open tab has none at all. Best-effort: an unreachable admin just
	returns the current mirror."""
	from jarvis import admin_client

	try:
		conn = admin_client.get_connection(timeout_s=8) or {}
		persist(conn.get("release_notice") or {})
	except Exception:
		pass
	return boot_payload()
