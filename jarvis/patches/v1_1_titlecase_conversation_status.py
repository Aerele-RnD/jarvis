"""Title-Case existing Jarvis Conversation status, matching the new doctype
options. Idempotent (BINARY match on the old value)."""

import frappe


def execute():
	for old, new in (("active", "Active"), ("archived", "Archived")):
		frappe.db.sql(
			"UPDATE `tabJarvis Conversation` SET `status` = %s WHERE BINARY `status` = %s",
			(new, old),
		)
	frappe.db.commit()
