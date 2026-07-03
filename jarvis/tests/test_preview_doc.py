"""Tests for jarvis.tools.preview_doc - the dry-run create.

Uses ``Note`` as the fixture DocType (same reasoning as test_create_doc):
exists on every site, simple fields, no cross-module side effects. The
essential contract: the full insert pipeline runs, and NOTHING persists.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.preview_doc import preview_doc

NOTE_DT = "Note"


class TestPreviewDoc(FrappeTestCase):
	def test_previews_without_persisting(self):
		before = frappe.db.count(NOTE_DT)
		out = preview_doc(NOTE_DT, {"title": "jarvis-preview-test", "content": "x"})
		self.assertTrue(out["valid"])
		self.assertEqual(out["resolved"].get("title"), "jarvis-preview-test")
		self.assertEqual(frappe.db.count(NOTE_DT), before)
		self.assertFalse(frappe.db.exists(NOTE_DT, {"title": "jarvis-preview-test"}))

	def test_reports_server_filled_defaults(self):
		out = preview_doc(NOTE_DT, {"title": "jarvis-preview-defaults"})
		self.assertTrue(out["valid"])
		# Note.public defaults to 0 via the insert pipeline; the caller did
		# not pass it, so any resolved-but-not-passed field lands here.
		for f in out["server_filled"]:
			self.assertNotIn(f, ("title",))

	def test_invalid_doc_returns_valid_false_not_raise(self):
		# ToDo requires description; missing it must come back as a clean
		# {valid: false} instead of an exception.
		out = preview_doc("ToDo", {"priority": "High"})
		self.assertFalse(out["valid"])
		self.assertTrue(out["error"])

	def test_explicit_values_win(self):
		out = preview_doc("ToDo", {"description": "jarvis preview", "priority": "High"})
		self.assertTrue(out["valid"])
		self.assertEqual(out["resolved"].get("priority"), "High")
		self.assertEqual(frappe.db.count("ToDo", {"description": "jarvis preview"}), 0)

	def test_rejects_protected_fields(self):
		with self.assertRaises(InvalidArgumentError):
			preview_doc(NOTE_DT, {"title": "x", "owner": "hacker@example.com"})

	def test_rejects_empty_values(self):
		with self.assertRaises(InvalidArgumentError):
			preview_doc(NOTE_DT, {})

	def test_permission_denied(self):
		with patch("frappe.has_permission", return_value=False):
			with self.assertRaises(PermissionDeniedError):
				preview_doc(NOTE_DT, {"title": "x"})

	def test_commit_restored_after_preview(self):
		# Compare __func__: attribute access mints a fresh bound method, so
		# identity on the bound method itself always fails.
		real_func = frappe.db.commit.__func__
		preview_doc(NOTE_DT, {"title": "jarvis-preview-commit"})
		self.assertIs(getattr(frappe.db.commit, "__func__", None), real_func)
		preview_doc("ToDo", {"priority": "High"})  # invalid -> valid:false path
		self.assertIs(getattr(frappe.db.commit, "__func__", None), real_func)

	def test_preview_drops_queued_commit_callbacks(self):
		# Savepoint rollback does not clear the after_commit queue; without
		# the sandbox restore, a queued webhook would fire on the request's
		# next real commit for a rolled-back document.
		from jarvis.tools._preview_sandbox import preview_sandbox

		before = len(frappe.db.after_commit._functions)
		with preview_sandbox():
			frappe.db.after_commit.add(lambda: None)
		self.assertEqual(len(frappe.db.after_commit._functions), before)

	def test_sandbox_restores_commit_when_savepoint_fails(self):
		from jarvis.tools._preview_sandbox import preview_sandbox

		real_func = frappe.db.commit.__func__
		with patch.object(frappe.db, "savepoint", side_effect=Exception("boom")):
			with self.assertRaises(Exception):
				with preview_sandbox():
					pass  # never reached
		self.assertIs(getattr(frappe.db.commit, "__func__", None), real_func)

	def test_zero_defaults_not_reported_as_server_filled(self):
		out = preview_doc("ToDo", {"description": "jarvis preview baseline"})
		self.assertTrue(out["valid"])
		self.assertNotIn("status", out["server_filled"])
