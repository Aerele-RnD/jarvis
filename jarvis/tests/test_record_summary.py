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


from jarvis.chat._record_summary import same_value


class TestSameValue(FrappeTestCase):
	def test_typed_float_equals_string_request(self):
		# The phantom-diff case display comparison was introduced to fix: the DB
		# holds a typed 100.0, the model sends "100". The save changes nothing.
		df = _df(fieldtype="Currency", fieldname="rate")
		self.assertTrue(same_value(100.0, "100", df))

	def test_rounding_collision_is_NOT_a_no_op(self):
		# THE regression this rule exists for. fmt_money at precision 2 renders both
		# as "100.00"; a display compare would drop the row and the card would omit
		# a change the confirm writes.
		df = _df(fieldtype="Currency", fieldname="rate")
		self.assertFalse(same_value(100.005, "100.001", df))

	def test_float_precision_collision_is_NOT_a_no_op(self):
		df = _df(fieldtype="Float", fieldname="exchange_rate")
		self.assertFalse(same_value(83.1234, "83.1236", df))

	def test_check_string_zero_is_a_no_op(self):
		df = _df(fieldtype="Check", fieldname="disabled")
		self.assertTrue(same_value(0, "0", df))
		self.assertFalse(same_value(0, "1", df))

	def test_none_equals_empty_string(self):
		self.assertTrue(same_value(None, ""))

	def test_uncastable_value_counts_as_changed(self):
		# Never hide a row because we could not compare it. Garbage bounces pre-card
		# via _DRY_RUN_ON_PARK anyway (api.py:1033-1039); this is a safety net.
		df = _df(fieldtype="Currency", fieldname="rate")
		self.assertFalse(same_value(100.0, object(), df))

	def test_dates_compare_across_types(self):
		# A typed date from the DB vs the model's string. Comparing two identical
		# STRINGS here would pass even with Date missing from _CAST entirely.
		import datetime
		df = _df(fieldtype="Date", fieldname="due_date")
		self.assertTrue(same_value(datetime.date(2026, 7, 17), "2026-07-17", df))
		self.assertFalse(same_value(datetime.date(2026, 7, 17), "2026-07-18", df))

	def test_setting_a_date_to_today_on_an_empty_field_is_NOT_a_no_op(self):
		# getdate(None) returns TODAY (frappe/utils/data.py:125-126). A bare getdate
		# cast would compare today to today and silently drop "due today" - a routine
		# request - from a gated card.
		from frappe.utils import nowdate
		df = _df(fieldtype="Date", fieldname="due_date")
		self.assertFalse(same_value(None, nowdate(), df))
		self.assertFalse(same_value(nowdate(), None, df))

	def test_empty_dates_are_equal_to_each_other(self):
		df = _df(fieldtype="Date", fieldname="due_date")
		self.assertTrue(same_value(None, "", df))
		self.assertTrue(same_value(None, None, df))

	def test_empty_datetimes_do_not_produce_a_phantom_change(self):
		# get_datetime(None) returns now() (data.py:164-165); two calls microseconds
		# apart would render "(empty) -> (empty)" as a change.
		df = _df(fieldtype="Datetime", fieldname="starts_on")
		self.assertTrue(same_value(None, None, df))

	def test_invalid_datetime_strings_are_not_equal(self):
		# get_datetime returns None for garbage rather than raising, so two different
		# invalid strings would otherwise compare equal (None == None).
		df = _df(fieldtype="Datetime", fieldname="starts_on")
		self.assertFalse(same_value("not-a-date", "also-not-a-date", df))

	def test_no_df_falls_back_to_string_compare(self):
		self.assertTrue(same_value("abc", "abc"))
		self.assertFalse(same_value("abc", "abd"))


from jarvis.chat._record_summary import _MAX_FLOOR, pick_fields


class TestPickFields(FrappeTestCase):
	def test_floor_includes_title_and_list_view_fields(self):
		fields = pick_fields(frappe.get_meta("ToDo"))
		self.assertIn("description", fields)
		self.assertNotIn("name", fields)  # name is the row header, not a row

	def test_floor_is_capped_and_deduped(self):
		fields = pick_fields(frappe.get_meta("User"))
		self.assertLessEqual(len(fields), _MAX_FLOOR)
		self.assertEqual(len(fields), len(set(fields)))

	def test_floor_excludes_child_tables(self):
		meta = frappe.get_meta("User")
		for f in pick_fields(meta):
			self.assertNotIn(meta.get_field(f).fieldtype, ("Table", "Table MultiSelect"))

	def test_long_text_fieldtypes_sort_last(self):
		# data_fieldtypes includes Text Editor / Markdown Editor / Code, so a 10k
		# body field can be in_list_view and would otherwise take a floor slot from
		# the customer and the total.
		meta = frappe.get_meta("ToDo")
		fields = pick_fields(meta)
		types = [meta.get_field(f).fieldtype for f in fields]
		long_idx = [i for i, t in enumerate(types) if t in ("Text Editor", "Markdown Editor", "Code")]
		short_idx = [i for i, t in enumerate(types) if t not in ("Text Editor", "Markdown Editor", "Code")]
		if long_idx and short_idx:
			self.assertGreater(min(long_idx), max(short_idx))

	def test_no_meta_returns_empty(self):
		self.assertEqual(pick_fields(None), [])
