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
		self.assertIn("/assets/jarvis/codex_login.py", out["data"]["one_liner"])

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


class TestPollSignin(_OAuthApiBase):
	def test_returns_pending_for_pending_nonce(self):
		nonce = "p_" + ("b" * 46)
		frappe.cache.hset(_CACHE_KEY, nonce, {
			"provider": "OpenAI", "status": "pending",
			"expires_at_ts": int(time.time()) + 600,
			"send_count": 0, "blob": None, "account_email": None,
		})
		out = oauth_api.poll_signin(nonce=nonce)
		self.assertEqual(out["data"]["status"], "pending")

	def test_returns_connected_with_email(self):
		nonce = "c_" + ("b" * 46)
		frappe.cache.hset(_CACHE_KEY, nonce, {
			"provider": "OpenAI", "status": "connected",
			"expires_at_ts": int(time.time()) + 600,
			"send_count": 0,
			"blob": {"type": "oauth", "provider": "openai-codex"},
			"account_email": "a@b.com",
		})
		out = oauth_api.poll_signin(nonce=nonce)
		self.assertEqual(out["data"]["status"], "connected")
		self.assertEqual(out["data"]["account_email"], "a@b.com")

	def test_unknown_nonce(self):
		out = oauth_api.poll_signin(nonce="missing")
		self.assertEqual(out["error"]["code"], "unknown_nonce")

	def test_expired_nonce(self):
		nonce = "e_" + ("b" * 46)
		frappe.cache.hset(_CACHE_KEY, nonce, {
			"provider": "OpenAI", "status": "pending",
			"expires_at_ts": 0, "send_count": 0, "blob": None,
			"account_email": None,
		})
		out = oauth_api.poll_signin(nonce=nonce)
		self.assertEqual(out["error"]["code"], "expired")


class TestCommitSignin(_OAuthApiBase):
	def _seed_connected(self, provider="OpenAI"):
		nonce = "k_" + ("d" * 46)
		blob = {
			"type": "oauth",
			"provider": "openai-codex" if provider == "OpenAI"
				else "google-gemini-cli",
			"access": "AT", "refresh": "RT",
			"expires": 1_700_000_000_000,
			"email": "manager@acme.com",
			"clientId": "app_EMoamEEZ73f0CkXaXp7hrann"
				if provider == "OpenAI"
				else "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com",
		}
		frappe.cache.hset(_CACHE_KEY, nonce, {
			"provider": provider, "status": "connected",
			"expires_at_ts": int(time.time()) + 600,
			"send_count": 0, "blob": blob, "account_email": blob["email"],
		})
		return nonce, blob

	@patch("jarvis.oauth.api.onboarding.save_llm_creds")
	@patch("jarvis.oauth.api.admin_client.post_push_oauth_blob")
	def test_commit_pushes_blob_and_saves_creds(self, mock_push, mock_save):
		mock_save.return_value = {"last_sync_status": "ok", "last_sync_at": ""}
		nonce, blob = self._seed_connected()
		out = oauth_api.commit_signin(nonce=nonce)
		self.assertTrue(out["ok"])
		mock_push.assert_called_once_with("openai-codex", blob)
		mock_save.assert_called_once()
		kwargs = mock_save.call_args.kwargs
		self.assertEqual(kwargs["provider"], "OpenAI")
		self.assertEqual(kwargs["auth_mode"], "oauth")
		self.assertEqual(kwargs["api_key"], "")
		# nonce cleared
		self.assertIsNone(frappe.cache.hget(_CACHE_KEY, nonce))
		# display-only metadata populated on Jarvis Settings
		settings = frappe.get_single("Jarvis Settings")
		self.assertEqual(settings.llm_oauth_account_email, "manager@acme.com")
		self.assertIsNotNone(settings.llm_oauth_connected_at)

	def test_unknown_nonce(self):
		out = oauth_api.commit_signin(nonce="missing")
		self.assertEqual(out["error"]["code"], "unknown_nonce")

	def test_pending_nonce_cannot_commit(self):
		nonce = "p_" + ("z" * 46)
		frappe.cache.hset(_CACHE_KEY, nonce, {
			"provider": "OpenAI", "status": "pending",
			"expires_at_ts": int(time.time()) + 600,
			"send_count": 0, "blob": None, "account_email": None,
		})
		out = oauth_api.commit_signin(nonce=nonce)
		self.assertEqual(out["error"]["code"], "not_connected")


