"""Tests for the Jarvis Chat Message DocType."""

import frappe
from frappe.tests.utils import FrappeTestCase

DOCTYPE = "Jarvis Chat Message"
CONV_DOCTYPE = "Jarvis Conversation"


def _make_conversation(title: str = "T") -> str:
	doc = frappe.get_doc({
		"doctype": CONV_DOCTYPE,
		"title": title,
		"status": "active",
	})
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def _cleanup_conversation(name: str) -> None:
	for child in frappe.get_all(DOCTYPE, filters={"conversation": name}, pluck="name"):
		frappe.delete_doc(DOCTYPE, child, ignore_permissions=True, force=True)
	frappe.delete_doc(CONV_DOCTYPE, name, ignore_permissions=True, force=True)
	frappe.db.commit()


class TestJarvisChatMessageDocType(FrappeTestCase):
	def test_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", DOCTYPE))

	def test_required_fields_exist(self):
		meta = frappe.get_meta(DOCTYPE)
		field_names = {f.fieldname for f in meta.fields}
		expected = {
			"conversation", "seq", "role", "content",
			"tool_name", "tool_args", "tool_result", "tool_status",
			"streaming", "error",
		}
		missing = expected - field_names
		self.assertFalse(missing, f"missing fields: {missing}")

	def test_role_select_options(self):
		meta = frappe.get_meta(DOCTYPE)
		f = next(f for f in meta.fields if f.fieldname == "role")
		options = (f.options or "").split("\n")
		for r in ("user", "assistant", "tool"):
			self.assertIn(r, options)

	def test_tool_status_select_options(self):
		meta = frappe.get_meta(DOCTYPE)
		f = next(f for f in meta.fields if f.fieldname == "tool_status")
		options = (f.options or "").split("\n")
		for s in ("running", "completed", "error"):
			self.assertIn(s, options)

	def test_conversation_is_required_link(self):
		meta = frappe.get_meta(DOCTYPE)
		f = next(f for f in meta.fields if f.fieldname == "conversation")
		self.assertEqual(f.fieldtype, "Link")
		self.assertEqual(f.options, CONV_DOCTYPE)
		self.assertTrue(f.reqd)

	def test_insert_and_link_to_conversation(self):
		conv = _make_conversation("link-test")
		try:
			msg = frappe.get_doc({
				"doctype": DOCTYPE,
				"conversation": conv,
				"seq": 1,
				"role": "user",
				"content": "hello",
				"streaming": 0,
			})
			msg.insert(ignore_permissions=True)
			frappe.db.commit()
			self.assertEqual(msg.conversation, conv)
		finally:
			_cleanup_conversation(conv)

	def test_owner_only_read_perm(self):
		meta = frappe.get_meta(DOCTYPE)
		for perm in meta.permissions:
			if perm.read:
				self.assertEqual(
					perm.if_owner,
					1,
					f"role {perm.role} has read without if_owner",
				)
