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


# Fields these tests write to. Snapshot in setUp, restore in tearDown so
# tests run against a real site (e.g. jarvis.localhost) don't clobber the
# operator's actual onboarded state — Frappe Singles aren't transactionally
# rolled back between tests.
_SNAPSHOTTED_FIELDS = (
	"jarvis_admin_url", "jarvis_admin_api_key", "agent_url", "agent_token",
)


def _snapshot_settings() -> dict:
	s = frappe.get_single("Jarvis Settings")
	snap = {}
	for f in _SNAPSHOTTED_FIELDS:
		# Password fields → get_password; plain → attribute. Both safe.
		v = s.get_password(f, raise_exception=False) if f.endswith(("_key", "_token")) else s.get(f)
		snap[f] = v or ""
	return snap


def _restore_settings(snap: dict) -> None:
	for f, v in snap.items():
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", f, v)
	frappe.db.commit()


class TestSyncConnection(FrappeTestCase):
	def setUp(self):
		self._snap = _snapshot_settings()

	def tearDown(self):
		_restore_settings(self._snap)

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

	def test_dev_onboard_defaults_admin_url_when_empty(self):
		"""Single-bench dev: dev_onboard should auto-set jarvis_admin_url to the
		current site URL so admin_client doesn't fall back to the prod default."""
		_set_token("")
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "jarvis_admin_url", "")
		frappe.db.commit()
		with patch("jarvis.onboarding.admin_client.dev_signup",
				   return_value={"api_token": "t", "agent_url": "ws://h:1", "agent_token": "k"}):
			onboarding.dev_onboard("e2@x.com", "Co", "Annual Plan")
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(s.jarvis_admin_url, frappe.utils.get_url())

	def test_dev_onboard_preserves_existing_admin_url(self):
		"""If operator has already set jarvis_admin_url (e.g. multi-bench dev),
		don't overwrite it."""
		_set_token("")
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings",
							"jarvis_admin_url", "http://other-admin.local")
		frappe.db.commit()
		try:
			with patch("jarvis.onboarding.admin_client.dev_signup",
					   return_value={"api_token": "t", "agent_url": "ws://h:1", "agent_token": "k"}):
				onboarding.dev_onboard("e3@x.com", "Co", "Annual Plan")
			s = frappe.get_single("Jarvis Settings")
			self.assertEqual(s.jarvis_admin_url, "http://other-admin.local")
		finally:
			frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "jarvis_admin_url", "")
			frappe.db.commit()
