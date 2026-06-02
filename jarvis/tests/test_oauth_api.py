"""REV-3 OAuth API tests. Bench owns the full OAuth flow (PKCE gen +
token exchange + blob push). Customer's laptop just hosts a browser
session that pastes the redirected URL back."""
import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.oauth import api as oauth_api

_CACHE_KEY = "jarvis.oauth.codex_signin"


class _OAuthApiBase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Jarvis Settings")
		cls._snap = {
			"llm_auth_mode": settings.llm_auth_mode,
			"llm_provider": settings.llm_provider,
			"llm_model": settings.llm_model,
			"llm_oauth_account_email": settings.llm_oauth_account_email,
			"llm_oauth_connected_at": settings.llm_oauth_connected_at,
		}

	@classmethod
	def tearDownClass(cls):
		settings = frappe.get_single("Jarvis Settings")
		for f, v in cls._snap.items():
			settings.db_set(f, v, update_modified=False)
		frappe.cache.delete_key(_CACHE_KEY)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.cache.delete_key(_CACHE_KEY)


class TestBeginPasteSignin(_OAuthApiBase):
	def test_returns_nonce_authorize_url_expiry(self):
		out = oauth_api.begin_paste_signin("OpenAI", "gpt-4o")
		self.assertTrue(out["ok"])
		self.assertIn("nonce", out["data"])
		self.assertIn("authorize_url", out["data"])
		self.assertEqual(out["data"]["expires_in"], 600)
		nonce = out["data"]["nonce"]
		self.assertEqual(len(nonce), 48)  # 24 hex bytes

	def test_authorize_url_contains_codex_params(self):
		out = oauth_api.begin_paste_signin("OpenAI", "gpt-4o")
		url = out["data"]["authorize_url"]
		self.assertIn("client_id=app_EMoamEEZ73f0CkXaXp7hrann", url)
		self.assertIn("originator=codex_cli_rs", url)
		self.assertIn("redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback", url)

	def test_caches_verifier_state_provider_model(self):
		out = oauth_api.begin_paste_signin("OpenAI", "gpt-4o")
		entry = frappe.cache.hget(_CACHE_KEY, out["data"]["nonce"])
		self.assertEqual(entry["provider"], "OpenAI")
		self.assertEqual(entry["model"], "gpt-4o")
		self.assertEqual(entry["status"], "pending")
		self.assertIn("verifier", entry)
		self.assertIn("state", entry)
		self.assertGreater(len(entry["verifier"]), 40)  # base64url(32 bytes)

	def test_gemini_provider_returns_gemini_url(self):
		out = oauth_api.begin_paste_signin("Google Gemini", "gemini-2.0-pro")
		self.assertIn("accounts.google.com", out["data"]["authorize_url"])

	def test_unknown_provider_rejected(self):
		out = oauth_api.begin_paste_signin("Anthropic", "claude-3-5")
		self.assertFalse(out["ok"])
		self.assertEqual(out["error"]["code"], "unknown_provider")
