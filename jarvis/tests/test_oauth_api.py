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


class TestReceiveBlob(_OAuthApiBase):
	def _seed(self, provider="OpenAI"):
		nonce = "n_" + ("a" * 46)
		frappe.cache.hset(_CACHE_KEY, nonce, {
			"provider": provider, "status": "pending",
			"expires_at_ts": int(time.time()) + 600,
			"send_count": 0, "blob": None, "account_email": None,
		})
		return nonce

	def _valid_blob(self, provider_id="openai-codex"):
		return {
			"type": "oauth",
			"provider": provider_id,
			"access": "AT", "refresh": "RT",
			"expires": 1_700_000_000_000,
			"email": "x@y.com",
			"clientId": "app_EMoamEEZ73f0CkXaXp7hrann",
		}

	def test_receive_happy_path_caches_blob_and_email(self):
		nonce = self._seed()
		out = oauth_api.receive_blob(nonce=nonce, blob=self._valid_blob())
		self.assertTrue(out["ok"])
		entry = frappe.cache.hget(_CACHE_KEY, nonce)
		self.assertEqual(entry["status"], "connected")
		self.assertEqual(entry["account_email"], "x@y.com")
		self.assertEqual(entry["blob"]["access"], "AT")

	def test_unknown_nonce_rejected(self):
		out = oauth_api.receive_blob(nonce="bogus", blob=self._valid_blob())
		self.assertFalse(out["ok"])
		self.assertEqual(out["error"]["code"], "unknown_nonce")

	def test_expired_nonce_rejected(self):
		nonce = self._seed()
		entry = frappe.cache.hget(_CACHE_KEY, nonce)
		entry["expires_at_ts"] = 0  # in the past
		frappe.cache.hset(_CACHE_KEY, nonce, entry)
		out = oauth_api.receive_blob(nonce=nonce, blob=self._valid_blob())
		self.assertEqual(out["error"]["code"], "expired")

	def test_replay_rejected_after_connect(self):
		nonce = self._seed()
		oauth_api.receive_blob(nonce=nonce, blob=self._valid_blob())
		out = oauth_api.receive_blob(nonce=nonce, blob=self._valid_blob())
		self.assertFalse(out["ok"])
		self.assertEqual(out["error"]["code"], "not_pending")

	def test_blob_type_must_be_oauth(self):
		nonce = self._seed()
		bad = self._valid_blob(); bad["type"] = "token"
		out = oauth_api.receive_blob(nonce=nonce, blob=bad)
		self.assertEqual(out["error"]["code"], "invalid_blob")

	def test_blob_provider_must_match_cached_provider(self):
		nonce = self._seed(provider="OpenAI")
		bad = self._valid_blob(provider_id="google-gemini-cli")
		out = oauth_api.receive_blob(nonce=nonce, blob=bad)
		self.assertEqual(out["error"]["code"], "invalid_blob")

	def test_blob_client_id_must_match_registered(self):
		nonce = self._seed()
		bad = self._valid_blob(); bad["clientId"] = "evil_id"
		out = oauth_api.receive_blob(nonce=nonce, blob=bad)
		self.assertEqual(out["error"]["code"], "invalid_blob")

	def test_missing_required_keys_rejected(self):
		nonce = self._seed()
		for missing in ("access", "expires", "clientId", "provider"):
			frappe.cache.hset(_CACHE_KEY, nonce, {
				"provider": "OpenAI", "status": "pending",
				"expires_at_ts": int(time.time()) + 600,
				"send_count": 0, "blob": None, "account_email": None,
			})
			bad = self._valid_blob(); del bad[missing]
			out = oauth_api.receive_blob(nonce=nonce, blob=bad)
			self.assertEqual(out["error"]["code"], "invalid_blob",
			                 msg=f"missing {missing}")
