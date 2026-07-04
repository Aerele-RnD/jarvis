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


from unittest.mock import patch

from jarvis.chat.actions_api import apply_action


def _make_conversation() -> str:
	conv = frappe.get_doc({
		"doctype": "Jarvis Conversation", "title": "actions-api test",
	}).insert(ignore_permissions=True)
	return conv.name


class TestApplyAction(FrappeTestCase):
	def _cleanup_doc(self, doctype, name):
		self.addCleanup(lambda: frappe.delete_doc(doctype, name, force=True, ignore_permissions=True))

	def _conv(self) -> str:
		conv = _make_conversation()
		self.addCleanup(lambda: frappe.delete_doc("Jarvis Conversation", conv, force=True, ignore_permissions=True))
		return conv

	def test_create_simple(self):
		r = apply_action(frappe.as_json({
			"verb": "create", "doctype": "ToDo",
			"values": {"description": "draft panel create test"},
			"conversation": self._conv(),
		}))
		self._cleanup_doc("ToDo", r["name"])
		self.assertTrue(r["ok"])
		self.assertTrue(frappe.db.exists("ToDo", r["name"]))

	def test_create_with_child_rows(self):
		r = apply_action(frappe.as_json({
			"verb": "create", "doctype": "Contact",
			"values": {
				"first_name": "DraftPanel Child Test",
				"email_ids": [
					{"email_id": "one@example.com", "is_primary": 1},
					{"email_id": "two@example.com"},
				],
			},
			"conversation": self._conv(),
		}))
		self._cleanup_doc("Contact", r["name"])
		doc = frappe.get_doc("Contact", r["name"])
		self.assertEqual(len(doc.email_ids), 2)
		self.assertEqual(doc.email_ids[1].email_id, "two@example.com")

	def test_update_replaces_child_rows(self):
		c = frappe.get_doc({
			"doctype": "Contact", "first_name": "DraftPanel Update Test",
			"email_ids": [{"email_id": "old@example.com", "is_primary": 1}],
		}).insert()
		self._cleanup_doc("Contact", c.name)
		apply_action(frappe.as_json({
			"verb": "update", "doctype": "Contact", "name": c.name,
			"values": {"email_ids": [
				{"email_id": "new1@example.com", "is_primary": 1},
				{"email_id": "new2@example.com"},
			]},
			"conversation": self._conv(),
		}))
		doc = frappe.get_doc("Contact", c.name)
		self.assertEqual(
			sorted(e.email_id for e in doc.email_ids),
			["new1@example.com", "new2@example.com"],
		)

	def test_confirm_verbs_rejected_here(self):
		# submit/cancel/delete/amend are confirm-as-proposed actions: they must
		# go through the token gate (confirm_tool), never the human-edit path.
		from jarvis.exceptions import InvalidArgumentError
		conv = self._conv()
		for verb in ("submit", "cancel", "delete", "amend"):
			with self.assertRaises(InvalidArgumentError) as cm:
				apply_action(frappe.as_json({
					"verb": verb, "doctype": "ToDo", "name": "whatever",
					"conversation": conv,
				}))
			self.assertIn("confirm", str(cm.exception).lower())

	def test_unknown_verb_refused(self):
		from jarvis.exceptions import InvalidArgumentError
		with self.assertRaises(InvalidArgumentError):
			apply_action(frappe.as_json({
				"verb": "yolo", "doctype": "ToDo", "conversation": self._conv(),
			}))

	def test_missing_conversation_rejected(self):
		# conversation is mandatory now - an edit can only act inside the
		# caller's own conversation, so there is always one.
		from jarvis.exceptions import InvalidArgumentError
		with self.assertRaises(InvalidArgumentError):
			apply_action(frappe.as_json({
				"verb": "create", "doctype": "ToDo",
				"values": {"description": "no conversation"},
			}))

	def test_create_doc_url_contract(self):
		r = apply_action(frappe.as_json({
			"verb": "create", "doctype": "ToDo",
			"values": {"description": "doc_url contract test"},
			"conversation": self._conv(),
		}))
		self._cleanup_doc("ToDo", r["name"])
		self.assertEqual(r["doc_url"], f"/app/todo/{r['name']}")

	def test_create_then_submit_of_own_draft(self):
		# create with submit:1 stays supported - it submits the JUST-created
		# draft the human authored (same payload they saw), low risk.
		from frappe.core.doctype.doctype.test_doctype import new_doctype
		dt = new_doctype(custom=1, is_submittable=1).insert()
		self.addCleanup(lambda: frappe.delete_doc("DocType", dt.name, force=True, ignore_permissions=True))
		r = apply_action(frappe.as_json({
			"verb": "create", "doctype": dt.name,
			"values": {"some_fieldname": "lifecycle test"}, "submit": 1,
			"conversation": self._conv(),
		}))
		self.assertTrue(r["ok"])
		self.assertEqual(frappe.db.get_value(dt.name, r["name"], "docstatus"), 1)

	def test_create_is_audited_as_human_write(self):
		with patch("jarvis.chat.actions_api.audit.record") as rec:
			r = apply_action(frappe.as_json({
				"verb": "create", "doctype": "ToDo",
				"values": {"description": "audit test"},
				"conversation": self._conv(),
			}))
		self._cleanup_doc("ToDo", r["name"])
		self.assertTrue(rec.called)
		kwargs = rec.call_args.kwargs
		self.assertTrue(kwargs["ok"])
		# label makes clear it was human-authored via apply_action, distinct
		# from a model tool call.
		self.assertIn("apply_action", kwargs["tool"])

	def test_receipt_messages_appended(self):
		conv = self._conv()
		r = apply_action(frappe.as_json({
			"verb": "create", "doctype": "ToDo",
			"values": {"description": "receipt test"},
			"conversation": conv,
		}))
		self._cleanup_doc("ToDo", r["name"])
		msgs = frappe.get_all(
			"Jarvis Chat Message", filters={"conversation": conv},
			fields=["role", "content", "tool_name"], order_by="seq asc",
		)
		self.assertEqual([m.role for m in msgs], ["tool", "assistant"])
		self.assertEqual(msgs[0].tool_name, "create_doc")
		self.assertIn(r["name"], msgs[1].content)

	def test_conversation_ownership_enforced(self):
		conv = self._conv()  # owner = Administrator
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				apply_action(frappe.as_json({
					"verb": "create", "doctype": "ToDo",
					"values": {"description": "x"}, "conversation": conv,
				}))
		finally:
			frappe.set_user("Administrator")
