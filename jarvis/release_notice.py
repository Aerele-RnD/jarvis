"""Release-notice plumbing: mirror the operator's per-host notice locally and
expose it to the SPA. The control plane resolves which notice (if any) applies to
this tenant's Jarvis Host; the bench just stores and renders what it is given.
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
	round-trip. Best-effort (never raises); an empty dict clears it."""
	try:
		n = notice or {}
		s = frappe.get_single(SETTINGS)
		s.db_set("release_notice_active", 1 if n.get("active") else 0)
		s.db_set("latest_jarvis_version", n.get("version") or "")
		s.db_set("release_notice_message", n.get("message") or "")
	except Exception:
		pass


def boot_payload() -> dict:
	"""``release_notice`` for context.boot. The SPA gates on `active`; the heading
	is composed client-side from the brand name, so no title travels."""
	row = frappe.get_cached_value(SETTINGS, SETTINGS, list(_FIELDS), as_dict=True) or {}
	return {
		"active": bool(row.get("release_notice_active")),
		"version": (row.get("latest_jarvis_version") or "").strip(),
		"message": row.get("release_notice_message") or "",
	}
