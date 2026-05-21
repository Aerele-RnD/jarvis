"""Tests for jarvis.onboarding sync + wrappers (admin_client mocked)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import onboarding


def _set_token(value):
	s = frappe.get_single("Jarvis Settings")
	s.db_set("jarvis_admin_api_key", value)
	s.db_set("agent_url", "")
	frappe.db.commit()


class TestSyncConnection(FrappeTestCase):
	def tearDown(self):
		_set_token("")

	def test_sync_writes_connection_when_assigned(self):
		_set_token("tok")
		with patch("jarvis.onboarding.admin_client.get_connection",
				   return_value={"agent_url": "ws://localhost:19000", "agent_token": "k", "tenant_status": "running"}):
			out = onboarding.sync_connection()
		self.assertTrue(out["synced"])
		self.assertEqual(frappe.get_single("Jarvis Settings").agent_url, "ws://localhost:19000")

	def test_sync_noop_when_pending(self):
		_set_token("tok")
		with patch("jarvis.onboarding.admin_client.get_connection",
				   return_value={"agent_url": "", "tenant_status": "pending"}):
			out = onboarding.sync_connection()
		self.assertFalse(out["synced"])

	def test_sync_skips_when_not_onboarded(self):
		import frappe.model.document
		with patch.object(frappe.model.document.Document, "get_password", return_value=""), \
			 patch("jarvis.onboarding.admin_client.get_connection",
				   side_effect=AssertionError("admin must not be called when not onboarded")):
			out = onboarding.sync_connection()
		self.assertFalse(out["synced"])
		self.assertEqual(out["reason"], "not onboarded")

	def test_dev_onboard_writes_token_and_connection(self):
		_set_token("")
		with patch("jarvis.onboarding.admin_client.dev_signup",
				   return_value={"customer": "C1", "api_token": "devtok", "agent_url": "ws://localhost:19002", "agent_token": "k"}):
			onboarding.dev_onboard("e@x.com", "Co", "Annual Plan")
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(s.get_password("jarvis_admin_api_key"), "devtok")
		self.assertEqual(s.agent_url, "ws://localhost:19002")
