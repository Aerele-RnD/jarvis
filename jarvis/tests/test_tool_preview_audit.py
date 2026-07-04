"""Tests for the api._run_tool cross-cutting additions: preview (a write
executed in a rolled-back savepoint, nothing committed) and write auditing
(every mutating tool is audited; reads are not)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import api


# These exercise the model-facing preview BRANCH in _run_tool. Every real
# _PREVIEWABLE tool is also in _GATED_WRITES, and gated tools now bypass the
# preview branch entirely (they park for confirmation - see Fix 1 in
# test_confirm_gate). So to keep testing the preview-branch mechanics we patch
# _GATED_WRITES to empty, which stands in for a hypothetical non-gated
# previewable tool - the only case that still reaches this branch.
class TestPreview(FrappeTestCase):
    def test_preview_create_does_not_persist(self):
        desc = "jarvis-test-preview-no-persist-001"
        with patch.object(api, "_GATED_WRITES", frozenset()):
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
    # NOTE: these exercise the inline write-audit seam with a NON-gated write
    # (add_comment). The gated writes in _GATED_WRITES (create_doc etc.) no
    # longer execute inline - they park for confirmation and are audited only
    # when confirm_tool runs them; that path is covered in test_confirm_gate.
    def test_successful_write_is_audited(self):
        todo = frappe.get_doc({
            "doctype": "ToDo", "description": "jarvis-test-audit-target",
        }).insert(ignore_permissions=True)
        with patch("jarvis.api.audit.record") as rec:
            r = api._run_tool("add_comment", {
                "doctype": "ToDo", "name": todo.name, "content": "audited note",
            })
        self.assertTrue(r["ok"])
        self.assertTrue(rec.called)
        self.assertEqual(rec.call_args.kwargs["tool"], "add_comment")
        self.assertTrue(rec.call_args.kwargs["ok"])

    def test_failed_write_is_audited_as_error(self):
        with patch("jarvis.api.audit.record") as rec:
            r = api._run_tool("add_comment", {
                "doctype": "ToDo", "name": "no-such-todo-zzz", "content": "x",
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
        with patch("jarvis.api.audit.record") as rec, \
                patch.object(api, "_GATED_WRITES", frozenset()):
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

        with patch("jarvis.api.dispatch", side_effect=fake_dispatch), \
                patch.object(api, "_GATED_WRITES", frozenset()):
            r = api._run_tool("run_method", {"method": "x", "preview": True})
        self.assertTrue(r["ok"])
        self.assertTrue(r["data"]["preview"])
        self.assertFalse(frappe.db.exists("ToDo", {"description": sentinel}))
