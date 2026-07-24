"""Release-notice plumbing: mirror the operator's notice locally and tell the SPA
whether this bench is behind the latest jarvis release.

The control plane ships the notice (copy + latest_version) on the get_connection
payload; the bench self-compares against its own installed ``jarvis.__version__``,
so only out-of-date tenants see it.
"""

import frappe

from jarvis import __version__ as INSTALLED_VERSION

SETTINGS = "Jarvis Settings"
_FIELDS = (
	"release_notice_active",
	"latest_jarvis_version",
	"release_notice_title",
	"release_notice_message",
	"release_notice_url",
)


def _version_tuple(v: str) -> tuple:
	"""Dotted version -> int tuple for ordering; unparseable -> ()."""
	parts = (v or "").strip().split(".")
	out = []
	for p in parts:
		digits = "".join(c for c in p if c.isdigit())
		if not digits:
			return ()
		out.append(int(digits))
	return tuple(out)


def update_available(installed: str, latest: str) -> bool:
	"""True only when both parse and installed < latest. Fail-open: blank/bad
	data => False, so a parse slip never puts up a spurious gate."""
	a, b = _version_tuple(installed), _version_tuple(latest)
	if not a or not b:
		return False
	return a < b


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
	"""``release_notice`` for context.boot: the persisted copy plus a computed
	``update_available`` (installed jarvis vs latest). The SPA gates on
	active && update_available && title."""
	row = frappe.get_cached_value(SETTINGS, SETTINGS, list(_FIELDS), as_dict=True) or {}
	latest = (row.get("latest_jarvis_version") or "").strip()
	return {
		"active": bool(row.get("release_notice_active")),
		"title": row.get("release_notice_title") or "",
		"message": row.get("release_notice_message") or "",
		"url": row.get("release_notice_url") or "",
		"current_version": INSTALLED_VERSION,
		"latest_version": latest,
		"update_available": update_available(INSTALLED_VERSION, latest),
	}
