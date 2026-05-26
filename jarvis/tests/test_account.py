"""Tests for jarvis.account wrappers and admin_client shims for the
/jarvis-account page. admin_client is mocked — these are unit tests of
the customer-side glue, not of the admin endpoints themselves."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import account, admin_client
from jarvis.exceptions import AdminValidationError


_SNAPSHOTTED_FIELDS = (
	"jarvis_admin_url", "jarvis_admin_api_key", "jarvis_admin_api_secret",
	"agent_url", "agent_token",
)


def _snapshot_settings() -> dict:
	s = frappe.get_single("Jarvis Settings")
	snap = {}
	for f in _SNAPSHOTTED_FIELDS:
		v = (s.get_password(f, raise_exception=False)
			 if f.endswith(("_key", "_secret", "_token")) else s.get(f))
		snap[f] = v or ""
	return snap


def _restore_settings(snap: dict) -> None:
	s = frappe.get_single("Jarvis Settings")
	for f, v in snap.items():
		s.db_set(f, v)
	frappe.db.commit()


class TestIsOnboarded(FrappeTestCase):
	def setUp(self):
		self._snap = _snapshot_settings()

	def tearDown(self):
		_restore_settings(self._snap)

	def test_true_when_admin_key_set(self):
		s = frappe.get_single("Jarvis Settings")
		s.db_set("jarvis_admin_api_key", "ak-abc")
		s.db_set("jarvis_admin_api_secret", "as-abc")
		frappe.db.commit()
		self.assertEqual(account.is_onboarded(), {"onboarded": True})

	def test_false_when_admin_key_blank(self):
		s = frappe.get_single("Jarvis Settings")
		s.db_set("jarvis_admin_api_key", "")
		s.db_set("jarvis_admin_api_secret", "")
		frappe.db.commit()
		self.assertEqual(account.is_onboarded(), {"onboarded": False})


class TestAccountWrappers(FrappeTestCase):
	def test_get_account_returns_admin_payload(self):
		fake = {"subscription_status": "Active", "plan": {"name": "p1"},
				"days_remaining": 12, "upgrade_plans": []}
		with patch.object(admin_client, "get_account_summary", return_value=fake) as m:
			out = account.get_account()
		m.assert_called_once_with()
		self.assertEqual(out, fake)

	def test_preview_upgrade_passes_target_plan_through(self):
		fake = {"prorated_inr": 500, "diff_per_day": 50.0,
				"days_remaining": 10, "total_period_days": 30}
		with patch.object(admin_client, "preview_upgrade", return_value=fake) as m:
			out = account.preview_upgrade("plan-pro")
		m.assert_called_once_with("plan-pro")
		self.assertEqual(out, fake)

	def test_start_upgrade_passes_target_plan_through(self):
		fake = {"razorpay_order_id": "order_X", "razorpay_key_id": "k",
				"amount_inr": 500, "target_plan": "plan-pro"}
		with patch.object(admin_client, "start_upgrade", return_value=fake) as m:
			out = account.start_upgrade("plan-pro")
		m.assert_called_once_with("plan-pro")
		self.assertEqual(out, fake)

	def test_get_account_surfaces_admin_validation_error_as_frappe_throw(self):
		"""_surface() converts AdminValidationError to frappe.throw so the
		page sees Frappe's standard red toast text instead of a traceback."""
		with patch.object(admin_client, "get_account_summary",
						  side_effect=AdminValidationError("plan disabled")):
			with self.assertRaises(frappe.ValidationError) as cm:
				account.get_account()
		self.assertIn("plan disabled", str(cm.exception))

	def test_preview_upgrade_surfaces_validation_error(self):
		with patch.object(admin_client, "preview_upgrade",
						  side_effect=AdminValidationError("downgrade not supported")):
			with self.assertRaises(frappe.ValidationError) as cm:
				account.preview_upgrade("plan-cheap")
		self.assertIn("downgrade not supported", str(cm.exception))
