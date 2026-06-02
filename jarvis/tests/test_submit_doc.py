"""Tests for jarvis.tools.submit_doc - third mutating tool.

Most of these are mock-based because submit's side effects (ledger
postings, stock moves, etc.) live in DocType ``on_submit`` hooks owned
by ERPNext, and setting up a minimal submittable real document
(Sales Invoice / Quotation / Stock Entry) requires substantial fixtures
that aren't worth the test isolation cost.

What we DO own and must verify:
- Arg-shape validation
- is_submittable gate
- docstatus state-machine gate (must be Draft)
- Permission gate (record-level submit)
- Return shape (delegates to doc.as_dict)
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.submit_doc import submit_doc


def _fake_meta(submittable: bool = True) -> MagicMock:
	m = MagicMock()
	m.is_submittable = submittable
	return m


def _fake_doc(docstatus: int = 0) -> MagicMock:
	d = MagicMock()
	d.docstatus = docstatus
	d.as_dict.return_value = {
		"name": "fake-001",
		"doctype": "Sales Invoice",
		"docstatus": 1,  # post-submit value
	}
	return d


class TestSubmitDocValidation(FrappeTestCase):
	"""Arg-shape rejections fire before any DB / meta lookups."""

	def test_rejects_empty_doctype(self):
		with self.assertRaises(InvalidArgumentError):
			submit_doc(doctype="", name="any")

	def test_rejects_empty_name(self):
		with self.assertRaises(InvalidArgumentError):
			submit_doc(doctype="Sales Invoice", name="")


class TestSubmitDocIsSubmittableGate(FrappeTestCase):
	"""Refuse non-submittable DocTypes with a clear error before
	touching the permission system."""

	def test_rejects_non_submittable_doctype(self):
		with patch("frappe.get_meta", return_value=_fake_meta(submittable=False)):
			with self.assertRaises(InvalidArgumentError) as ctx:
				submit_doc(doctype="Note", name="any")
		self.assertIn("not submittable", str(ctx.exception))


class TestSubmitDocPermissions(FrappeTestCase):
	"""Caller needs WRITE-equivalent submit perm on the record itself."""

	def test_rejects_when_user_lacks_submit_perm(self):
		with patch("frappe.get_meta", return_value=_fake_meta()):
			with patch("frappe.has_permission", return_value=False):
				with self.assertRaises(PermissionDeniedError):
					submit_doc(doctype="Sales Invoice", name="SINV-001")

	def test_checks_submit_ptype_at_record_level(self):
		"""Like update_doc, submit perm is record-scoped (doc=name passed)."""
		called_with = {}

		def fake_perm(doctype, ptype=None, doc=None, **_):
			called_with["doctype"] = doctype
			called_with["ptype"] = ptype
			called_with["doc"] = doc
			return True

		with patch("frappe.get_meta", return_value=_fake_meta()):
			with patch("frappe.has_permission", side_effect=fake_perm):
				with patch("frappe.get_doc", return_value=_fake_doc(docstatus=0)):
					submit_doc(doctype="Sales Invoice", name="SINV-001")

		self.assertEqual(called_with["doctype"], "Sales Invoice")
		self.assertEqual(called_with["ptype"], "submit")
		self.assertEqual(called_with["doc"], "SINV-001")


class TestSubmitDocStateMachine(FrappeTestCase):
	"""Only Draft (docstatus=0) docs can be submitted. Already-Submitted
	and Cancelled must be refused with state-aware error messages so the
	agent can explain why to the user."""

	def test_rejects_already_submitted(self):
		with patch("frappe.get_meta", return_value=_fake_meta()):
			with patch("frappe.has_permission", return_value=True):
				with patch("frappe.get_doc", return_value=_fake_doc(docstatus=1)):
					with self.assertRaises(InvalidArgumentError) as ctx:
						submit_doc(doctype="Sales Invoice", name="SINV-001")
		self.assertIn("already submitted", str(ctx.exception))

	def test_rejects_cancelled(self):
		with patch("frappe.get_meta", return_value=_fake_meta()):
			with patch("frappe.has_permission", return_value=True):
				with patch("frappe.get_doc", return_value=_fake_doc(docstatus=2)):
					with self.assertRaises(InvalidArgumentError) as ctx:
						submit_doc(doctype="Sales Invoice", name="SINV-001")
		self.assertIn("cancelled", str(ctx.exception).lower())


class TestSubmitDocHappyPath(FrappeTestCase):
	"""When all gates pass, doc.submit() is called and we return the
	post-submit dict."""

	def test_calls_doc_submit_and_returns_dict(self):
		doc = _fake_doc(docstatus=0)
		with patch("frappe.get_meta", return_value=_fake_meta()):
			with patch("frappe.has_permission", return_value=True):
				with patch("frappe.get_doc", return_value=doc):
					result = submit_doc(
						doctype="Sales Invoice",
						name="SINV-001",
					)
		doc.submit.assert_called_once()
		self.assertEqual(result["name"], "fake-001")
		self.assertEqual(result["docstatus"], 1)

	def test_propagates_validate_error_from_submit(self):
		"""Frappe's validate() can reject during submit (missing required
		fields, broken links, etc.). The exception propagates unchanged so
		the agent surfaces the real validation message to the user."""
		doc = _fake_doc(docstatus=0)
		doc.submit.side_effect = frappe.ValidationError("posting_date is required")
		with patch("frappe.get_meta", return_value=_fake_meta()):
			with patch("frappe.has_permission", return_value=True):
				with patch("frappe.get_doc", return_value=doc):
					with self.assertRaises(frappe.ValidationError) as ctx:
						submit_doc(doctype="Sales Invoice", name="SINV-001")
		self.assertIn("posting_date", str(ctx.exception))
