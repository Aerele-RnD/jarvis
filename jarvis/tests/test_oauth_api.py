"""REV-2 OAuth API tests. The bench no longer drives OAuth itself — it
mints nonces, accepts blobs from the laptop helper, and forwards them
through the existing admin → fleet-agent path."""
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


class TestBeginCodexSignin(_OAuthApiBase):
	def test_returns_nonce_and_one_liner_for_openai(self):
		out = oauth_api.begin_codex_signin("OpenAI")
		self.assertTrue(out["ok"])
		self.assertIn("nonce", out["data"])
		self.assertIn("one_liner", out["data"])
		nonce = out["data"]["nonce"]
		self.assertEqual(len(nonce), 48)  # 24 hex bytes
		self.assertIn("JARVIS_NONCE=" + nonce, out["data"]["one_liner"])
		self.assertIn("JARVIS_PROVIDER=openai", out["data"]["one_liner"])
		self.assertIn("/codex-login", out["data"]["one_liner"])

	def test_returns_one_liner_for_gemini(self):
		out = oauth_api.begin_codex_signin("Google Gemini")
		self.assertIn("JARVIS_PROVIDER=gemini", out["data"]["one_liner"])

	def test_caches_pending_entry(self):
		out = oauth_api.begin_codex_signin("OpenAI")
		entry = frappe.cache.hget(_CACHE_KEY, out["data"]["nonce"])
		self.assertEqual(entry["provider"], "OpenAI")
		self.assertEqual(entry["status"], "pending")
		self.assertIn("expires_at_ts", entry)
		self.assertIsNone(entry.get("blob"))

	def test_unknown_provider_rejected(self):
		out = oauth_api.begin_codex_signin("Anthropic")
		self.assertFalse(out["ok"])
		self.assertEqual(out["error"]["code"], "unknown_provider")
