from datetime import datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.oauth import device_flow, refresh


class TestRefreshTick(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Jarvis Settings")
		cls._snap = {
			"llm_auth_mode": settings.llm_auth_mode,
			"llm_provider": settings.llm_provider,
			"llm_oauth_refresh_token": settings.get_password(
				"llm_oauth_refresh_token", raise_exception=False
			) or "",
			"llm_oauth_access_token": settings.get_password(
				"llm_oauth_access_token", raise_exception=False
			) or "",
			"llm_oauth_access_token_expires_at": settings.llm_oauth_access_token_expires_at,
			"llm_oauth_last_refresh_at": settings.llm_oauth_last_refresh_at,
			"last_sync_status": settings.last_sync_status,
		}

	@classmethod
	def tearDownClass(cls):
		from frappe.utils.password import remove_encrypted_password
		settings = frappe.get_single("Jarvis Settings")
		# Restore plain fields
		for f in ("llm_auth_mode", "llm_provider",
		          "llm_oauth_access_token_expires_at",
		          "llm_oauth_last_refresh_at", "last_sync_status"):
			settings.db_set(f, cls._snap[f], update_modified=False)
		# Restore password fields (or wipe if snapshot was empty)
		for f in ("llm_oauth_refresh_token", "llm_oauth_access_token"):
			remove_encrypted_password("Jarvis Settings", "Jarvis Settings", f)
			if cls._snap[f]:
				settings.db_set(f, cls._snap[f], update_modified=False)
		frappe.db.commit()
		super().tearDownClass()

	def _set_subscription(self, expires_at):
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "subscription", update_modified=False)
		settings.db_set("llm_provider", "OpenAI", update_modified=False)
		settings.db_set("llm_oauth_refresh_token", "RT-seed", update_modified=False)
		settings.db_set("llm_oauth_access_token", "AT-seed", update_modified=False)
		settings.db_set("llm_oauth_access_token_expires_at", expires_at, update_modified=False)
		frappe.db.commit()

	@patch("jarvis.oauth.refresh.device_flow.refresh")
	def test_noop_when_not_subscription(self, mock_refresh):
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "api_key", update_modified=False)
		frappe.db.commit()
		refresh.tick()
		mock_refresh.assert_not_called()

	@patch("jarvis.oauth.refresh.device_flow.refresh")
	def test_noop_when_token_fresh(self, mock_refresh):
		far_future = datetime.utcnow() + timedelta(hours=2)
		self._set_subscription(far_future)
		refresh.tick()
		mock_refresh.assert_not_called()

	@patch("jarvis.oauth.refresh.openclaw_push.push_creds_reload")
	@patch("jarvis.oauth.refresh.get_oauth_client_id", return_value="CLIENT_ID")
	@patch("jarvis.oauth.refresh.device_flow.refresh")
	def test_refreshes_when_within_15min(self, mock_refresh, _mock_cid, mock_reload):
		soon = datetime.utcnow() + timedelta(minutes=10)
		self._set_subscription(soon)
		mock_refresh.return_value = {
			"access_token": "AT-2", "refresh_token": None, "expires_in": 3600,
		}
		refresh.tick()
		mock_refresh.assert_called_once()
		settings = frappe.get_single("Jarvis Settings")
		self.assertEqual(settings.get_password("llm_oauth_access_token"), "AT-2")
		mock_reload.assert_called_once()

	@patch("jarvis.oauth.refresh.get_oauth_client_id", return_value="CLIENT_ID")
	@patch("jarvis.oauth.refresh.device_flow.refresh")
	def test_invalid_grant_zeros_creds_and_sets_revoked(self, mock_refresh, _mock_cid):
		soon = datetime.utcnow() + timedelta(minutes=10)
		self._set_subscription(soon)
		mock_refresh.side_effect = device_flow.InvalidGrant("revoked")
		refresh.tick()
		settings = frappe.get_single("Jarvis Settings")
		self.assertEqual(settings.last_sync_status, "subscription_revoked")
		self.assertFalse(settings.get_password("llm_oauth_refresh_token", raise_exception=False))
		self.assertFalse(settings.get_password("llm_oauth_access_token", raise_exception=False))
		# Mode stays subscription per spec
		self.assertEqual(settings.llm_auth_mode, "subscription")

	@patch("jarvis.oauth.refresh.get_oauth_client_id", return_value="CLIENT_ID")
	@patch("jarvis.oauth.refresh.device_flow.refresh")
	def test_transient_error_does_not_clear_creds(self, mock_refresh, _mock_cid):
		soon = datetime.utcnow() + timedelta(minutes=10)
		self._set_subscription(soon)
		mock_refresh.side_effect = device_flow.ProviderUnavailable("503")
		refresh.tick()  # Should not raise
		settings = frappe.get_single("Jarvis Settings")
		self.assertTrue(settings.get_password("llm_oauth_refresh_token"))
