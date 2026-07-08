"""Single source of truth for the Jarvis app-access gate.

Reaching Jarvis at all requires the dedicated ``Jarvis User`` role, with
``System Manager`` always allowed and ``Administrator`` implicitly allowed
(it bypasses all perms). Every enforcement point (chat APIs, plugin
``call_tool``, the SPA route, the desk page) checks through the helpers here
rather than inlining a role list, so the rule stays in one place.
"""

from __future__ import annotations

import frappe

# The access rule, everywhere: "Jarvis User" OR "System Manager"
# (Administrator is implicitly allowed by has_jarvis_access / frappe perms).
JARVIS_ACCESS_ROLES = ("System Manager", "Jarvis User")


def has_jarvis_access(user: str | None = None) -> bool:
	"""True iff ``user`` may reach Jarvis.

	``Administrator`` is always allowed; otherwise the user must hold at least
	one of :data:`JARVIS_ACCESS_ROLES`. Defaults to the current session user."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(JARVIS_ACCESS_ROLES) & set(frappe.get_roles(user)))


def require_jarvis_access() -> None:
	"""Raise ``frappe.PermissionError`` if the current session user lacks access.

	``frappe.only_for`` accepts a list/tuple as any-of, so this passes when the
	user holds any of :data:`JARVIS_ACCESS_ROLES` (and always for Administrator,
	which ``only_for`` special-cases)."""
	frappe.only_for(JARVIS_ACCESS_ROLES, message="Access to Jarvis requires the Jarvis User role.")
