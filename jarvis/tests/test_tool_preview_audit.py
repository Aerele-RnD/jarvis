"""Tests for the api._run_tool cross-cutting additions: preview (a write
executed in a rolled-back savepoint, nothing committed) and write auditing
(every mutating tool is audited; reads are not)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import api


class TestPreview(FrappeTestCase):
    def test_preview_create_does_not_persist(self):
        desc = "jarvis-test-preview-no-persist-001"
        r = api._run_tool("create_doc", {
            "doctype": "ToDo", "values": {"description": desc}, "preview": True,
        })
        self.assertTrue(r["ok"])
        self.assertTrue(r["data"]["preview"])
        self.assertIn("would", r["data"])
        # savepoint was rolled back -> nothing committed
        self.assertFalse(frappe.db.exists("ToDo", {"description": desc}))

    def test_preview_rejected_for_non_previewable_tool(self):
        r = api._run_tool("get_list", {"doctype": "ToDo", "preview": True})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "InvalidArgumentError")


class TestWriteAudit(FrappeTestCase):
    def test_successful_write_is_audited(self):
        with patch("jarvis.api.audit.record") as rec:
            r = api._run_tool("create_doc", {
                "doctype": "ToDo", "values": {"description": "jarvis-test-audit-ok"},
            })
        self.assertTrue(r["ok"])
        self.assertTrue(rec.called)
        self.assertEqual(rec.call_args.kwargs["tool"], "create_doc")
        self.assertTrue(rec.call_args.kwargs["ok"])

    def test_failed_write_is_audited_as_error(self):
        with patch("jarvis.api.audit.record") as rec:
            r = api._run_tool("create_doc", {
                "doctype": "No Such DocType ZZZ", "values": {},
            })
        self.assertFalse(r["ok"])
        self.assertTrue(rec.called)
        self.assertFalse(rec.call_args.kwargs["ok"])

    def test_read_is_not_audited(self):
        with patch("jarvis.api.audit.record") as rec:
            api._run_tool("get_list", {"doctype": "ToDo", "limit": 1})
        self.assertFalse(rec.called)

    def test_preview_error_is_not_audited(self):
        # A failed dry-run must not pollute the audit log with a phantom write.
        with patch("jarvis.api.audit.record") as rec:
            r = api._run_tool("create_doc", {
                "doctype": "No Such DocType ZZZ", "values": {}, "preview": True,
            })
        self.assertFalse(r["ok"])
        self.assertFalse(rec.called)

    def test_preview_sandboxes_a_tool_that_commits(self):
        # The core fix: even when the dispatched tool calls frappe.db.commit()
        # internally, preview must not persist anything.
        sentinel = "jarvis-test-preview-commit-sentinel"

        def fake_dispatch(tool, args):
            frappe.get_doc({"doctype": "ToDo", "description": sentinel}).insert(
                ignore_permissions=True)
            frappe.db.commit()  # would persist + destroy a naive savepoint
            return {"ok": True}

        with patch("jarvis.api.dispatch", side_effect=fake_dispatch):
            r = api._run_tool("run_method", {"method": "x", "preview": True})
        self.assertTrue(r["ok"])
        self.assertTrue(r["data"]["preview"])
        self.assertFalse(frappe.db.exists("ToDo", {"description": sentinel}))
