"""Tests for jarvis.dev — the customer-side reset_onboarding endpoint."""

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.dev import is_dev_mode_active, reset_onboarding, _RESET_CLEAR_FIELDS


SETTINGS = "Jarvis Settings"


_PASSWORD_FIELDS = {
	"jarvis_admin_api_key", "jarvis_admin_api_secret", "agent_token",
	"chat_device_private_key", "chat_device_token", "llm_api_key",
}


def _read(s, field):
	"""Read a Jarvis Settings field, password-safe."""
	if field in _PASSWORD_FIELDS:
		return (s.get_password(field, raise_exception=False) or "")
	return (s.get(field) or "")


def _snapshot():
	"""Snapshot every reset-affected field so tests run against a real site
	(not test_site) don't trash the operator's actual onboarded state."""
	s = frappe.get_single(SETTINGS)
	snap = {f: _read(s, f) for f in (*_RESET_CLEAR_FIELDS, "llm_provider")}
	return snap


def _restore(snap):
	s = frappe.get_single(SETTINGS)
	for f, v in snap.items():
		s.db_set(f, v)
	frappe.db.commit()


def _seed_onboarded_state():
	"""Plant non-empty values in every field reset_onboarding will clear."""
	s = frappe.get_single(SETTINGS)
	for f in _RESET_CLEAR_FIELDS:
		s.db_set(f, f"seed-{f}")
	s.db_set("llm_provider", "OpenAI")
	frappe.db.commit()


class _GuardSwap:
	"""Force developer_mode on for the duration of a test."""
	def __enter__(self):
		self._prior = frappe.conf.get("developer_mode") or 0
		frappe.conf.developer_mode = 1
		return self

	def __exit__(self, *exc):
		frappe.conf.developer_mode = self._prior


class TestResetOnboarding(FrappeTestCase):
	def setUp(self):
		self._snap = _snapshot()
		_seed_onboarded_state()

	def tearDown(self):
		_restore(self._snap)

	def test_clears_all_targeted_fields(self):
		with _GuardSwap():
			out = reset_onboarding()
		self.assertTrue(out["ok"])
		s = frappe.get_single(SETTINGS)
		for f in _RESET_CLEAR_FIELDS:
			self.assertEqual(_read(s, f), "", f"{f} should be blank after reset")
		# llm_provider resets to default rather than going blank (Select).
		self.assertEqual(s.llm_provider, "Anthropic")

	def test_preserves_unrelated_settings(self):
		s = frappe.get_single(SETTINGS)
		s.db_set("jarvis_admin_url", "https://admin.example.com")
		s.db_set("token_budget_monthly", 50000)
		s.db_set("llm_temperature", 0.4)
		frappe.db.commit()
		with _GuardSwap():
			reset_onboarding()
		s = frappe.get_single(SETTINGS)
		self.assertEqual(s.jarvis_admin_url, "https://admin.example.com")
		self.assertEqual(int(s.token_budget_monthly), 50000)
		self.assertAlmostEqual(float(s.llm_temperature), 0.4)


class TestResetOnboardingGuards(FrappeTestCase):
	def setUp(self):
		self._snap = _snapshot()
		self._prior_dev_mode = frappe.conf.get("developer_mode") or 0

	def tearDown(self):
		frappe.conf.developer_mode = self._prior_dev_mode
		_restore(self._snap)

	def test_rejects_when_developer_mode_off(self):
		frappe.conf.developer_mode = 0
		with self.assertRaises(frappe.ValidationError) as cm:
			reset_onboarding()
		self.assertEqual(frappe.local.response.http_status_code, 403)
		self.assertIn("developer_mode", str(cm.exception))

	def test_rejects_when_non_system_manager(self):
		frappe.conf.developer_mode = 1
		# Use a Guest who lacks System Manager role.
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.ValidationError) as cm:
			reset_onboarding()
		self.assertEqual(frappe.local.response.http_status_code, 403)
		self.assertIn("System Manager", str(cm.exception))


class TestIsDevModeActive(FrappeTestCase):
	def setUp(self):
		self._prior = frappe.conf.get("developer_mode") or 0

	def tearDown(self):
		frappe.conf.developer_mode = self._prior

	def test_true_when_developer_mode_on(self):
		frappe.conf.developer_mode = 1
		out = is_dev_mode_active()
		self.assertEqual(out["data"]["active"], True)
		self.assertEqual(frappe.local.response.http_status_code, 200)

	def test_false_when_developer_mode_off(self):
		frappe.conf.developer_mode = 0
		out = is_dev_mode_active()
		self.assertEqual(out["data"]["active"], False)
		self.assertEqual(frappe.local.response.http_status_code, 200)
