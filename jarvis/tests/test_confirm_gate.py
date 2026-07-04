"""Tests for the write-safety confirmation gate (issue #186).

The gate parks every mutating tool call in ``_GATED_WRITES`` instead of
running it: ``_run_tool`` returns ``status: pending_confirmation`` and mints a
single-use token in ``pending_confirm``. Only ``confirm_tool`` - a human
cookie-session endpoint - can then execute the stored call, owner-bound and
single-use. Non-gated writes still execute immediately.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import api
from jarvis.chat import pending_confirm
from jarvis.chat.actions_api import confirm_tool


def _spy_mint():
	"""Return (patcher-context, captured-dict). The captured dict's ``token``
	key holds the token that the gate minted, since the model-facing return
	deliberately never carries it."""
	captured = {}
	real = pending_confirm.mint

	def spy(**kwargs):
		token = real(**kwargs)
		captured["token"] = token
		captured["kwargs"] = kwargs
		return token

	return patch("jarvis.chat.pending_confirm.mint", side_effect=spy), captured


class TestGateParks(FrappeTestCase):
	def test_gated_create_with_no_token_parks(self):
		desc = "jarvis-test-gate-park-001"
		patcher, captured = _spy_mint()
		with patcher:
			r = api._run_tool("create_doc", {
				"doctype": "ToDo", "values": {"description": desc},
			})
		# Non-executing pending status, model-facing.
		self.assertTrue(r["ok"])
		self.assertEqual(r["data"]["status"], "pending_confirmation")
		self.assertEqual(r["data"]["tool"], "create_doc")
		# Nothing was written.
		self.assertFalse(frappe.db.exists("ToDo", {"description": desc}))
		# A token was minted and is retrievable from the store...
		token = captured["token"]
		self.assertIsNotNone(pending_confirm.peek(token))
		# ...but it is NEVER in the model-facing return dict.
		self.assertNotIn(token, frappe.as_json(r))

	def test_gated_create_pending_preview_is_sandboxed_shape(self):
		desc = "jarvis-test-gate-preview-002"
		patcher, _ = _spy_mint()
		with patcher:
			r = api._run_tool("create_doc", {
				"doctype": "ToDo", "values": {"description": desc},
			})
		preview = r["data"]["preview"]
		# Previewable tool -> the sandboxed _run_preview shape.
		self.assertTrue(preview["preview"])
		self.assertIn("would", preview)
		self.assertFalse(frappe.db.exists("ToDo", {"description": desc}))

	def test_send_email_parks_described_not_sent(self):
		patcher, captured = _spy_mint()
		with patch("jarvis.api.dispatch") as disp, patcher:
			r = api._run_tool("send_email", {
				"recipients": "nobody@example.com",
				"subject": "hi", "content": "body",
			})
			# The gate parks BEFORE any dispatch: send_email never fired.
			self.assertFalse(disp.called)
		self.assertEqual(r["data"]["status"], "pending_confirmation")
		preview = r["data"]["preview"]
		# send_email is not a dry run - a described intent, not a sandboxed one.
		self.assertFalse(preview["preview"])
		self.assertTrue(preview["described"])
		self.assertIn("summary", preview)
		self.assertIsNotNone(captured.get("token"))


class TestNonGatedWriteRunsImmediately(FrappeTestCase):
	def test_add_comment_executes_immediately(self):
		# add_comment is a write but NOT gated - it must run inline, no park.
		todo = frappe.get_doc({
			"doctype": "ToDo", "description": "jarvis-test-nongated-target",
		}).insert(ignore_permissions=True)
		r = api._run_tool("add_comment", {
			"doctype": "ToDo", "name": todo.name, "content": "inline note",
		})
		self.assertTrue(r["ok"])
		# Ran, did not park.
		self.assertNotEqual(
			(r.get("data") or {}).get("status"), "pending_confirmation")
		self.assertTrue(frappe.db.exists(
			"Comment", {"reference_doctype": "ToDo", "reference_name": todo.name}))


class TestConfirmTool(FrappeTestCase):
	def _park(self, tool, args):
		patcher, captured = _spy_mint()
		with patcher:
			r = api._run_tool(tool, args)
		self.assertEqual(r["data"]["status"], "pending_confirmation")
		return captured["token"]

	def test_confirm_executes_and_is_single_use(self):
		desc = "jarvis-test-confirm-create-003"
		token = self._park("create_doc", {
			"doctype": "ToDo", "values": {"description": desc},
		})
		self.assertFalse(frappe.db.exists("ToDo", {"description": desc}))

		res = confirm_tool(token)
		self.assertTrue(res["ok"])
		self.assertTrue(frappe.db.exists("ToDo", {"description": desc}))

		# Single use: the same token cannot execute again.
		again = confirm_tool(token)
		self.assertFalse(again["ok"])
		self.assertEqual(again["error"]["type"], "InvalidConfirmation")

	def test_confirm_by_wrong_owner_rejected_and_does_not_burn_token(self):
		desc = "jarvis-test-confirm-owner-004"
		# Parked as Administrator (the test session user).
		token = self._park("create_doc", {
			"doctype": "ToDo", "values": {"description": desc},
		})

		other = "jarvis-confirm-other@example.com"
		if not frappe.db.exists("User", other):
			frappe.get_doc({
				"doctype": "User", "email": other, "first_name": "Other",
				"send_welcome_email": 0,
			}).insert(ignore_permissions=True)

		original = frappe.session.user
		frappe.set_user(other)
		try:
			res = confirm_tool(token)
		finally:
			frappe.set_user(original)
		self.assertFalse(res["ok"])
		self.assertEqual(res["error"]["type"], "InvalidConfirmation")
		# Token was NOT burned by the wrong-owner attempt.
		self.assertFalse(frappe.db.exists("ToDo", {"description": desc}))

		# The real owner can still confirm.
		ok = confirm_tool(token)
		self.assertTrue(ok["ok"])
		self.assertTrue(frappe.db.exists("ToDo", {"description": desc}))

	def test_confirm_rejects_guest(self):
		token = self._park("create_doc", {
			"doctype": "ToDo", "values": {"description": "jarvis-test-guest-005"},
		})
		original = frappe.session.user
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				confirm_tool(token)
		finally:
			frappe.set_user(original)

	def test_confirm_unknown_token_is_invalid(self):
		res = confirm_tool("no-such-token-zzz")
		self.assertFalse(res["ok"])
		self.assertEqual(res["error"]["type"], "InvalidConfirmation")
