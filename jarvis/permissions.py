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

# The tenant-side admin role (design section 2): a customer power-user who can
# manage Jarvis (per-user usage limits, the admin pane) WITHOUT full System
# Manager rights.
#
# NAMING NOTE: the control-plane app (``jarvis_admin``, a DIFFERENT site in a
# different tree) defines an UNRELATED role also named "Jarvis Admin" for Aerele
# ops staff. Roles are site-local so there is no technical clash; here "Jarvis
# Admin" means *the tenant's own admin*. This comment exists so a cross-repo grep
# finds the disambiguation.
JARVIS_ADMIN_ROLE = "Jarvis Admin"

# App-access: a Jarvis Admin can also use chat (appended so an admin isn't
# locked out of the surface they administer).
JARVIS_ACCESS_ROLES = ("System Manager", JARVIS_USER_ROLE, JARVIS_ADMIN_ROLE)

# Tenant-admin gate: System Manager OR the tenant admin role (Administrator is
# implicitly allowed by has_jarvis_admin_access).
JARVIS_ADMIN_ROLES = ("System Manager", JARVIS_ADMIN_ROLE)


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


# --------------------------------------------------------------------------- #
# Tenant-admin gate (design section 2). Mirrors the app-access helpers above so
# the seed (learning/roles.py), the boot flag (www/jarvis.py), the admin APIs
# (chat/user_settings_api.py) and tests share one source of truth.
# --------------------------------------------------------------------------- #


def ensure_jarvis_admin_role() -> None:
	"""Idempotently create the ``Jarvis Admin`` role (desk-access, custom).
	Definition lives here (single source of truth); the after_migrate seed
	calls this so the role exists on every migrated site."""
	if not frappe.db.exists("Role", JARVIS_ADMIN_ROLE):
		frappe.get_doc({
			"doctype": "Role",
			"role_name": JARVIS_ADMIN_ROLE,
			"desk_access": 1,
			"is_custom": 1,
		}).insert(ignore_permissions=True)


def has_jarvis_admin_access(user: str | None = None) -> bool:
	"""True iff ``user`` may administer other users' Jarvis usage.

	``Administrator`` is always allowed (it bypasses all perms); otherwise the
	user must hold at least one of :data:`JARVIS_ADMIN_ROLES`. Defaults to the
	current session user."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(JARVIS_ADMIN_ROLES) & set(frappe.get_roles(user)))


def require_jarvis_admin(user: str | None = None) -> None:
	"""Raise ``frappe.PermissionError`` (with a clear message) if the user is not
	a Jarvis Admin (or System Manager / Administrator). Defaults to the current
	session user. Implemented directly, not via ``frappe.only_for`` (same reason
	as :func:`require_jarvis_access`)."""
	if not has_jarvis_admin_access(user):
		frappe.throw(
			"You need the Jarvis Admin role to manage Jarvis users. "
			"Ask an administrator for access.",
			frappe.PermissionError,
		)
