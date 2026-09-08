"""Mock-based tests for get_itemised_tax_breakup's permission-check ordering.

The tool wraps an ERPNext helper, so its integration behaviour is covered by
test_tier2a_erpnext_reads (which needs erpnext). These tests verify only the
permission/loading CONTRACT the perf reorder touches - existence gate, the
read-permission check runs on the LOADED doc object (not the name string), and
denial - all without an erpnext-bearing site.
"""

from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.get_itemised_tax_breakup import get_itemised_tax_breakup

DT = "Sales Invoice"
NAME = "SINV-001"


class TestGetItemisedTaxBreakupPerm(FrappeTestCase):
	def test_unknown_record_raises_invalid_argument(self):
		with patch("frappe.db.exists", return_value=False):
			with self.assertRaises(InvalidArgumentError):
				get_itemised_tax_breakup(doctype=DT, name=NAME)

	def test_rejects_when_user_lacks_read_perm(self):
		# get_doc is loaded before the perm check; mock it so no real (erpnext)
		# controller load is needed.
		with patch("frappe.db.exists", return_value=True):
			with patch("frappe.get_doc", return_value=MagicMock()):
				with patch("frappe.has_permission", return_value=False):
					with self.assertRaises(PermissionDeniedError):
						get_itemised_tax_breakup(doctype=DT, name=NAME)

	def test_checks_read_perm_on_loaded_doc(self):
		"""Read perm is checked on the LOADED Document object (not the name
		string), after get_doc and before the erpnext tax computation."""
		called_with = {}

		def fake_perm(doctype, ptype=None, doc=None, **_):
			called_with["doctype"] = doctype
			called_with["ptype"] = ptype
			called_with["doc"] = doc
			return True

		doc = MagicMock()
		with patch("frappe.db.exists", return_value=True):
			with patch("frappe.get_doc", return_value=doc):
				with patch("frappe.has_permission", side_effect=fake_perm):
					with patch("jarvis.compat.itemised_tax", return_value={"ITEM-1": {}}) as itax:
						result = get_itemised_tax_breakup(doctype=DT, name=NAME)

		self.assertEqual(called_with["doctype"], DT)
		self.assertEqual(called_with["ptype"], "read")
		self.assertIs(called_with["doc"], doc)
		# The loaded doc (not the name) is handed to the erpnext helper.
		itax.assert_called_once_with(doc, with_tax_account=True)
		self.assertEqual(result["itemised_tax"], {"ITEM-1": {}})
