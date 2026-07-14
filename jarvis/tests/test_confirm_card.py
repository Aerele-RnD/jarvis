"""Tests for jarvis.chat.confirm_card.build_card - the render-ready "what will
change" summary attached to a confirmation card at park (F9).

The builder shapes tool + args + the park-time preview into a structured card the
SPA renders; it never raises (a card is UX, not correctness) and returns None for
shapes it does not cover, so the SPA falls back to the raw preview.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.confirm_card import build_card


class TestCreateCard(FrappeTestCase):
	def test_create_lists_set_fields_from_would(self):
		would = {"name": "TODO-NEW-1", "description": "buy milk", "priority": "High"}
		card = build_card(
			"create_doc",
			{"doctype": "ToDo", "values": {"description": "buy milk", "priority": "High"}},
			{"preview": True, "would": would})
		self.assertEqual(card["kind"], "create")
		self.assertEqual(card["doctype"], "ToDo")
		self.assertEqual(card["name"], "TODO-NEW-1")
		labels = {r["value"] for r in card["rows"]}
		self.assertIn("buy milk", labels)
		self.assertIn("High", labels)

	def test_create_hides_fields_absent_from_permfiltered_would(self):
		# A field the model set but that is NOT in the perm-filtered ``would`` is
		# dropped (never leak a restricted field's value).
		card = build_card(
			"create_doc",
			{"doctype": "ToDo", "values": {"description": "x", "secret_field": "SEE"}},
			{"would": {"name": "T-1", "description": "x"}})
		vals = {r["value"] for r in card["rows"]}
		self.assertIn("x", vals)
		self.assertNotIn("SEE", vals)


class TestUpdateCard(FrappeTestCase):
	def test_update_shows_from_to_diff(self):
		todo = frappe.get_doc({
			"doctype": "ToDo", "description": "old desc", "priority": "Medium",
		}).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc(
			"ToDo", todo.name, force=True, ignore_permissions=True))
		would = {"description": "new desc", "priority": "Low"}
		card = build_card(
			"update_doc",
			{"doctype": "ToDo", "name": todo.name,
			 "changes": {"description": "new desc", "priority": "Low"}},
			{"would": would})
		self.assertEqual(card["kind"], "update")
		self.assertEqual(card["name"], todo.name)
		by_from = {d["from"]: d["to"] for d in card["diff"]}
		# OLD from the current doc, NEW from ``would``.
		self.assertEqual(by_from.get("old desc"), "new desc")
		self.assertEqual(by_from.get("Medium"), "Low")

	def test_update_skips_unchanged_and_permhidden(self):
		todo = frappe.get_doc({
			"doctype": "ToDo", "description": "same", "priority": "Medium",
		}).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc(
			"ToDo", todo.name, force=True, ignore_permissions=True))
		would = {"description": "same"}  # no-op change; priority not in would
		card = build_card(
			"update_doc",
			{"doctype": "ToDo", "name": todo.name,
			 "changes": {"description": "same", "priority": "High"}},
			{"would": would})
		# description is a no-op (from == to) and priority is not perm-visible.
		self.assertEqual(card["diff"], [])


class TestVerbCard(FrappeTestCase):
	def test_single_verb(self):
		card = build_card("submit_doc", {"doctype": "Sales Order", "name": "SO-1"}, {"would": {}})
		self.assertEqual(card["kind"], "verb")
		self.assertEqual(card["verb"], "submit")
		self.assertEqual(card["doctype"], "Sales Order")
		self.assertEqual(card["targets"], ["SO-1"])
		self.assertEqual(card["count"], 1)

	def test_bulk_verb_lists_targets(self):
		names = [f"SO-{i}" for i in range(3)]
		card = build_card("cancel_doc", {"doctype": "Sales Order", "names": names}, {})
		self.assertEqual(card["verb"], "cancel")
		self.assertEqual(card["count"], 3)
		self.assertEqual(card["targets"], names)

	def test_workflow_action_carries_action(self):
		card = build_card(
			"apply_workflow_action",
			{"doctype": "Sales Order", "name": "SO-1", "action": "Approve"}, {})
		self.assertEqual(card["verb"], "apply")
		self.assertEqual(card["action"], "Approve")


class TestEmailAndMethodCards(FrappeTestCase):
	def test_email_shows_to_subject_body(self):
		card = build_card(
			"send_email",
			{"recipients": "a@x.test", "subject": "Hi", "content": "the body"}, {})
		self.assertEqual(card["kind"], "email")
		self.assertEqual(card["to"], "a@x.test")
		self.assertEqual(card["subject"], "Hi")
		self.assertEqual(card["body"], "the body")

	def test_bulk_email_falls_back(self):
		card = build_card("send_email", {"messages": [{"recipients": "a@x.test"}]}, {})
		self.assertIsNone(card)

	def test_method_masks_secret_arg_keys(self):
		card = build_card(
			"run_method",
			{"method": "some.method", "args": {"doc": "X", "api_key": "SECRET", "password": "p"}},
			{})
		self.assertEqual(card["kind"], "method")
		self.assertEqual(card["method"], "some.method")
		self.assertEqual(card["args"]["doc"], "X")
		self.assertEqual(card["args"]["api_key"], "[hidden]")
		self.assertEqual(card["args"]["password"], "[hidden]")


class TestBatchAndFallback(FrappeTestCase):
	def test_batch_create_from_would_created(self):
		would = {"created": [
			{"doctype": "ToDo", "name": "T-1"}, {"doctype": "ToDo", "name": "T-2"}],
			"notes": ["reused Supplier X"]}
		card = build_card(
			"create_doc", {"docs": [{"doctype": "ToDo", "values": {}}]}, {"would": would})
		self.assertEqual(card["kind"], "batch_create")
		self.assertEqual(card["count"], 2)
		self.assertEqual([r["name"] for r in card["rows"]], ["T-1", "T-2"])
		self.assertEqual(card["notes"], ["reused Supplier X"])

	def test_uncovered_tool_returns_none(self):
		self.assertIsNone(build_card("share_doc", {"doctype": "ToDo", "name": "T-1"}, {}))
		self.assertIsNone(build_card("assign_to", {"doctype": "ToDo", "name": "T-1"}, {}))

	def test_never_raises_on_bad_input(self):
		self.assertIsNone(build_card("update_doc", None, None))
		self.assertIsNone(build_card("create_doc", "not-a-dict", {}))

	def test_long_value_truncated(self):
		would = {"name": "T-1", "description": "z" * 500}
		card = build_card(
			"create_doc", {"doctype": "ToDo", "values": {"description": "z" * 500}},
			{"would": would})
		shown = card["rows"][0]["value"]
		self.assertLessEqual(len(shown), 200)
		self.assertTrue(shown.endswith("…"))
