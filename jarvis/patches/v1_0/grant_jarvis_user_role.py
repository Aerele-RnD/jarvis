"""Grant the 'Jarvis User' role to every existing enabled user.

Before role-gating, Jarvis chat was open to ANY logged-in user (the SPA route
and chat APIs had no role check). The gate now requires the 'Jarvis User' role
(or System Manager), so on upgrade we grant the role to every current enabled
user — System Users AND Website Users, since both could reach Jarvis before — to
preserve today's open access exactly (design 2026-07-08-jarvis-user-role-gating,
section "Rollout"). Admins revoke access afterward as desired.

Idempotent: the role is created if missing (shared helper), Administrator/Guest
are excluded, and users who already hold the role are skipped, so re-runs are
no-ops.
"""

import frappe

from jarvis.permissions import JARVIS_USER_ROLE, ensure_jarvis_user_role


def execute():
	# Seed the role in case this runs before after_migrate.
	ensure_jarvis_user_role()

	# Users that already hold the role (skip these; guards against re-runs).
	already = set(
		frappe.get_all(
			"Has Role",
			filters={"parenttype": "User", "role": JARVIS_USER_ROLE},
			pluck="parent",
		)
	)

	# EVERY enabled user (System + Website) — matches the previously-open access.
	users = frappe.get_all("User", filters={"enabled": 1}, pluck="name")

	for user in users:
		if user in ("Administrator", "Guest") or user in already:
			continue
		# Insert the child Has Role row directly rather than loading + saving the
		# full User doc per user — a one-time grant over the whole user table.
		frappe.get_doc(
			{
				"doctype": "Has Role",
				"parenttype": "User",
				"parentfield": "roles",
				"parent": user,
				"role": JARVIS_USER_ROLE,
			}
		).insert(ignore_permissions=True)

	frappe.db.commit()
