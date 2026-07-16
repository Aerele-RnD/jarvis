"""Retire the 'Knowledge Wiki User' role.

Personal (User-scope) wiki editing was consolidated onto the platform
'Jarvis User' role: the human write matrix (wiki_permissions.can_edit_page)
now lets any Jarvis User edit their own page, and 'Jarvis Admin' inherits
'Knowledge Wiki Manager' for curation. 'Knowledge Wiki User' no longer carries
any capability, so drop it — after making sure no holder loses own-page
editing.

Idempotent (no-op once the role is gone):
  1. ensure 'Jarvis User' exists;
  2. grant 'Jarvis User' to any KW-User holder lacking it (preserves own-page
     editing — the capability KW-User used to confer);
  3. delete the role's Has Role rows, then the Role itself (best-effort).
'Knowledge Wiki Manager' is untouched.
"""

import frappe

from jarvis.permissions import JARVIS_USER_ROLE, ensure_jarvis_user_role

RETIRED_ROLE = "Knowledge Wiki User"


def execute():
	if not frappe.db.exists("Role", RETIRED_ROLE):
		return

	# Seed the platform role in case this runs before after_migrate.
	ensure_jarvis_user_role()

	holders = set(
		frappe.get_all(
			"Has Role",
			filters={"parenttype": "User", "role": RETIRED_ROLE},
			pluck="parent",
		)
	)
	already = set(
		frappe.get_all(
			"Has Role",
			filters={"parenttype": "User", "role": JARVIS_USER_ROLE},
			pluck="parent",
		)
	)
	# Preserve own-page editing for any holder that lacks the platform role.
	for user in holders - already:
		if user in ("Administrator", "Guest"):
			continue
		frappe.get_doc({
			"doctype": "Has Role",
			"parenttype": "User",
			"parentfield": "roles",
			"parent": user,
			"role": JARVIS_USER_ROLE,
		}).insert(ignore_permissions=True)

	# Drop every assignment of the retired role, then the Role row itself.
	frappe.db.delete("Has Role", {"role": RETIRED_ROLE})
	try:
		frappe.delete_doc("Role", RETIRED_ROLE, force=1, ignore_permissions=True)
	except Exception:
		# A stray link must not block migrate; the role is already unseeded and
		# stripped of assignments, so it is functionally retired.
		frappe.log_error(
			title="retire Knowledge Wiki User: role delete deferred",
			message=frappe.get_traceback(),
		)
	frappe.db.commit()
