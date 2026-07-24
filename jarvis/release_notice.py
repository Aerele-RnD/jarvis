"""Release-notice plumbing: mirror the operator's notice locally and expose it to
the SPA. The notice is a fleet-wide operator switch — no per-tenant version
comparison; it shows to every tenant while active and clears when the operator
turns it off. `latest_jarvis_version` is an optional display badge only.
"""

import frappe

SETTINGS = "Jarvis Settings"
_FIELDS = (
	"release_notice_active",
	"latest_jarvis_version",
	"release_notice_title",
	"release_notice_message",
	"release_notice_url",
)


def persist(notice: dict) -> None:
	"""Mirror the admin-sent notice onto Jarvis Settings so boot reads it with no
	round-trip. Best-effort (never raises); an empty dict clears it."""
	try:
		n = notice or {}
		s = frappe.get_single(SETTINGS)
		s.db_set("release_notice_active", 1 if n.get("active") else 0)
		s.db_set("latest_jarvis_version", n.get("latest_version") or "")
		s.db_set("release_notice_title", n.get("title") or "")
		s.db_set("release_notice_message", n.get("message") or "")
		s.db_set("release_notice_url", n.get("url") or "")
	except Exception:
		pass


def boot_payload() -> dict:
	"""``release_notice`` for context.boot. The SPA gates on active && title."""
	row = frappe.get_cached_value(SETTINGS, SETTINGS, list(_FIELDS), as_dict=True) or {}
	return {
		"active": bool(row.get("release_notice_active")),
		"title": row.get("release_notice_title") or "",
		"message": row.get("release_notice_message") or "",
		"url": row.get("release_notice_url") or "",
		"latest_version": (row.get("latest_jarvis_version") or "").strip(),
	}
