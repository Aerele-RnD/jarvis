"""Mock-based tests for get_doc's permission-check ordering.

The end-to-end get_doc tests (test_get_doc.py) build erpnext fixtures in
setUpClass, so they can't run on an erpnext-less site. These mock-based tests
cover the permission/loading CONTRACT the perf reorder touches - existence gate,
the read-permission check on the LOADED doc object (not the name string), and
that field-level masking still runs after the check - without erpnext.
"""

from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.get_doc import _get_doc_one


class TestGetDocOnePerm(FrappeTestCase):
	def test_unknown_record_raises_invalid_argument(self):
		with patch("frappe.db.exists", return_value=False):
			with self.assertRaises(InvalidArgumentError):
				_get_doc_one("Note", "MISSING")

	def test_rejects_when_user_lacks_read_perm(self):
		with patch("frappe.db.exists", return_value=True):
			with patch("frappe.get_doc", return_value=MagicMock()):
				with patch("frappe.has_permission", return_value=False):
					with self.assertRaises(PermissionDeniedError):
						_get_doc_one("Note", "N-1")

	def test_checks_read_perm_on_loaded_doc(self):
		"""Read perm is checked on the LOADED Document object (not the name
		string), and field-level masking runs AFTER the check passes."""
		called_with = {}

		def fake_perm(doctype, ptype=None, doc=None, **_):
			called_with["doctype"] = doctype
			called_with["ptype"] = ptype
			called_with["doc"] = doc
			return True

		doc = MagicMock()
		doc.as_dict.return_value = {"name": "N-1", "doctype": "Note"}
		with patch("frappe.db.exists", return_value=True):
			with patch("frappe.get_doc", return_value=doc):
				with patch("frappe.has_permission", side_effect=fake_perm):
					result = _get_doc_one("Note", "N-1")

		self.assertEqual(called_with["doctype"], "Note")
		self.assertEqual(called_with["ptype"], "read")
		self.assertIs(called_with["doc"], doc)
		# permlevel masking still runs (after the check, before as_dict).
		doc.apply_fieldlevel_read_permissions.assert_called_once()
		self.assertEqual(result["name"], "N-1")
