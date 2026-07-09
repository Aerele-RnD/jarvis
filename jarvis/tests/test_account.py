"""Tests for jarvis.account wrappers and admin_client shims for the
/jarvis-account page. admin_client is mocked - these are unit tests of
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

# A System User who is NOT a System Manager: the realistic caller these gates
# exist to stop. A Website User is a weaker test - plenty of code paths reject
# those for unrelated reasons.
NON_SM_USER = "account-gate-staff@test.invalid"
WEBSITE_USER = "account-gate-portal@test.invalid"


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


class TestAccountEndpointsAreSystemManagerOnly(FrappeTestCase):
	"""get_account and preview_upgrade were whitelisted but ungated.

	The only thing keeping non-admins out was presentation: SettingsDialog
	hides the ACCOUNT & BILLING rail group, and the /jarvis-account desk page
	declares roles=["System Manager"]. Neither constrains a direct
	/api/method/jarvis.account.get_account call, so any authenticated user
	could read the account's plan, subscription status and validity - and
	price upgrades, one admin round-trip per request.

	start_upgrade was gated in the 2026-06-16 review; these two are its read
	siblings and were missed.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("User", NON_SM_USER):
			frappe.get_doc({
				"doctype": "User", "email": NON_SM_USER,
				"first_name": "Account Gate Staff",
				"user_type": "System User", "send_welcome_email": 0,
			}).insert(ignore_permissions=True)
		if not frappe.db.exists("User", WEBSITE_USER):
			frappe.get_doc({
				"doctype": "User", "email": WEBSITE_USER,
				"first_name": "Account Gate Portal",
				"user_type": "Website User", "send_welcome_email": 0,
			}).insert(ignore_permissions=True)
		# Site role defaults / hooks can hand out System Manager. Strip it, or
		# this whole class would silently assert nothing.
		u = frappe.get_doc("User", NON_SM_USER)
		u.remove_roles("System Manager")
		u.save(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for user in (NON_SM_USER, WEBSITE_USER):
			frappe.delete_doc("User", user, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_fixture_user_really_lacks_system_manager(self):
		"""Guard the guard: if the site hands this user System Manager, every
		rejection test below would pass for the wrong reason."""
		roles = frappe.get_roles(NON_SM_USER)
		self.assertNotIn("System Manager", roles)

	def test_get_account_rejects_non_system_manager(self):
		frappe.set_user(NON_SM_USER)
		with self.assertRaises(frappe.PermissionError):
			account.get_account()

	def test_preview_upgrade_rejects_non_system_manager(self):
		frappe.set_user(NON_SM_USER)
		with self.assertRaises(frappe.PermissionError):
			account.preview_upgrade("plan-pro")

	def test_get_account_rejects_website_user(self):
		frappe.set_user(WEBSITE_USER)
		with self.assertRaises(frappe.PermissionError):
			account.get_account()

	def test_get_account_rejects_guest(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			account.get_account()

	def test_preview_upgrade_rejects_guest(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			account.preview_upgrade("plan-pro")

	def test_rejection_happens_before_any_admin_round_trip(self):
		"""Fail closed: the gate must run before _surface() calls admin. A
		gate placed after the round-trip would still leak the payload into
		admin's logs and burn a request per unauthorised caller."""
		frappe.set_user(NON_SM_USER)
		with patch.object(admin_client, "get_account_summary") as get_summary, \
				patch.object(admin_client, "preview_upgrade") as prev:
			with self.assertRaises(frappe.PermissionError):
				account.get_account()
			with self.assertRaises(frappe.PermissionError):
				account.preview_upgrade("plan-pro")
		get_summary.assert_not_called()
		prev.assert_not_called()

	def test_system_manager_still_allowed(self):
		"""The gate must not break the legitimate caller."""
		frappe.set_user("Administrator")
		self.assertIn("System Manager", frappe.get_roles("Administrator"))
		fake = {"subscription_status": "Active", "plan": {"name": "p1"},
				"days_remaining": 12, "upgrade_plans": []}
		with patch.object(admin_client, "get_account_summary", return_value=fake):
			self.assertEqual(account.get_account(), fake)
		with patch.object(admin_client, "preview_upgrade", return_value={"prorated_inr": 1}):
			self.assertEqual(account.preview_upgrade("plan-pro"), {"prorated_inr": 1})