from jarvis import admin_client


class TestDisconnect(_OAuthApiBase):
	@patch("jarvis.oauth.api.admin_client.post_subscription_disconnect")
	def test_disconnect_flips_mode_and_clears_cache(self, mock_disc):
		# Seed a pending nonce that should get nuked
		frappe.cache.hset(_CACHE_KEY, "stale_nonce",
		                  {"status": "pending", "provider": "OpenAI",
		                   "expires_at_ts": 9999999999, "send_count": 0,
		                   "blob": None, "account_email": None})
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "oauth", update_modified=False)
		settings.db_set("llm_oauth_account_email", "manager@acme.com", update_modified=False)
		settings.db_set("llm_oauth_connected_at", frappe.utils.now_datetime(), update_modified=False)
		frappe.db.commit()

		out = oauth_api.disconnect()
		self.assertTrue(out["ok"])
		mock_disc.assert_called_once()
		settings = frappe.get_single("Jarvis Settings")
		self.assertEqual(settings.llm_auth_mode, "api_key")
		self.assertEqual(settings.last_sync_status, "disconnected")
		# Display-only oauth metadata also cleared
		self.assertFalse(settings.llm_oauth_account_email)
		self.assertIsNone(settings.llm_oauth_connected_at)
		# In-flight nonce cleared
		self.assertIsNone(frappe.cache.hget(_CACHE_KEY, "stale_nonce"))

	@patch("jarvis.oauth.api.admin_client.post_subscription_disconnect",
	       side_effect=admin_client.AdminUnreachableError("net"))
	def test_disconnect_admin_failure_returns_error(self, _):
		out = oauth_api.disconnect()
		self.assertFalse(out["ok"])
		self.assertEqual(out["error"]["code"], "disconnect_failed")


class TestShareSignin(_OAuthApiBase):
	def _seed(self):
		nonce = "s_" + ("e" * 46)
		frappe.cache.hset(_CACHE_KEY, nonce, {
			"provider": "OpenAI", "status": "pending",
			"expires_at_ts": int(time.time()) + 600,
			"send_count": 0, "blob": None, "account_email": None,
		})
		return nonce

	@patch("jarvis.oauth.api.frappe.sendmail")
	def test_share_sends_email_with_one_liner(self, mock_mail):
		nonce = self._seed()
		out = oauth_api.share_signin(nonce=nonce, recipient_email="dev@acme.com")
		self.assertTrue(out["ok"])
		mock_mail.assert_called_once()
		body = mock_mail.call_args.kwargs["message"]
		self.assertIn("JARVIS_NONCE=" + nonce, body)
		# send_count incremented
		entry = frappe.cache.hget(_CACHE_KEY, nonce)
		self.assertEqual(entry["send_count"], 1)

	def test_share_unknown_nonce(self):
		out = oauth_api.share_signin(nonce="bogus", recipient_email="x@y.com")
		self.assertEqual(out["error"]["code"], "unknown_nonce")

	@patch("jarvis.oauth.api.frappe.sendmail")
	def test_share_rate_limited_at_5(self, _):
		nonce = self._seed()
		for _ in range(5):
			oauth_api.share_signin(nonce=nonce, recipient_email="x@y.com")
		out = oauth_api.share_signin(nonce=nonce, recipient_email="x@y.com")
		self.assertEqual(out["error"]["code"], "rate_limited")
