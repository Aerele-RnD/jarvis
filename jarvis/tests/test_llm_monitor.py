"""TDD tests for customer-side LLM monitor wrappers (Plan 3 Phase F).

Tests: account.get_llm_usage (short-circuit for direct tenants; passthrough
for proxy tenants; admin error surfaces as frappe.ValidationError) and
account.get_llm_connection_status (field remapping; no token material).
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import account, admin_client
from jarvis.exceptions import AdminValidationError


class TestGetLlmUsage(FrappeTestCase):
	def setUp(self):
		self._proxy = frappe.db.get_single_value("Jarvis Settings", "proxy_active")

	def tearDown(self):
		frappe.db.set_single_value("Jarvis Settings", "proxy_active", self._proxy or 0)
		frappe.db.commit()

	def test_direct_tenant_returns_empty_shape_without_admin_call(self):
		frappe.db.set_single_value("Jarvis Settings", "proxy_active", 0)
		frappe.db.commit()
		with patch.object(admin_client, "get_llm_usage") as m:
			out = account.get_llm_usage()
		m.assert_not_called()
		self.assertEqual(out["applicable"], False)
		self.assertEqual(out["per_model"], [])
		self.assertEqual(out["used_vs_limit"], {"used_usd": 0.0, "limit_usd": None})

	def test_proxy_tenant_passes_admin_payload_through(self):
		frappe.db.set_single_value("Jarvis Settings", "proxy_active", 1)
		frappe.db.commit()
		fake = {
			"applicable": True,
			"period": "1M",
			"tokens_in": 10,
			"tokens_out": 20,
			"cost_usd": 0.42,
			"per_model": [{"model": "gpt-5.5", "tokens": 30, "cost": 0.42}],
			"used_vs_limit": {"used_usd": 0.42, "limit_usd": 5.0},
		}
		with patch.object(admin_client, "get_llm_usage", return_value=fake) as m:
			out = account.get_llm_usage()
		m.assert_called_once_with()
		self.assertEqual(out["applicable"], True)
		self.assertEqual(out["cost_usd"], 0.42)
		self.assertEqual(out["per_model"][0]["model"], "gpt-5.5")

	def test_admin_validation_error_surfaces_as_frappe_throw(self):
		frappe.db.set_single_value("Jarvis Settings", "proxy_active", 1)
		frappe.db.commit()
		with patch.object(
			admin_client, "get_llm_usage", side_effect=AdminValidationError("bifrost unreachable")
		):
			with self.assertRaises(frappe.ValidationError):
				account.get_llm_usage()


class TestGetLlmConnectionStatus(FrappeTestCase):
	def setUp(self):
		self._proxy = frappe.db.get_single_value("Jarvis Settings", "proxy_active")
		self._llm_model = frappe.db.get_single_value("Jarvis Settings", "llm_model")

	def tearDown(self):
		frappe.db.set_single_value("Jarvis Settings", "proxy_active", self._proxy or 0)
		frappe.db.set_single_value("Jarvis Settings", "llm_model", self._llm_model or "")
		frappe.db.commit()

	def test_remaps_admin_auth_status_fields(self):
		frappe.db.set_single_value("Jarvis Settings", "proxy_active", 1)
		frappe.db.commit()
		raw = {
			"ok": True,
			"data": {
				"auth_profile_present": True,
				"profile_ids": ["openai"],
				"default_model": "gpt-5.5",
				"openai_profile_expires_ms": 1893456000000,
			},
		}
		with patch.object(admin_client, "post_llm_auth_status", return_value=raw) as m:
			out = account.get_llm_connection_status()
		m.assert_called_once_with()
		self.assertEqual(out["proxy_active"], True)
		self.assertEqual(out["auth_present"], True)
		self.assertEqual(out["oauth_expires_at"], 1893456000000)
		self.assertEqual(out["default_model"], "gpt-5.5")

	def test_direct_tenant_short_circuits_without_admin_call(self):
		# A DIRECT (single-model) tenant has no proxy auth profile to report -
		# the SPA's ConnectionPane used to render this as a misleading orange
		# "Not connected" instead of an accurate "Direct" state.
		frappe.db.set_single_value("Jarvis Settings", "proxy_active", 0)
		frappe.db.set_single_value("Jarvis Settings", "llm_model", "gpt-4o")
		frappe.db.commit()
		with patch.object(admin_client, "post_llm_auth_status") as m:
			out = account.get_llm_connection_status()
		m.assert_not_called()
		self.assertEqual(out["proxy_active"], False)
		self.assertEqual(out["auth_present"], False)
		self.assertEqual(out["default_model"], "gpt-4o")
