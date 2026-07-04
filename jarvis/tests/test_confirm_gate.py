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
	"""Fix #14: a gated write called with ``preview=True`` must NOT take the
	model-facing preview branch (a dry-run that still fires inline non-DB hook
	side effects) AND must NOT silently park. It returns an informative
	InvalidArgumentError so a transition-window model that used preview to
	dry-run gets a legible signal instead of a premature pending card. It does
	not park (no token minted) and does not execute."""

	def test_gated_create_with_preview_true_returns_error_not_park(self):
		desc = "jarvis-test-gate-preview-bypass-010"
		patcher, captured = _spy_mint()
		with patcher:
			r = api._run_tool("create_doc", {
				"doctype": "ToDo", "values": {"description": desc},
				"preview": True,
			})
		# Informative error, NOT the park shape and NOT the dry-run shape.
		self.assertFalse(r["ok"])
		self.assertEqual(r["error"]["code"], "InvalidArgumentError")
		self.assertIn("preview is not needed", r["error"]["message"])
		# Did NOT park: no token minted, nothing written.
		self.assertIsNone(captured.get("token"))
		self.assertFalse(frappe.db.exists("ToDo", {"description": desc}))

	def test_gated_run_method_with_preview_true_returns_error_and_does_not_execute(self):
		# run_method is gated + previewable. With preview=True it must return the
		# informative error without parking or dispatching. dispatch is patched,
		# so any execution would be visible.
		patcher, captured = _spy_mint()
		with patch("jarvis.api.dispatch") as disp, patcher:
			r = api._run_tool("run_method", {
				"method": "frappe.ping", "preview": True,
			})
			self.assertFalse(disp.called)
		self.assertFalse(r["ok"])
		self.assertEqual(r["error"]["code"], "InvalidArgumentError")
		self.assertIsNone(captured.get("token"))


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
	"""#1/#5/#6: in self-host the gate binds the token to the CONVERSATION
	OWNER (the operator whose browser is subscribed), NOT the restricted tool
	user the model path runs as. The operator confirms from their own browser
	session (== the owner), and the confirmed write EXECUTES as the stored
	``exec_user`` (the tool user) so a confirm never exceeds the model path's
	scope. Managed mode is unchanged (owner == exec_user)."""

	_TOOL_USER = "jarvis-selfhost-tool@example.com"

	def _ensure_user(self, email):
		if not frappe.db.exists("User", email):
			frappe.get_doc({
				"doctype": "User", "email": email, "first_name": "SelfHost",
				"send_welcome_email": 0,
			}).insert(ignore_permissions=True)
		return email

	def test_selfhost_confirm_by_owner_executes_as_exec_user(self):
		# The gate binds owner=operator (the browser session, Administrator here)
		# and exec_user=tool_user. The operator confirms from their own session;
		# the write dispatches under the tool user, not the browser session (#6).
		tool_user = self._ensure_user(self._TOOL_USER)
		operator = frappe.session.user  # browser session == conversation owner
		token = pending_confirm.mint(
			conversation="", owner=operator, exec_user=tool_user, tool="create_doc",
			args={"doctype": "ToDo", "values": {"description": "sh-020"}}, run_id="")

		acting = {}

		def _spy_dispatch(tool, args):
			acting["user"] = frappe.session.user
			return {"name": "TODO-FAKE"}

		with patch("jarvis.selfhost.is_self_hosted", return_value=True), \
				patch("jarvis.api._selfhost_tool_user", return_value=tool_user), \
				patch("jarvis.api.dispatch", side_effect=_spy_dispatch):
			res = confirm_tool(token)
		self.assertTrue(res["ok"])
		# #6: executed under the scoped tool user, not the browser-session owner.
		self.assertEqual(acting["user"], tool_user)
		# The confirming session user is restored after dispatch.
		self.assertEqual(frappe.session.user, operator)
		# Single use.
		again = confirm_tool(token)
		self.assertFalse(again["ok"])

	def test_selfhost_confirm_still_rejects_guest(self):
		tool_user = self._ensure_user(self._TOOL_USER)
		operator = frappe.session.user
		token = pending_confirm.mint(
			conversation="", owner=operator, exec_user=tool_user, tool="create_doc",
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
		self.assertIsNotNone(pending_confirm.peek(token))

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


CONV = "Jarvis Conversation"


def _make_conv(owner: str) -> str:
	"""Create a Jarvis Conversation owned by ``owner`` and return its name."""
	orig = frappe.session.user
	frappe.set_user(owner)
	try:
		doc = frappe.get_doc({"doctype": CONV, "title": "confirm-gate test"})
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return doc.name
	finally:
		frappe.set_user(orig)


class TestConfirmedWriteReceipt(FrappeTestCase):
	"""#7: a confirmed write must leave a transcript receipt (a role=tool Jarvis
	Chat Message) in the conversation, the same way the inline model-write path
	does, so a confirmed delete/submit/email shows on reload."""

	def tearDown(self):
		for name in frappe.get_all(
			CONV, filters={"title": "confirm-gate test"}, pluck="name"):
			frappe.delete_doc(CONV, name, force=True, ignore_permissions=True)
		frappe.db.commit()

	def test_confirmed_create_persists_tool_receipt(self):
		from jarvis.chat.api import get_conversation

		owner = frappe.session.user  # Administrator
		conv = _make_conv(owner)
		desc = "jarvis-test-confirm-receipt-040"
		token = pending_confirm.mint(
			conversation=conv, owner=owner, exec_user=owner, tool="create_doc",
			args={"doctype": "ToDo", "values": {"description": desc}}, run_id="")

		res = confirm_tool(token)
		self.assertTrue(res["ok"])
		self.assertTrue(frappe.db.exists("ToDo", {"description": desc}))

		# The receipt is visible via get_conversation as a role=tool message.
		msgs = get_conversation(conv)["messages"]
		tool_msgs = [m for m in msgs if m["role"] == "tool"
					 and m["tool_name"] == "create_doc"]
		self.assertEqual(len(tool_msgs), 1)
		self.assertEqual(tool_msgs[0]["tool_status"], "completed")


class TestRealConversationGuard(FrappeTestCase):
	"""#11: confirm_tool accepts the conversation the click came from and passes
	it into consume as a REAL check. A mismatched conversation is rejected; the
	matching one succeeds; when omitted, owner + single-use still guard."""

	def test_mismatched_conversation_rejected_and_token_not_burned(self):
		owner = frappe.session.user
		desc = "jarvis-test-confirm-convguard-050"
		token = pending_confirm.mint(
			conversation="conv-real", owner=owner, exec_user=owner, tool="create_doc",
			args={"doctype": "ToDo", "values": {"description": desc}}, run_id="")
		# Wrong conversation -> rejected, nothing executes, token still lives.
		res = confirm_tool(token, conversation="conv-other")
		self.assertFalse(res["ok"])
		self.assertEqual(res["error"]["type"], "InvalidConfirmation")
		self.assertFalse(frappe.db.exists("ToDo", {"description": desc}))
		self.assertIsNotNone(pending_confirm.peek(token))
		# Matching conversation -> succeeds.
		res = confirm_tool(token, conversation="conv-real")
		self.assertTrue(res["ok"])
		self.assertTrue(frappe.db.exists("ToDo", {"description": desc}))

	def test_no_conversation_arg_falls_back_to_owner_single_use(self):
		owner = frappe.session.user
		desc = "jarvis-test-confirm-convguard-051"
		token = pending_confirm.mint(
			conversation="conv-real", owner=owner, exec_user=owner, tool="create_doc",
			args={"doctype": "ToDo", "values": {"description": desc}}, run_id="")
		# No conversation passed: owner + single-use still guard, it executes.
		res = confirm_tool(token)
		self.assertTrue(res["ok"])
		self.assertTrue(frappe.db.exists("ToDo", {"description": desc}))
		# Single use.
		self.assertFalse(confirm_tool(token)["ok"])


class TestListPendingConfirmations(FrappeTestCase):
	"""The resync endpoint returns only the caller's OWN live parked tokens,
	owner-scoped, conversation-filterable, excluding expired/consumed."""

	_OWNER = "jarvis-listpending-owner@example.com"
	_OTHER = "jarvis-listpending-other@example.com"

	def _ensure(self, email):
		if not frappe.db.exists("User", email):
			frappe.get_doc({
				"doctype": "User", "email": email, "first_name": "LP",
				"send_welcome_email": 0,
			}).insert(ignore_permissions=True)
		return email

	def setUp(self):
		# Dedicated owner + a cleared Redis index, so token-count assertions are
		# isolated from the many tokens other tests park under Administrator.
		self._ensure(self._OWNER)
		self._ensure(self._OTHER)
		for o in (self._OWNER, self._OTHER):
			frappe.cache().delete_value(pending_confirm._OWNER_PREFIX + o)
		self._orig = frappe.session.user
		frappe.set_user(self._OWNER)

	def tearDown(self):
		frappe.set_user(self._orig)

	def _ensure_other(self):
		return self._OTHER

	def test_returns_only_own_tokens_filtered_by_conversation(self):
		from jarvis.chat.actions_api import list_pending_confirmations

		owner = frappe.session.user
		other = self._ensure_other()
		t1 = pending_confirm.mint(
			conversation="lp-conv-1", owner=owner, exec_user=owner,
			tool="create_doc",
			args={"doctype": "ToDo", "values": {"description": "lp-1"}}, run_id="r1")
		pending_confirm.mint(
			conversation="lp-conv-2", owner=owner, exec_user=owner,
			tool="delete_doc", args={"doctype": "ToDo", "name": "X"}, run_id="r2")
		# Another user's token must never surface.
		pending_confirm.mint(
			conversation="lp-conv-1", owner=other, exec_user=other,
			tool="create_doc",
			args={"doctype": "ToDo", "values": {"description": "lp-other"}}, run_id="")

		res = list_pending_confirmations()
		self.assertTrue(res["ok"])
		items = res["data"]["pending"]
		# Only the caller's two tokens, each carrying the action:pending shape.
		self.assertEqual(len(items), 2)
		for it in items:
			self.assertIn("token", it)
			self.assertIn("preview", it)
			self.assertIn("summary", it)
			self.assertIn("conversation", it)
			self.assertIn("run_id", it)

		# Filtered by conversation.
		one = list_pending_confirmations(conversation="lp-conv-1")["data"]["pending"]
		self.assertEqual([i["token"] for i in one], [t1])

	def test_excludes_consumed(self):
		from jarvis.chat.actions_api import list_pending_confirmations

		owner = frappe.session.user
		t = pending_confirm.mint(
			conversation="lp-conv-3", owner=owner, exec_user=owner,
			tool="create_doc",
			args={"doctype": "ToDo", "values": {"description": "lp-3"}}, run_id="")
		pending_confirm.consume(t, owner=owner, conversation="lp-conv-3")
		tokens = [i["token"]
				  for i in list_pending_confirmations()["data"]["pending"]]
		self.assertNotIn(t, tokens)

	def test_rejects_guest(self):
		from jarvis.chat.actions_api import list_pending_confirmations

		original = frappe.session.user
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				list_pending_confirmations()
		finally:
			frappe.set_user(original)
