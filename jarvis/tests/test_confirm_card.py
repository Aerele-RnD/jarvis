"""Tests for jarvis.chat.confirm_card.build_card - the render-ready "what will
change" summary attached to a confirmation card at park (F9).

The builder shapes tool + args + the park-time preview into a structured card the
SPA renders; it never raises (a card is UX, not correctness) and returns None for
shapes it does not cover, so the SPA falls back to the raw preview.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.confirm_card import _MAX_ROWS, build_card


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


class TestBulkUpdateCard(FrappeTestCase):
	"""A batch ``update_doc(updates=[{name, changes}, ...])`` renders a per-record
	from->to card (kind ``bulk_update``) instead of the raw-JSON dump."""

	def _todo(self, **vals):
		vals.setdefault("description", "task")
		doc = frappe.get_doc({"doctype": "ToDo", **vals}).insert(ignore_permissions=True)
		self.addCleanup(lambda n=doc.name: frappe.delete_doc(
			"ToDo", n, force=True, ignore_permissions=True))
		return doc

	def test_bulk_update_lists_per_record_from_to(self):
		t1 = self._todo(description="d1", priority="Medium")
		t2 = self._todo(description="d2", priority="Low")
		args = {"doctype": "ToDo", "updates": [
			{"name": t1.name, "changes": {"priority": "High"}},
			{"name": t2.name, "changes": {"priority": "High"}},
		]}
		would = {"count": 2, "doctype": "ToDo", "updated": [t1.name, t2.name]}
		card = build_card("update_doc", args, {"preview": True, "would": would})
		self.assertEqual(card["kind"], "bulk_update")
		self.assertEqual(card["doctype"], "ToDo")
		self.assertEqual(card["count"], 2)
		self.assertEqual(len(card["records"]), 2)
		self.assertEqual(card["records"][0]["name"], t1.name)
		# OLD from the current doc (Medium), NEW from the requested changes (High).
		self.assertTrue(any(
			d["from"] == "Medium" and d["to"] == "High"
			for d in card["records"][0]["diff"]))
		# each record surfaces the changed field labels for the collapsed summary
		self.assertTrue(card["records"][0]["fields"])

	def test_bulk_update_skips_noop_rows(self):
		t1 = self._todo(priority="High")
		args = {"doctype": "ToDo", "updates": [
			{"name": t1.name, "changes": {"priority": "High"}},  # already High -> no-op
		]}
		card = build_card("update_doc", args, {"would": {}})
		self.assertEqual(card["kind"], "bulk_update")
		self.assertEqual(card["records"][0]["diff"], [])

	def test_bulk_update_normalizes_typed_noop(self):
		# A field set to its CURRENT value - typed in the DB (a Date), a string in
		# the request - must not render a spurious "2026-07-20 -> 2026-07-20" row.
		t1 = self._todo(date="2026-07-20")
		args = {"doctype": "ToDo", "updates": [
			{"name": t1.name, "changes": {"date": "2026-07-20"}},
		]}
		card = build_card("update_doc", args, {"would": {}})
		self.assertEqual(card["records"][0]["diff"], [])

	def test_bulk_update_flags_varying_changes(self):
		t1 = self._todo()
		t2 = self._todo()
		args = {"doctype": "ToDo", "updates": [
			{"name": t1.name, "changes": {"priority": "High"}},
			{"name": t2.name, "changes": {"description": "changed"}},
		]}
		card = build_card("update_doc", args, {"would": {}})
		self.assertTrue(card["varying"])

	def test_bulk_update_homogeneous_not_varying(self):
		t1 = self._todo()
		t2 = self._todo()
		args = {"doctype": "ToDo", "updates": [
			{"name": t1.name, "changes": {"priority": "High"}},
			{"name": t2.name, "changes": {"priority": "High"}},
		]}
		card = build_card("update_doc", args, {"would": {}})
		self.assertFalse(card["varying"])

	def test_bulk_update_caps_records_and_reports_extra(self):
		todos = [self._todo() for _ in range(_MAX_ROWS + 2)]
		args = {"doctype": "ToDo", "updates": [
			{"name": t.name, "changes": {"priority": "High"}} for t in todos]}
		card = build_card("update_doc", args, {"would": {}})
		self.assertEqual(card["count"], _MAX_ROWS + 2)
		self.assertEqual(len(card["records"]), _MAX_ROWS)
		self.assertEqual(card["extra"], 2)


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


from unittest.mock import patch


class TestPhase1Rewire(FrappeTestCase):
	def test_update_card_renders_a_real_change(self):
		# Baseline shape check. NOT a no-op test - a text change passes against the
		# old raw comparison too. The cast-compare logic is covered at the unit level
		# in test_record_summary (TestSameValue) and at card level by the existing
		# test_bulk_update_normalizes_typed_noop.
		todo = frappe.get_doc({"doctype": "ToDo", "description": "x"}).insert(
			ignore_permissions=True)
		card = build_card(
			"update_doc",
			{"doctype": "ToDo", "name": todo.name, "changes": {"description": "y"}},
			{"would": {"description": "y"}})
		self.assertEqual(card["kind"], "update")
		self.assertTrue(any(d["to"] == "y" for d in card["diff"]))

	def test_update_card_drops_an_unchanged_field(self):
		todo = frappe.get_doc({"doctype": "ToDo", "description": "x"}).insert(
			ignore_permissions=True)
		card = build_card(
			"update_doc",
			{"doctype": "ToDo", "name": todo.name, "changes": {"description": "x"}},
			{"would": {"description": "x"}})
		self.assertEqual(card["diff"], [])

	def test_update_card_carries_the_record_title(self):
		# ToDo's title_field is `description`.
		todo = frappe.get_doc({"doctype": "ToDo", "description": "probe title"}).insert(
			ignore_permissions=True)
		card = build_card(
			"update_doc",
			{"doctype": "ToDo", "name": todo.name, "changes": {"priority": "High"}},
			{"would": {"priority": "High"}})
		self.assertIn("probe title", card["title"])

	def test_update_card_checks_read_permission(self):
		# _update_card:143 has the same unchecked get_doc as _bulk_update_card - the
		# spec and both review rounds named only the bulk one. Without this, a user
		# who cannot read the record sees its old values on a single-update card.
		todo = frappe.get_doc({"doctype": "ToDo", "description": "secret"}).insert(
			ignore_permissions=True)
		with patch("frappe.model.document.Document.has_permission", return_value=False):
			card = build_card(
				"update_doc",
				{"doctype": "ToDo", "name": todo.name, "changes": {"description": "y"}},
				{"would": {"description": "y"}})
		# The old value must not appear: the read failed, so `from` is empty.
		self.assertNotIn("secret", str(card))
		self.assertEqual(card["title"], "")

	def test_bulk_update_card_checks_read_permission_on_each_doc(self):
		# The pre-existing hole: get_doc checks nothing, and
		# apply_fieldlevel_read_permissions is permlevel-only, so a user who cannot
		# read a record could see its OLD values on an update card.
		#
		# The degrade is deliberate: the record still lists the caller's own proposed
		# changes (which they authored, so they are not a leak) with an EMPTY `from`,
		# and no title. Asserting "no diff rows" would be wrong - it contradicts the
		# implementation, which cannot skip rows it never loaded.
		todo = frappe.get_doc({"doctype": "ToDo", "description": "secret-old"}).insert(
			ignore_permissions=True)
		with patch("frappe.model.document.Document.has_permission", return_value=False):
			card = build_card(
				"update_doc",
				{"doctype": "ToDo", "updates": [{"name": todo.name, "changes": {"description": "y"}}]},
				{})
		self.assertNotIn("secret-old", str(card))  # the old value must not leak
		self.assertTrue(all(d["from"] == "" for r in card["records"] for d in r["diff"]))
		self.assertEqual(card["records"][0]["title"], "")

	def test_create_card_renders_child_tables(self):
		card = build_card(
			"create_doc",
			{"doctype": "Sales Invoice", "values": {
				"customer": "X",
				"items": [{"item_code": "I-1", "qty": 2}],
			}},
			{"would": {"name": "SI-1", "customer": "X",
					   "items": [{"item_code": "I-1", "qty": 2}]}})
		self.assertTrue(card.get("tables"))
		self.assertEqual(card["tables"][0]["count"], 1)
