"""Tests for export_document: composed content → downloadable PDF / HTML / PNG.

save_file is mocked so we inspect the exact bytes the tool produced (real
render engines still run — get_pdf / md_to_html / pypdfium2).
"""
from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError, NoDataError
from jarvis.tools.export_document import export_document

_MD = "# Report\n\n| Metric | Value |\n|---|---|\n| Revenue | 1000 |\n\n- point one\n"


def _saved(mock):
    """(filename, bytes) export_document handed save_file."""
    return mock.call_args.args[0], mock.call_args.args[1]


class TestExportDocumentGuards(FrappeTestCase):
    def test_rejects_empty_content(self):
        with self.assertRaises(NoDataError):
            export_document("")
        with self.assertRaises(NoDataError):
            export_document("   \n  ")

    def test_rejects_unknown_format(self):
        with self.assertRaises(InvalidArgumentError):
            export_document(_MD, format="docx")


class TestExportDocumentFormats(FrappeTestCase):
    def _mock(self):
        m = patch("frappe.utils.file_manager.save_file").start()
        self.addCleanup(patch.stopall)
        m.return_value = frappe._dict(
            file_url="/private/files/doc.out", file_name="doc.out", file_size=1, name="F-DOC"
        )
        return m

    def test_pdf(self):
        m = self._mock()
        out = export_document(_MD, format="pdf", title="My Report")
        fname, payload = _saved(m)
        self.assertEqual(out["mime_type"], "application/pdf")
        self.assertTrue(fname.endswith(".pdf"))
        self.assertEqual(payload[:4], b"%PDF")

    def test_html_is_standalone_and_renders_markdown(self):
        m = self._mock()
        out = export_document(_MD, format="html", title="My Report")
        fname, payload = _saved(m)
        text = payload.decode("utf-8")
        self.assertEqual(out["mime_type"], "text/html")
        self.assertTrue(fname.endswith(".html"))
        self.assertIn("<!doctype html>", text.lower())
        self.assertIn("<title>My Report</title>", text)
        self.assertIn("<table", text)          # markdown table rendered
        self.assertIn("Revenue", text)

    def test_png(self):
        m = self._mock()
        out = export_document(_MD, format="png", title="My Report")
        fname, payload = _saved(m)
        self.assertEqual(out["mime_type"], "image/png")
        self.assertTrue(fname.endswith(".png"))
        self.assertEqual(payload[:4], b"\x89PNG")

    def test_raw_html_passthrough(self):
        m = self._mock()
        export_document("<h1>Raw</h1><p>kept verbatim</p>", format="html", content_is_html=True)
        _, payload = _saved(m)
        text = payload.decode("utf-8")
        self.assertIn("<h1>Raw</h1>", text)     # not markdown-escaped
        self.assertIn("kept verbatim", text)

    def test_default_format_is_pdf(self):
        m = self._mock()
        out = export_document(_MD, title="d")
        self.assertEqual(out["mime_type"], "application/pdf")
        self.assertEqual(_saved(m)[1][:4], b"%PDF")
