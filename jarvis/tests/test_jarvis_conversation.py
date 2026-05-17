"""Tests for the Jarvis Conversation DocType.

Schema, permissions (owner-only read), and the before_insert default for
last_active_at.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

DOCTYPE = "Jarvis Conversation"


class TestJarvisConversationDocType(FrappeTestCase):
	def test_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", DOCTYPE))

	def test_required_fields_exist(self):
		meta = frappe.get_meta(DOCTYPE)
		field_names = {f.fieldname for f in meta.fields}
		for required in ("title", "session_key", "last_active_at", "status"):
			self.assertIn(required, field_names, f"missing field: {required}")

	def test_session_key_is_unique(self):
		meta = frappe.get_meta(DOCTYPE)
		f = next(f for f in meta.fields if f.fieldname == "session_key")
		self.assertTrue(f.unique, "session_key must be unique")

	def test_status_select_options(self):
		meta = frappe.get_meta(DOCTYPE)
		f = next(f for f in meta.fields if f.fieldname == "status")
		self.assertEqual(f.fieldtype, "Select")
		options = (f.options or "").split("\n")
		self.assertIn("active", options)
		self.assertIn("archived", options)

	def test_owner_can_read_own_only(self):
		"""Permissions are owner-only (no role grants global read)."""
		meta = frappe.get_meta(DOCTYPE)
		for perm in meta.permissions:
			# Any read permission must be scoped: if_owner=1
			if perm.read:
				self.assertEqual(
					perm.if_owner,
					1,
					f"role {perm.role} has read without if_owner",
				)

	def test_before_insert_sets_last_active_at(self):
		try:
			doc = frappe.get_doc({
				"doctype": DOCTYPE,
				"title": "Test chat",
				"status": "active",
			})
			doc.insert(ignore_permissions=True)
			self.assertIsNotNone(doc.last_active_at)
		finally:
			frappe.delete_doc(DOCTYPE, doc.name, ignore_permissions=True, force=True)
			frappe.db.commit()
