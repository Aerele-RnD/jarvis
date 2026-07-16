"""Remove the Jarvis User Preference DocType after v1_16 copied its data into
Jarvis User Settings. Guarded so it no-ops on a fresh DB where the DocType was
never created (its folder is gone from the app).

Note: frappe.delete_doc("DocType", ...) only removes the DocType *metadata*
row (tabDocType) plus its DocField/DocPerm children - it does NOT drop the
doctype's own physical data table. That extra DROP TABLE is required and is
the same two-step sequence frappe.installer._delete_doctypes uses when an app
is uninstalled (frappe/installer.py)."""

import frappe


def execute():
	if frappe.db.exists("DocType", "Jarvis User Preference"):
		frappe.delete_doc(
			"DocType", "Jarvis User Preference", force=True, ignore_missing=True, ignore_on_trash=True
		)
		frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabJarvis User Preference`")
		frappe.db.commit()
