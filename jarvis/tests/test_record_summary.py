"""Tests for jarvis.chat._record_summary - field selection, permission-checked doc
reads, Frappe-correct formatting, and cast-compare no-op detection.

These back every confirmation card. A bug here is a card that misdescribes a write.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat._record_summary import _MAX_VAL, fmt


def _df(**kwargs):
	"""A stand-in DocField. format_value only reads attributes, so a _dict is enough."""
	return frappe._dict(kwargs)


class TestFmt(FrappeTestCase):
	def test_check_uses_cint_so_string_zero_is_no(self):
		# format_value has no Check branch (formatters.py:146) and returns 1/0. A
		# model sends "0" as a string; naive truthiness would render "Yes" and
		# fabricate a phantom change on a gated card.
		df = _df(fieldtype="Check", fieldname="disabled")
		self.assertEqual(fmt(0, df), "No")
		self.assertEqual(fmt("0", df), "No")
		self.assertEqual(fmt(1, df), "Yes")
		self.assertEqual(fmt("1", df), "Yes")

	def test_html_fieldtypes_bypass_format_value(self):
		# format_value turns newlines into <br> for Text; the cards escape every
		# value, so that would render as literal tags.
		df = _df(fieldtype="Small Text", fieldname="notes")
		self.assertEqual(fmt("a\nb", df), "a\nb")

	def test_percent_formats(self):
		df = _df(fieldtype="Percent", fieldname="pct")
		self.assertEqual(fmt(12.5, df), "12.5%")

	def test_list_renders_row_count(self):
		self.assertEqual(fmt([1, 2, 3]), "3 rows")
		self.assertEqual(fmt([1]), "1 row")

	def test_none_renders_empty(self):
		self.assertEqual(fmt(None), "")

	def test_truncates_at_limit(self):
		out = fmt("x" * 500)
		self.assertEqual(len(out), _MAX_VAL)
		self.assertTrue(out.endswith("…"))

	def test_limit_is_overridable_for_long_form_bodies(self):
		out = fmt("x" * 500, limit=8000)
		self.assertEqual(out, "x" * 500)

	def test_raising_field_falls_back_to_str(self):
		# format_value can raise (get_field_currency attribute access, meta.py:886).
		# One odd field must never blank a whole card. Assert the VALUE, not the type:
		# fmt always returns a str, so assertIsInstance would pass even with the
		# except branch deleted.
		df = _df(fieldtype="Currency", fieldname="amount", options="bad_link_field")
		self.assertEqual(fmt(5, df, doc=object()), "5")
