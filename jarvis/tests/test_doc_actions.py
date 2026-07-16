from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.tools import _doc_actions
from jarvis.tools._doc_actions import get_doc_actions
from jarvis.tools.get_schema import get_schema


class TestDocActions(FrappeTestCase):
	"""Extraction of whitelisted, button-surfaced server methods per DocType.

	Runs against a real bench with erpnext installed (Sales Order etc.).
	Discovery is fail-safe: the helper must never raise and must only ever
	return methods that genuinely resolve + pass is_whitelisted.
	"""

	def test_sales_order_surfaces_make_mappers(self):
		"""The high-value create-from mapper family (added by base controllers
		but implemented in the subclass sales_order.js) is captured."""
		actions = get_doc_actions("Sales Order")
		self.assertTrue(actions, "expected Sales Order to expose button actions")
		tails = {a["method"].rsplit(".", 1)[-1] for a in actions}
		self.assertTrue(
			{"make_delivery_note", "make_sales_order"} & tails,
			f"expected make_* mappers, got {sorted(tails)}",
		)
		self.assertEqual(set(actions[0].keys()), {"method", "label", "args"})

	def test_returned_methods_are_dotted_and_whitelisted(self):
		"""Every surfaced method is a full dotted path (run_method-callable) and
		actually whitelisted - the validation step is doing real work."""
		actions = get_doc_actions("Sales Order")
		for a in actions:
			self.assertIn(".", a["method"], f"{a['method']} is not a dotted path")
			fn = frappe.get_attr(a["method"])
			frappe.is_whitelisted(fn)  # raises if not whitelisted -> test fails

	def test_capped_at_max(self):
		"""A pathological form can't blow the context budget - result is capped."""
		many = " ".join(f'x.xcall("a.b.c{i}")' for i in range(_doc_actions._MAX_ACTIONS + 15))
		with (
			patch.object(_doc_actions, "_assembled_form_js", return_value=many),
			patch.object(
				_doc_actions,
				"_validated_action",
				side_effect=lambda dotted, installed_apps=None: {
					"method": dotted,
					"label": dotted,
					"args": [],
				},
			),
		):
			actions = get_doc_actions("Whatever")
		self.assertEqual(len(actions), _doc_actions._MAX_ACTIONS)

	def test_candidate_resolution_is_bounded(self):
		"""A form with far more distinct methods than the cap must not resolve
		(import) all of them - work is bounded, not just output."""
		n = _doc_actions._MAX_CANDIDATES + 50
		js = " ".join(f'x.xcall("a.b.c{i}")' for i in range(n))
		calls = []
		with (
			patch.object(_doc_actions, "_assembled_form_js", return_value=js),
			patch.object(
				_doc_actions,
				"_validated_action",
				side_effect=lambda dotted, installed_apps=None: calls.append(dotted) or None,
			),
		):
			get_doc_actions("Whatever")
		self.assertLessEqual(len(calls), _doc_actions._MAX_CANDIDATES)

	def test_own_doctype_methods_rank_first(self):
		"""When the cap bites, the DocType's own actions outrank foreign
		reverse-mappers even if the foreign path sorts earlier alphabetically."""
		js = (
			'x.xcall("erpnext.buying.doctype.purchase_order.mapper.a_make");'
			'x.xcall("erpnext.selling.doctype.sales_order.mapper.z_make");'
		)
		with (
			patch.object(_doc_actions, "_assembled_form_js", return_value=js),
			patch.object(
				_doc_actions,
				"_validated_action",
				side_effect=lambda dotted, installed_apps=None: {"method": dotted, "label": "", "args": []},
			),
		):
			actions = get_doc_actions("Sales Order")
		self.assertEqual(actions[0]["method"].split(".")[3], "sales_order")

	def test_no_message_log_pollution(self):
		"""Rejecting an uninstalled-app ref or a resolvable-but-unwhitelisted
		method must not leak stray messages into frappe.local.message_log (the
		throwing APIs append before raising; we must avoid them)."""
		js = 'frappe.call({ method: "notanapp.foo.bar" });frappe.call({ method: "frappe.utils.get_url" });'
		before = len(frappe.local.message_log or [])
		with patch.object(_doc_actions, "_assembled_form_js", return_value=js):
			actions = get_doc_actions("Whatever")
		self.assertEqual(actions, [])
		self.assertEqual(len(frappe.local.message_log or []), before)

	def test_empty_when_no_form_js(self):
		with patch.object(_doc_actions, "_assembled_form_js", return_value=""):
			self.assertEqual(get_doc_actions("Sales Order"), [])

	def test_real_method_extracted_from_synthetic_js(self):
		"""A dotted, whitelisted method referenced in the form JS is returned."""
		js = 'frappe.call({ method: "frappe.client.get_list", args: {} });'
		with patch.object(_doc_actions, "_assembled_form_js", return_value=js):
			methods = {a["method"] for a in get_doc_actions("Whatever")}
		self.assertIn("frappe.client.get_list", methods)

	def test_bogus_dotted_method_filtered(self):
		"""A dotted string that isn't a real whitelisted method is dropped."""
		js = 'frappe.call({ method: "not.a.real.whitelisted.method" });'
		with patch.object(_doc_actions, "_assembled_form_js", return_value=js):
			self.assertEqual(get_doc_actions("Whatever"), [])

	def test_relative_docmethod_skipped(self):
		"""A bare (non-dotted) name is a doc-method run_method can't call - skip."""
		js = 'frappe.call({ doc: frm.doc, method: "create_stock_reservation_entries" });'
		with patch.object(_doc_actions, "_assembled_form_js", return_value=js):
			self.assertEqual(get_doc_actions("Whatever"), [])

	def test_nonexistent_doctype_returns_empty(self):
		"""FormMeta raises for an unknown DocType; the helper swallows it -> []."""
		self.assertEqual(get_doc_actions("No Such DocType 9Z"), [])

	def test_never_raises_on_internal_failure(self):
		"""The 'never raises' contract holds even when a frappe call deep inside
		the body blows up (here get_installed_apps), not just FormMeta."""
		with (
			patch.object(_doc_actions, "_assembled_form_js", return_value='x.xcall("a.b.c");'),
			patch("frappe.get_installed_apps", side_effect=RuntimeError("boom")),
		):
			self.assertEqual(get_doc_actions("Whatever"), [])

	# --- get_schema integration ---

	def test_get_schema_includes_actions(self):
		result = get_schema("Sales Order", refresh=True)
		self.assertIn("actions", result)
		self.assertTrue(result["actions"], "expected a non-empty actions list")
		self.assertIn(".", result["actions"][0]["method"])

	def test_get_schema_survives_actions_error(self):
		"""Extraction blowing up must never break get_schema itself."""
		with patch(
			"jarvis.tools.get_schema.get_doc_actions",
			side_effect=RuntimeError("boom"),
		):
			result = get_schema("Customer", refresh=True)
		self.assertEqual(result["actions"], [])
