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


class TestGatedToolRefusesModelPreview(FrappeTestCase):
	"""Fix 1: a gated write called with ``preview=True`` must NOT take the
	model-facing preview branch (a dry-run that still fires inline non-DB hook
	side effects). It must fall through to the gate and PARK, which builds its
	own preview. The park's status discriminates it from the old preview-branch
	return (which had ``would`` at the top of ``data`` and no ``status``)."""

	def test_gated_create_with_preview_true_parks_not_dry_run(self):
		desc = "jarvis-test-gate-preview-bypass-010"
		patcher, captured = _spy_mint()
		with patcher:
			r = api._run_tool("create_doc", {
				"doctype": "ToDo", "values": {"description": desc},
				"preview": True,
			})
		# Parked (gate), not the preview-branch dry-run shape.
		self.assertTrue(r["ok"])
		self.assertEqual(r["data"]["status"], "pending_confirmation")
		# The preview branch would have put ``would`` at the top of ``data``;
		# the gate nests its preview under data["preview"] instead.
		self.assertNotIn("would", r["data"])
		self.assertIn("preview", r["data"])
		# A token was minted (the gate ran), and nothing was written.
		self.assertIsNotNone(captured.get("token"))
		self.assertFalse(frappe.db.exists("ToDo", {"description": desc}))

	def test_gated_run_method_with_preview_true_does_not_execute_on_model_path(self):
		# run_method is gated + previewable. Even with preview=True the model's
		# call must park - the real (non-sandboxed) target is never dispatched
		# outside the gate on this call. dispatch is patched, so if the model
		# reached execution it would be visible; the gate parks first and only
		# the sandboxed preview builder may touch dispatch.
		patcher, captured = _spy_mint()
		with patcher:
			r = api._run_tool("run_method", {
				"method": "frappe.ping", "preview": True,
			})
		self.assertTrue(r["ok"])
		self.assertEqual(r["data"]["status"], "pending_confirmation")
		self.assertNotIn("would", r["data"])
		self.assertIsNotNone(captured.get("token"))


class TestRunMethodParkDoesNotSandboxExecute(FrappeTestCase):
	"""Fix 2: run_method is _PREVIEWABLE, but parking one must NOT sandbox-
	execute the target method to build its preview - the sandbox only rolls
	back DB writes, so a method's inline non-DB side effects (HTTP/email) would
	fire unconfirmed and its result would leak to the model. run_method parks
	with a described-intent preview (never executed at park time); the real
	call runs exactly once, only on confirm."""

	def test_run_method_parks_described_and_not_executed_at_park(self):
		patcher, captured = _spy_mint()
		with patch("jarvis.api.dispatch") as disp, patcher:
			r = api._run_tool("run_method", {"method": "frappe.ping"})
			# No sandbox execution at park time: dispatch is never touched.
			self.assertFalse(disp.called)
		self.assertEqual(r["data"]["status"], "pending_confirmation")
		preview = r["data"]["preview"]
		# Described intent, explicitly NOT a dry run (no sandboxed "would").
		self.assertFalse(preview["preview"])
		self.assertTrue(preview["described"])
		self.assertIn("summary", preview)
		self.assertNotIn("would", preview)
		self.assertIsNotNone(captured.get("token"))

	def test_confirm_executes_run_method_exactly_once(self):
		patcher, captured = _spy_mint()
		with patcher:
			r = api._run_tool("run_method", {"method": "frappe.ping"})
		self.assertEqual(r["data"]["status"], "pending_confirmation")
		token = captured["token"]
		# The method runs for the first and only time on confirm.
		with patch("jarvis.api.dispatch", return_value={"message": "pong"}) as disp:
			res = confirm_tool(token)
		self.assertTrue(res["ok"])
		self.assertEqual(disp.call_count, 1)
		self.assertEqual(disp.call_args.args[0], "run_method")


