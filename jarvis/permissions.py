"""Single source of truth for the Jarvis app-access gate.

Reaching Jarvis at all requires the dedicated ``Jarvis User`` role, with
``System Manager`` always allowed and ``Administrator`` implicitly allowed
(it bypasses all perms).

Enforcement is at the HUMAN ENTRY POINTS — the SPA route (``www/jarvis.py``),
the desk page (``jarvis_chat``) and the user-initiated chat APIs. It is
deliberately NOT applied to machine-authenticated or delegated paths (the
self-hosted plugin tool user, or ``send_message`` invoked under
``set_user(owner)`` by the scheduler / approvals resume), which act as an
identity that legitimately may not hold the role.
"""

from __future__ import annotations

import frappe

# The role name + the access rule, everywhere: "Jarvis User" OR "System Manager"
# (Administrator is implicitly allowed by has_jarvis_access / frappe perms).
# One constant so the seed (learning/roles.py, the grant patch, tests) and the
# gate can never drift.
JARVIS_USER_ROLE = "Jarvis User"
JARVIS_ACCESS_ROLES = ("System Manager", JARVIS_USER_ROLE)


def ensure_jarvis_user_role() -> None:
	"""Idempotently create the ``Jarvis User`` role (desk-access). Shared by the
	after_migrate seed and the one-time grant patch so the role definition lives
	in exactly one place."""
	if not frappe.db.exists("Role", JARVIS_USER_ROLE):
		frappe.get_doc({
			"doctype": "Role",
			"role_name": JARVIS_USER_ROLE,
			"desk_access": 1,
			"is_custom": 1,
		}).insert(ignore_permissions=True)


def has_jarvis_access(user: str | None = None) -> bool:
	"""True iff ``user`` may reach Jarvis.

	``Administrator`` is always allowed; otherwise the user must hold at least
	one of :data:`JARVIS_ACCESS_ROLES`. Defaults to the current session user."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(JARVIS_ACCESS_ROLES) & set(frappe.get_roles(user)))


def require_jarvis_access(user: str | None = None) -> None:
	"""Raise ``frappe.PermissionError`` (with a clear message) if the user lacks
	access. Defaults to the current session user.

	Note: implemented directly rather than via ``frappe.only_for`` — in this
	Frappe version ``only_for`` treats its ``message`` argument as a boolean flag
	and would discard a custom string, showing a generic desk-role error."""
	if not has_jarvis_access(user):
		frappe.throw(
			"You need the Jarvis User role to use Jarvis. Ask an administrator for access.",
			frappe.PermissionError,
		)
