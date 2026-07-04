import frappe


def execute():
	"""Jarvis Approval -> Jarvis Approval Request: the old name read as
	'an approved thing'; the doctype stores the whole request lifecycle
	(Pending IS the queue, decided rows stay as the audit trail)."""
	if frappe.db.exists("DocType", "Jarvis Approval") and not frappe.db.exists(
		"DocType", "Jarvis Approval Request"
	):
		frappe.rename_doc("DocType", "Jarvis Approval", "Jarvis Approval Request", force=True)
