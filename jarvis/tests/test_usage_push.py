"""Daily month-to-date usage rollup push (Architecture A, fleet spec §3/§5).
admin_client is mocked; a push failure is swallowed; self-hosted / unconfigured
skip; payload cap logged."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat import usage, usage_push

USETT = "Jarvis User Settings"
MODEL_USAGE = "Jarvis User Model Usage"
USER_A = "jarvis-push-a@example.test"


def _ensure_user(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc({
			"doctype": "User", "email": email, "first_name": "Jarvis",
			"last_name": "PushTest", "enabled": 1, "send_welcome_email": 0,
			"user_type": "System User",
		}).insert(ignore_permissions=True)


def _cleanup():
	for n in frappe.get_all(MODEL_USAGE, filters={"parent": USER_A}, pluck="name"):
		frappe.delete_doc(MODEL_USAGE, n, ignore_permissions=True, force=True)
	for n in frappe.get_all(USETT, filters={"user": USER_A}, pluck="name"):
		frappe.delete_doc(USETT, n, ignore_permissions=True, force=True)


class _Base(FrappeTestCase):
	def setUp(self):
		self._orig = frappe.session.user
		frappe.set_user("Administrator")
		_ensure_user(USER_A)
		_cleanup()
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		_cleanup()
		frappe.db.commit()
		frappe.set_user(self._orig)

	def _seed(self):
		usage.get_or_create_user_settings(USER_A)
		month = usage.current_month_key()
		frappe.db.set_value(
			USETT, {"user": USER_A},
			{"usage_month": month, "month_input_tokens": 30,
			 "month_output_tokens": 20, "month_tokens": 50}, update_modified=False)
		usage.set_model_limit(USER_A, "gpt-4o", 0)
		frappe.db.set_value(
			MODEL_USAGE, {"parent": USER_A, "model": "gpt-4o", "month_key": month},
			{"month_input_tokens": 18, "month_output_tokens": 12}, update_modified=False)
		frappe.db.commit()


class TestBuildRollup(_Base):
	def test_payload_shape(self):
		self._seed()
		rollup, truncated = usage_push._build_rollup()
		self.assertFalse(truncated)
		self.assertEqual(rollup["month_key"], usage.current_month_key())
		u = {x["email"]: x for x in rollup["users"]}[USER_A]
		self.assertEqual(u["tokens_in"], 30)
		self.assertEqual(u["tokens_out"], 20)
		self.assertEqual(u["total_tokens"], 50)
		self.assertEqual(u["per_model"], {"gpt-4o": {"in": 18, "out": 12}})

	def test_cap_truncates_and_flags(self):
		self._seed()
		rollup, truncated = usage_push._build_rollup(cap=0)
		self.assertTrue(truncated)
		self.assertEqual(rollup["users"], [])


class TestPushJob(_Base):
	def test_pushes_when_configured(self):
		self._seed()
		with patch("jarvis.selfhost.is_self_hosted", return_value=False), \
			 patch.object(usage_push, "_admin_configured", return_value=True), \
			 patch("jarvis.admin_client.push_usage_rollup", return_value={"ok": True}) as push:
			usage_push.push_usage_rollup()
		push.assert_called_once()
		sent = push.call_args.args[0]
		self.assertEqual(sent["month_key"], usage.current_month_key())
		self.assertTrue(any(x["email"] == USER_A for x in sent["users"]))

	def test_self_hosted_skips(self):
		self._seed()
		with patch("jarvis.selfhost.is_self_hosted", return_value=True), \
			 patch("jarvis.admin_client.push_usage_rollup") as push:
			usage_push.push_usage_rollup()
		push.assert_not_called()

	def test_unconfigured_skips(self):
		self._seed()
		with patch("jarvis.selfhost.is_self_hosted", return_value=False), \
			 patch.object(usage_push, "_admin_configured", return_value=False), \
			 patch("jarvis.admin_client.push_usage_rollup") as push:
			usage_push.push_usage_rollup()
		push.assert_not_called()

	def test_failure_is_swallowed(self):
		self._seed()
		from jarvis.exceptions import AdminUnreachableError
		with patch("jarvis.selfhost.is_self_hosted", return_value=False), \
			 patch.object(usage_push, "_admin_configured", return_value=True), \
			 patch("jarvis.admin_client.push_usage_rollup",
				   side_effect=AdminUnreachableError("down")), \
			 patch("frappe.log_error") as logged:
			usage_push.push_usage_rollup()   # must NOT raise
		self.assertTrue(logged.called)

	def test_not_onboarded_is_quiet_skip(self):
		self._seed()
		from jarvis.exceptions import AdminAuthError
		with patch("jarvis.selfhost.is_self_hosted", return_value=False), \
			 patch.object(usage_push, "_admin_configured", return_value=True), \
			 patch("jarvis.admin_client.push_usage_rollup",
				   side_effect=AdminAuthError("not onboarded")), \
			 patch("frappe.log_error") as logged:
			usage_push.push_usage_rollup()   # must NOT raise, and not log_error
		self.assertFalse(logged.called)
