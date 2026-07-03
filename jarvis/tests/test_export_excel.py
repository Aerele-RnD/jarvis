"""Tests for export_excel's "no data" guard.

A workbook with no columns, no data rows, or only blank cells is empty in
every sense — export_excel must raise NoDataError (which the agent relays as
"No data to prepare for Excel.") rather than hand the user a blank .xlsx to
open and discover is empty.
"""
from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import NoDataError
from jarvis.tools.export_excel import export_excel


class TestExportExcelNoData(FrappeTestCase):
    def test_rejects_empty_list(self):
        with self.assertRaises(NoDataError):
            export_excel([])

    def test_rejects_list_of_empty_dicts(self):
        # No keys → no columns → a contentless workbook. Must be rejected.
        with self.assertRaises(NoDataError):
            export_excel([{}])
        with self.assertRaises(NoDataError):
            export_excel([{}, {}])

    def test_rejects_all_blank_dict_rows(self):
        # Columns exist but every value is empty → nothing to export.
        with self.assertRaises(NoDataError):
            export_excel([{"a": None, "b": None}])
        with self.assertRaises(NoDataError):
            export_excel([{"a": "", "b": "   "}])

    def test_rejects_header_only_list(self):
        with self.assertRaises(NoDataError):
            export_excel([["Name", "Qty"]])

    def test_rejects_all_blank_list_rows(self):
        with self.assertRaises(NoDataError):
            export_excel([["Name", "Qty"], ["", None]])

    def test_generates_when_there_is_real_data(self):
        # Regression guard: a row with at least one non-empty cell exports.
        with patch("frappe.utils.file_manager.save_file") as m:
            m.return_value = frappe._dict(
                file_url="/private/files/ok.xlsx", file_name="ok.xlsx", file_size=42, name="F-OK"
            )
            out = export_excel([{"a": 1, "b": None}], title="ok")
        self.assertEqual(out["file_url"], "/private/files/ok.xlsx")

    def test_generates_list_of_lists_with_data(self):
        with patch("frappe.utils.file_manager.save_file") as m:
            m.return_value = frappe._dict(
                file_url="/private/files/ll.xlsx", file_name="ll.xlsx", file_size=42, name="F-LL"
            )
            out = export_excel([["Name", "Qty"], ["Widget", 5]])
        self.assertEqual(out["file_url"], "/private/files/ll.xlsx")
