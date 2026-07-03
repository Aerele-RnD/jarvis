"""Tests for the chat action-apply surface (jarvis.chat.actions_api).

The draft side-panel is metadata-driven: form meta must expose child tables
(the whole point — the old get_doctype_fields hid them), load_doc must return
current values for update pre-fill, and apply_action must route to the
permission-checked tools and leave a receipt in the conversation.
"""
from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.actions_api import get_doctype_form_meta, load_doc


class TestFormMeta(FrappeTestCase):
	def test_form_meta_includes_child_table(self):
		# Sales Order is the marquee case: an `items` Table field plus its
		# child columns must be present so the panel can render a grid.
		r = get_doctype_form_meta("Sales Order")
		self.assertTrue(r["ok"])
		self.assertEqual(r["is_submittable"], 1)
		table_fields = [f for f in r["fields"] if f["fieldtype"] == "Table"]
		self.assertIn("items", [f["fieldname"] for f in table_fields])
		items = r["tables"]["items"]
		self.assertEqual(items["child_doctype"], "Sales Order Item")
		colnames = [c["fieldname"] for c in items["columns"]]
		self.assertIn("item_code", colnames)
		self.assertIn("qty", colnames)

	def test_form_meta_unknown_doctype(self):
		self.assertFalse(get_doctype_form_meta("No Such DocType")["ok"])

	def test_form_meta_denies_without_read(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				get_doctype_form_meta("Sales Order")
		finally:
			frappe.set_user("Administrator")


class TestLoadDoc(FrappeTestCase):
	def test_load_doc_returns_values_and_tables(self):
		c = frappe.get_doc({
			"doctype": "Contact", "first_name": "LoadDoc Test",
			"email_ids": [{"email_id": "a@example.com", "is_primary": 1}],
		}).insert()
		self.addCleanup(lambda: frappe.delete_doc("Contact", c.name, force=True))
		r = load_doc("Contact", c.name)
		self.assertTrue(r["ok"])
		self.assertEqual(r["values"]["first_name"], "LoadDoc Test")
		self.assertEqual(r["tables"]["email_ids"][0]["email_id"], "a@example.com")
		self.assertEqual(r["docstatus"], 0)