class TestConfirmSelfHostOwnerBinding(FrappeTestCase):
	"""Fix 2: in self-hosted mode the gate mints the token under the self-host
	tool user (that is the session user inside call_tool), but the human confirms
	from a DIFFERENT browser session. ``confirm_tool`` must consume under the
	same owner the gate minted under - resolved by deployment mode - or every
	self-host confirm fails closed-but-broken. Managed mode is unchanged."""

	_TOOL_USER = "jarvis-selfhost-tool@example.com"

	def _ensure_user(self, email):
		if not frappe.db.exists("User", email):
			frappe.get_doc({
				"doctype": "User", "email": email, "first_name": "SelfHost",
				"send_welcome_email": 0,
			}).insert(ignore_permissions=True)
		return email

	def test_selfhost_confirm_consumes_under_tool_user_not_session(self):
		desc = "jarvis-test-selfhost-confirm-020"
		tool_user = self._ensure_user(self._TOOL_USER)
		# Park directly under the tool user, exactly as the gate does in
		# self-host (owner == frappe.session.user == the self-host tool user).
		token = pending_confirm.mint(
			conversation="", owner=tool_user, tool="create_doc",
			args={"doctype": "ToDo", "values": {"description": desc}}, run_id="")
		self.assertFalse(frappe.db.exists("ToDo", {"description": desc}))

		# The confirm arrives on the human browser session (Administrator here -
		# a DIFFERENT user than the token owner). Self-host owner binding still
		# resolves to the tool user, so it consumes + executes.
		with patch("jarvis.selfhost.is_self_hosted", return_value=True), \
				patch("jarvis.api._selfhost_tool_user", return_value=tool_user):
			res = confirm_tool(token)
		self.assertTrue(res["ok"])
		self.assertTrue(frappe.db.exists("ToDo", {"description": desc}))

	def test_selfhost_confirm_still_rejects_guest(self):
		tool_user = self._ensure_user(self._TOOL_USER)
		token = pending_confirm.mint(
			conversation="", owner=tool_user, tool="create_doc",
			args={"doctype": "ToDo", "values": {"description": "x-021"}},
			run_id="")
		original = frappe.session.user
		frappe.set_user("Guest")
		try:
			with patch("jarvis.selfhost.is_self_hosted", return_value=True), \
					patch("jarvis.api._selfhost_tool_user", return_value=tool_user), \
					self.assertRaises(frappe.PermissionError):
				confirm_tool(token)
		finally:
			frappe.set_user(original)
		# Guest was rejected before consume, so the token is NOT burned.
		self.assertFalse(frappe.db.exists("ToDo", {"description": "x-021"}))

	def test_managed_confirm_owner_is_session_user_unchanged(self):
		# Managed mode: owner must equal the confirming session user.
		desc_ok = "jarvis-test-managed-owner-ok-022"
		desc_bad = "jarvis-test-managed-owner-bad-022"
		session_user = frappe.session.user  # Administrator in tests
		with patch("jarvis.selfhost.is_self_hosted", return_value=False):
			# Token minted under the session user -> confirms + executes.
			ok_token = pending_confirm.mint(
				conversation="", owner=session_user, tool="create_doc",
				args={"doctype": "ToDo", "values": {"description": desc_ok}},
				run_id="")
			res = confirm_tool(ok_token)
			self.assertTrue(res["ok"])
			self.assertTrue(frappe.db.exists("ToDo", {"description": desc_ok}))

			# Token minted under a DIFFERENT owner -> rejected, not executed.
			bad_token = pending_confirm.mint(
				conversation="", owner="someone-else@example.com",
				tool="create_doc",
				args={"doctype": "ToDo", "values": {"description": desc_bad}},
				run_id="")
			res = confirm_tool(bad_token)
			self.assertFalse(res["ok"])
			self.assertEqual(res["error"]["type"], "InvalidConfirmation")
			self.assertFalse(frappe.db.exists("ToDo", {"description": desc_bad}))
