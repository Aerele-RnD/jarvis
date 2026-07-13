"""Revoke the 'Jarvis User' role from Website (portal) users.

Follow-up to ``grant_jarvis_user_role`` (security review PART 1 TASK 6). The
original backfill granted 'Jarvis User' to EVERY enabled user — System Users
AND Website Users — to preserve the previously-open access. But portal/website
users are a distinct, lower-trust population that must not reach Jarvis chat:
the shared access gate (``jarvis.permissions.has_jarvis_access``) now also
requires ``user_type == "System User"``, and the role should follow the same
policy so the two never drift.

We do NOT rewrite the already-applied grant patch (it ran on existing benches);
this new, separately-registered patch removes the role from any Website User
that received it. Idempotent: re-runs are no-ops once the rows are gone.

Website Users legitimately hold NO desk-access role, so a bare ``Has Role`` row
delete is safe — Frappe never renders a portal user through Desk regardless.
"""

import frappe

from jarvis.permissions import JARVIS_USER_ROLE


def execute():
	if not frappe.db.exists("Role", JARVIS_USER_ROLE):
		return

	# Every user that holds the role AND is a Website User.
	holders = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": JARVIS_USER_ROLE},
		pluck="parent",
	)
	if not holders:
		return

	website_users = set(
		frappe.get_all(
			"User",
			filters={"name": ["in", list(set(holders))], "user_type": "Website User"},
			pluck="name",
		)
	)
	for user in website_users:
		# Delete the child Has Role row directly rather than loading + saving the
		# full User doc — mirrors the grant patch's insert-the-row approach.
		frappe.db.delete(
			"Has Role",
			{"parenttype": "User", "parent": user, "role": JARVIS_USER_ROLE},
		)
		frappe.clear_cache(user=user)

	frappe.db.commit()
