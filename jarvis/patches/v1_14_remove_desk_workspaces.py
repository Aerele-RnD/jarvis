"""Remove Desk workspace navigation entries for the Jarvis app.

The Frappe Desk workspace/sidebar entries (a "Jarvis" Desktop Icon folder
plus three Workspace Sidebar pages: Chat, Account, Onboarding) are being
retired in favor of SPA-only entry points - an in-app onboarding popup and
a floating "go to chat" icon rendered inside /jarvis itself. The Desk
workspace nav is no longer part of the product.

These were "standard": 1 fixture records imported from
jarvis/desktop_icon/*.json and jarvis/workspace_sidebar/*.json (now deleted
in this same change). Deleting the JSON files stops them being RE-CREATED
on a fresh install, but Frappe's fixture-import machinery does not delete
already-installed rows on existing sites - so every current site
(site.jarvis, jarvis.proxy, jarvis.admin, and every customer/CI site
created before this patch) still has the DB rows and would keep showing
the old Desk nav. This patch removes those rows directly.

Defensive/idempotent by design:
- Guarded with frappe.db.table_exists: both doctypes ship with the
  framework so the table should always exist, but we don't assume it (and
  a fresh CI site migrating straight through with the JSONs already gone
  never creates these rows in the first place, so the filter matching
  zero rows is expected and fine).
- Each delete is wrapped in try/except so a partially migrated site can
  never fail the migrate over these cosmetic Desk-nav rows.
- Safe to re-run: frappe.db.delete on an already-empty filter is a no-op.
"""

import frappe


def execute():
	# Desktop Icon rows registered by jarvis/desktop_icon/*.json (Chat,
	# Account, Onboarding, Jarvis) all carry app == "jarvis".
	try:
		if frappe.db.table_exists("Desktop Icon"):
			frappe.db.delete("Desktop Icon", {"app": "jarvis"})
	except Exception:
		pass  # rows may never have existed, or table shape may differ

	# Workspace Sidebar rows registered by jarvis/workspace_sidebar/*.json
	# (Chat, Account, Onboarding) all carry module == "Jarvis".
	try:
		if frappe.db.table_exists("Workspace Sidebar"):
			frappe.db.delete("Workspace Sidebar", {"module": "Jarvis"})
	except Exception:
		pass  # rows may never have existed, or table shape may differ

	frappe.db.commit()
