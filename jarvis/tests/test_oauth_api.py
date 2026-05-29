import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.oauth import api as oauth_api
from jarvis.oauth import device_flow


class _OAuthApiBase(FrappeTestCase):
	"""Snapshot+restore Jarvis Settings for OAuth API tests."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Jarvis Settings")
		cls._snap = {
			"llm_auth_mode": settings.llm_auth_mode,
			"llm_provider": settings.llm_provider,
			"llm_oauth_account_email": settings.llm_oauth_account_email,
			"llm_oauth_refresh_token": settings.get_password(
				"llm_oauth_refresh_token", raise_exception=False
			) or "",
			"llm_oauth_access_token": settings.get_password(
				"llm_oauth_access_token", raise_exception=False
			) or "",
		}

	@classmethod
	def tearDownClass(cls):
		from frappe.utils.password import remove_encrypted_password
		settings = frappe.get_single("Jarvis Settings")
		for f in ("llm_auth_mode", "llm_provider", "llm_oauth_account_email"):
			settings.db_set(f, cls._snap[f], update_modified=False)
		for f in ("llm_oauth_refresh_token", "llm_oauth_access_token"):
			remove_encrypted_password("Jarvis Settings", "Jarvis Settings", f)
			settings.db_set(f, None, update_modified=False)
			if cls._snap[f]:
				settings.db_set(f, cls._snap[f], update_modified=False)
		frappe.cache.delete_key("jarvis.oauth.device_codes")
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		# Clean cache key before each test
		frappe.cache.delete_key("jarvis.oauth.device_codes")


class TestStartSignin(_OAuthApiBase):
	@patch("jarvis.oauth.api.device_flow.start")
	def test_start_signin_happy(self, mock_start):
		mock_start.return_value = {
			"device_code": "DC-1", "user_code": "JARV-9X3K",
			"verification_uri": "https://chatgpt.com/auth/device",
			"interval": 5, "expires_in": 600,
		}
		out = oauth_api.start_signin("OpenAI")
		self.assertTrue(out["ok"])
		self.assertEqual(out["data"]["user_code"], "JARV-9X3K")
		# device_code cached for poll
		cached = frappe.cache.hget("jarvis.oauth.device_codes", "DC-1")
		self.assertEqual(cached["provider"], "OpenAI")
		self.assertEqual(cached["send_count"], 0)


class TestPollSignin(_OAuthApiBase):
	@patch("jarvis.oauth.api.device_flow.poll")
	def test_poll_pending(self, mock_poll):
		mock_poll.return_value = device_flow.PENDING
		frappe.cache.hset("jarvis.oauth.device_codes", "DC-1",
		                  {"provider": "OpenAI", "send_count": 0})
		out = oauth_api.poll_signin(device_code="DC-1")
		self.assertEqual(out["data"]["status"], "pending")

	@patch("jarvis.oauth.api.device_flow.poll")
	@patch("jarvis.oauth.api.onboarding.save_llm_creds")
	@patch("jarvis.oauth.api.admin_client.post_push_oauth_blob")
	def test_poll_connected_pushes_blob_and_saves_creds(
		self, mock_push, mock_save, mock_poll,
	):
		"""REV-1: on success, build the openclaw OAuthCredential blob, push it
		via admin → fleet-agent → container, then save_llm_creds(auth_mode=
		"oauth") so on_update restarts container into Branch B config."""
		mock_poll.return_value = {
			"access_token": "AT-1", "refresh_token": "RT-1",
			"expires_in": 3600, "account_email": "manager@acme.com",
		}
		mock_save.return_value = {"last_sync_status": "ok", "last_sync_at": ""}
		frappe.cache.hset("jarvis.oauth.device_codes", "DC-2",
		                  {"provider": "OpenAI", "send_count": 0})
		out = oauth_api.poll_signin(device_code="DC-2")
		self.assertEqual(out["data"]["status"], "connected")
		self.assertEqual(out["data"]["account_email"], "manager@acme.com")

		# Blob pushed with openclaw's expected shape.
		mock_push.assert_called_once()
		pid, blob = mock_push.call_args.args
		self.assertEqual(pid, "openai-codex")
		self.assertEqual(blob["type"], "oauth")
		self.assertEqual(blob["provider"], "openai-codex")
		self.assertEqual(blob["access"], "AT-1")
		self.assertEqual(blob["refresh"], "RT-1")
		self.assertEqual(blob["email"], "manager@acme.com")
		# expires is unix-ms, slightly in the future.
		self.assertGreater(blob["expires"], int(time.time() * 1000))

		# save_llm_creds saved the oauth-mode entry so on_update reshapes config.
		mock_save.assert_called_once()
		kw = mock_save.call_args.kwargs
		self.assertEqual(kw["provider"], "OpenAI")
		self.assertEqual(kw["auth_mode"], "oauth")
		self.assertEqual(kw["api_key"], "")

	@patch("jarvis.oauth.api.device_flow.poll")
	@patch("jarvis.oauth.api.onboarding.save_llm_creds")
	@patch("jarvis.oauth.api.admin_client.post_push_oauth_blob")
	def test_poll_connected_gemini_maps_to_gemini_cli(
		self, mock_push, mock_save, mock_poll,
	):
		mock_poll.return_value = {
			"access_token": "AT-g", "refresh_token": "RT-g",
			"expires_in": 3600, "account_email": "alice@x.com",
		}
		mock_save.return_value = {"last_sync_status": "ok", "last_sync_at": ""}
		frappe.cache.hset("jarvis.oauth.device_codes", "DC-G",
		                  {"provider": "Google Gemini", "send_count": 0})
		oauth_api.poll_signin(device_code="DC-G")
		pid, blob = mock_push.call_args.args
		self.assertEqual(pid, "google-gemini-cli")
		self.assertEqual(blob["provider"], "google-gemini-cli")


class TestShareCode(_OAuthApiBase):
	def setUp(self):
		super().setUp()
		frappe.cache.hset("jarvis.oauth.device_codes", "DC-3", {
			"provider": "OpenAI", "send_count": 0,
			"user_code": "JARV-9X3K",
			"verification_uri": "https://chatgpt.com/auth/device",
			"expires_at_ts": 9999999999,
		})

	@patch("jarvis.oauth.api.frappe.sendmail")
	def test_share_code_sends_email(self, mock_sendmail):
		out = oauth_api.share_code(device_code="DC-3", recipient_email="bob@example.com")
		self.assertTrue(out["ok"])
		mock_sendmail.assert_called_once()

	@patch("jarvis.oauth.api.frappe.sendmail")
	def test_share_code_rate_limit_after_5(self, mock_sendmail):
		for _ in range(5):
			oauth_api.share_code(device_code="DC-3", recipient_email="bob@example.com")
		out = oauth_api.share_code(device_code="DC-3", recipient_email="bob@example.com")
		self.assertFalse(out["ok"])
		self.assertEqual(out["error"]["code"], "rate_limited")
		self.assertEqual(mock_sendmail.call_count, 5)


class TestDisconnect(_OAuthApiBase):
	@patch("jarvis.oauth.api._best_effort_revoke")
	@patch("jarvis.openclaw_push.push_creds_restart")
	def test_disconnect_clears_oauth_fields(self, _mock_restart, _mock_revoke):
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "subscription", update_modified=False)
		settings.db_set("llm_provider", "OpenAI", update_modified=False)
		settings.db_set("llm_oauth_refresh_token", "RT-1", update_modified=False)
		settings.db_set("llm_oauth_account_email", "manager@acme.com", update_modified=False)
		frappe.db.commit()
		out = oauth_api.disconnect()
		self.assertTrue(out["ok"])
		settings = frappe.get_single("Jarvis Settings")
		self.assertFalse(settings.get_password("llm_oauth_refresh_token", raise_exception=False))
		self.assertFalse(settings.llm_oauth_account_email)
