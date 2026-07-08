"""Grant the 'Jarvis User' role to every existing enabled System User.

Before role-gating, Jarvis chat was open to any logged-in user. The gate now
requires the 'Jarvis User' role (or System Manager), so on upgrade we grant the
role to all current enabled System Users to preserve today's open access
exactly (design 2026-07-08-jarvis-user-role-gating-design, section "Rollout").
Admins revoke access afterward as desired.

Idempotent: the role is created if missing (mirroring jarvis/learning/roles.py),
Administrator/Guest are excluded, and users who already hold the role are
skipped, so re-runs are no-ops.
"""

import frappe

_JARVIS_ACCESS_ROLE = "Jarvis User"


def execute():
	# Seed the role in case this runs before after_migrate (mirror learning/roles.py).
	if not frappe.db.exists("Role", _JARVIS_ACCESS_ROLE):
		frappe.get_doc({
			"doctype": "Role", "role_name": _JARVIS_ACCESS_ROLE,
			"desk_access": 1, "is_custom": 1,
		}).insert(ignore_permissions=True)

	# Users that already hold the role (skip these; guards against re-runs).
	already = set(
		frappe.get_all(
			"Has Role",
			filters={"parenttype": "User", "role": _JARVIS_ACCESS_ROLE},
			pluck="parent",
		)
	)

	users = frappe.get_all(
		"User",
		filters={"enabled": 1, "user_type": "System User"},
		pluck="name",
	)

	for user in users:
		if user in ("Administrator", "Guest") or user in already:
			continue
		frappe.get_doc("User", user).add_roles(_JARVIS_ACCESS_ROLE)

	frappe.db.commit()
