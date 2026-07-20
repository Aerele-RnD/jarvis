"""Per-model cap enforcement (fleet usage spec §7, §9). The aggregate gate is
the outer gate and is checked first; the per-model gate only fires when a
concrete model is passed. Pool "Auto" resolves to "" -> skipped (spec §2).
Fail-open on any error (G2)."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat import policy, usage, user_settings_api

USETT = "Jarvis User Settings"
MODEL_USAGE = "Jarvis User Model Usage"
USER_A = "jarvis-polmodel-a@example.test"


def _ensure_user(email: str) -> None:
	if not frappe.db.exists("User", email):
		frappe.get_doc({
			"doctype": "User", "email": email, "first_name": "Jarvis",
			"last_name": "PolModelTest", "enabled": 1, "send_welcome_email": 0,
			"user_type": "System User",
		}).insert(ignore_permissions=True)


def _cleanup() -> None:
	for name in frappe.get_all(MODEL_USAGE, filters={"parent": USER_A}, pluck="name"):
		frappe.delete_doc(MODEL_USAGE, name, ignore_permissions=True, force=True)
	for name in frappe.get_all(USETT, filters={"user": USER_A}, pluck="name"):
		frappe.delete_doc(USETT, name, ignore_permissions=True, force=True)


class _Base(FrappeTestCase):
	def setUp(self):
		self._orig_user = frappe.session.user
		frappe.set_user("Administrator")
		_ensure_user(USER_A)
		_cleanup()
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		_cleanup()
		frappe.db.commit()
		frappe.set_user(self._orig_user)

	def _set_model_usage(self, model, used_in, used_out, limit):
		usage.get_or_create_user_settings(USER_A)
		usage.set_model_limit(USER_A, model, limit)
		frappe.db.set_value(
			MODEL_USAGE,
			{"parent": USER_A, "model": model, "month_key": usage.current_month_key()},
			{"month_input_tokens": used_in, "month_output_tokens": used_out},
			update_modified=False,
		)
		frappe.db.commit()


class TestPerModelGate(_Base):
	def test_blocks_when_pinned_model_over_limit(self):
		self._set_model_usage("gpt-4o", 60, 50, 100)   # used 110 >= 100
		ok, reason = policy.validate_can_send(USER_A, model="gpt-4o")
		self.assertFalse(ok)
		self.assertEqual(reason, "usage_limit")

	def test_allows_when_pinned_model_under_limit(self):
		self._set_model_usage("gpt-4o", 20, 20, 100)   # used 40 < 100
		ok, reason = policy.validate_can_send(USER_A, model="gpt-4o")
		self.assertTrue(ok)
		self.assertIsNone(reason)

	def test_empty_model_skips_gate(self):
		# Pool "Auto" resolves to "" -> per-model gate skipped even if another
		# model is over its cap.
		self._set_model_usage("gpt-4o", 999, 999, 100)
		ok, _reason = policy.validate_can_send(USER_A, model="")
		self.assertTrue(ok)
		ok2, _ = policy.validate_can_send(USER_A, model=None)
		self.assertTrue(ok2)

	def test_zero_model_limit_is_unlimited(self):
		self._set_model_usage("gpt-4o", 999, 999, 0)
		ok, _reason = policy.validate_can_send(USER_A, model="gpt-4o")
		self.assertTrue(ok)

	def test_aggregate_gate_fires_first(self):
		# Aggregate over-limit blocks regardless of model, and even with no
		# per-model row for the passed model.
		user_settings_api.admin_set_user_limit(user=USER_A, monthly_token_limit=100)
		frappe.db.set_value(
			USETT, {"user": USER_A},
			{"usage_month": usage.current_month_key(), "month_tokens": 150},
			update_modified=False,
		)
		frappe.db.commit()
		ok, reason = policy.validate_can_send(USER_A, model="some-model-with-no-row")
		self.assertFalse(ok)
		self.assertEqual(reason, "usage_limit")

	def test_fail_open_on_db_error(self):
		self._set_model_usage("gpt-4o", 999, 0, 100)   # would block if it ran
		with patch("frappe.db.get_value", side_effect=RuntimeError("boom")):
			ok, _reason = policy.validate_can_send(USER_A, model="gpt-4o")
		# _over_model_limit swallowed the error and allowed the send (G2).
		self.assertTrue(ok)

	def test_no_row_for_model_allows(self):
		usage.get_or_create_user_settings(USER_A)
		ok, _reason = policy.validate_can_send(USER_A, model="never-used")
		self.assertTrue(ok)
