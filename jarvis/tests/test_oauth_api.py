"""REV-3 OAuth API tests. Bench owns the full OAuth flow (PKCE gen +
token exchange + blob push). Customer's laptop just hosts a browser
session that pastes the redirected URL back."""
import base64
import json
import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.oauth import api as oauth_api


def _jwt(payload: dict) -> str:
	"""Build a fake JWT for tests. Header + signature are bogus; the
	bench never verifies the signature - TLS to the provider is the
	trust root for token-derived claims."""
	payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
	return f"header.{payload_b64}.signature"

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
		out = oauth_api.begin_paste_signin("OpenAI", "gpt-5.5")
		entry = frappe.cache.hget(_CACHE_KEY, out["data"]["nonce"])
		self.assertEqual(entry["provider"], "OpenAI")
		self.assertEqual(entry["model"], "gpt-5.5")
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

	def test_standard_api_model_coerced_to_codex_default(self):
		"""Customer-supplied models that aren't in the codex subscription list
		(e.g. "gpt-4o" carried over from api_key mode) get rewritten to the
		default codex model. Otherwise the openclaw codex extension fails
		every chat turn with ProviderAuthError "No API key found for provider
		openai" - treats model-mismatch as auth failure. Confirmed live on
		jarvis-pool-05b704 (2026-06-11)."""
		out = oauth_api.begin_paste_signin("OpenAI", "gpt-4o")
		entry = frappe.cache.hget(_CACHE_KEY, out["data"]["nonce"])
		self.assertEqual(entry["model"], "gpt-5.5")

	def test_empty_model_coerced_to_default(self):
		out = oauth_api.begin_paste_signin("OpenAI", "")
		entry = frappe.cache.hget(_CACHE_KEY, out["data"]["nonce"])
		self.assertEqual(entry["model"], "gpt-5.5")

	def test_valid_codex_model_passed_through(self):
		for model in ("gpt-5.5", "gpt-5.4", "gpt-5.4-mini"):
			out = oauth_api.begin_paste_signin("OpenAI", model)
			entry = frappe.cache.hget(_CACHE_KEY, out["data"]["nonce"])
			self.assertEqual(entry["model"], model, f"valid codex model {model!r} should pass through unchanged")

	def test_gemini_standard_api_model_coerced_to_cli_default(self):
		"""Same hazard on the Gemini side: a gemini-pro / gemini-1.0-pro from
		the api_key catalog has to be rewritten to a gemini-cli model before
		entering the OAuth nonce cache."""
		out = oauth_api.begin_paste_signin("Google Gemini", "gemini-pro")
		entry = frappe.cache.hget(_CACHE_KEY, out["data"]["nonce"])
		self.assertEqual(entry["model"], "gemini-2.0-pro")


class TestCompletePasteSigninParsing(_OAuthApiBase):
	def _seed(self, **overrides):
		nonce = "n_" + ("a" * 46)
		entry = {
			"provider": "OpenAI",
			# Seed with a codex-CLI model - in production begin_paste_signin
			# has already coerced the customer-supplied model via
			# _coerce_subscription_model before caching, so any nonce
			# complete_paste_signin sees holds a valid codex model.
			"model": "gpt-5.5",
			"status": "pending",
			"expires_at_ts": int(time.time()) + 600,
			"verifier": "test-verifier",
			"state": "test-state",
			"authorize_url": "https://auth.openai.com/oauth/authorize?...",
		}
		entry.update(overrides)
		frappe.cache.hset(_CACHE_KEY, nonce, entry)
		return nonce

	def test_rejects_unknown_nonce(self):
		out = oauth_api.complete_paste_signin(
			nonce="bogus",
			redirected_url="http://localhost:1455/auth/callback?code=A&state=B",
		)
		self.assertEqual(out["error"]["code"], "unknown_nonce")

	def test_rejects_expired_nonce(self):
		nonce = self._seed(expires_at_ts=0)
		out = oauth_api.complete_paste_signin(
			nonce=nonce,
			redirected_url="http://localhost:1455/auth/callback?code=A&state=test-state",
		)
		self.assertEqual(out["error"]["code"], "expired")

	def test_rejects_missing_code(self):
		nonce = self._seed()
		out = oauth_api.complete_paste_signin(
			nonce=nonce,
			redirected_url="http://localhost:1455/auth/callback?state=test-state",
		)
		self.assertEqual(out["error"]["code"], "missing_code")

	def test_rejects_state_mismatch(self):
		nonce = self._seed()
		out = oauth_api.complete_paste_signin(
			nonce=nonce,
			redirected_url="http://localhost:1455/auth/callback?code=A&state=wrong",
		)
		self.assertEqual(out["error"]["code"], "state_mismatch")

	def test_accepts_query_string_only(self):
		nonce = self._seed()
		with patch("jarvis.oauth.api._exchange_code", return_value={
			"access_token": "AT", "refresh_token": "RT", "expires_in": 3600,
			"id_token": "", "email": "x@y.com",
		}), patch("jarvis.oauth.api.admin_client.post_push_oauth_blob"), \
		     patch("jarvis.oauth.api.onboarding.save_llm_creds",
		           return_value={"last_sync_status": "ok"}):
			out = oauth_api.complete_paste_signin(
				nonce=nonce,
				redirected_url="?code=ABC&state=test-state",
			)
		self.assertTrue(out["ok"], msg=str(out))

	def test_accepts_bare_querystring_no_prefix(self):
		nonce = self._seed()
		with patch("jarvis.oauth.api._exchange_code", return_value={
			"access_token": "AT", "refresh_token": "RT", "expires_in": 3600,
			"id_token": "", "email": "x@y.com",
		}), patch("jarvis.oauth.api.admin_client.post_push_oauth_blob"), \
		     patch("jarvis.oauth.api.onboarding.save_llm_creds",
		           return_value={"last_sync_status": "ok"}):
			out = oauth_api.complete_paste_signin(
				nonce=nonce,
				redirected_url="code=ABC&state=test-state",
			)
		self.assertTrue(out["ok"], msg=str(out))


class TestCompletePasteSigninFlow(_OAuthApiBase):
	def _seed(self, provider="OpenAI", model="gpt-5.5"):
		nonce = "k_" + ("d" * 46)
		frappe.cache.hset(_CACHE_KEY, nonce, {
			"provider": provider, "model": model,
			"status": "pending",
			"expires_at_ts": int(time.time()) + 600,
			"verifier": "test-verifier",
			"state": "test-state",
			"authorize_url": "https://auth.openai.com/oauth/authorize?...",
		})
		return nonce

	@patch("jarvis.oauth.api.onboarding.save_llm_creds")
	@patch("jarvis.oauth.api.admin_client.post_push_oauth_blob")
	@patch("jarvis.oauth.api._exchange_code")
	def test_happy_path_pushes_blob_and_saves_creds(
		self, mock_exchange, mock_push, mock_save,
	):
		# Realistic JWT shape: openclaw's codex auth resolver pulls accountId
		# from the access token's `https://api.openai.com/auth.chatgpt_account_id`
		# claim; without that field the OAuth profile is treated as unusable
		# and chat surfaces "No API key found for provider openai".
		access_jwt = _jwt({
			"https://api.openai.com/auth": {
				"chatgpt_account_id": "9151840e-6317-4e8c-a575-8ea33beda869",
			},
		})
		mock_exchange.return_value = {
			"access_token": access_jwt,
			"refresh_token": "RT-456",
			"expires_in": 3600,
			"id_token": "",
			"email": "manager@acme.com",
		}
		mock_save.return_value = {"last_sync_status": "ok"}
		nonce = self._seed()

		out = oauth_api.complete_paste_signin(
			nonce=nonce,
			redirected_url="http://localhost:1455/auth/callback?code=ABC&state=test-state",
		)

		self.assertTrue(out["ok"])
		self.assertEqual(out["data"]["account_email"], "manager@acme.com")
		self.assertEqual(out["data"]["last_sync_status"], "ok")

		mock_exchange.assert_called_once()
		kwargs = mock_exchange.call_args.kwargs
		self.assertEqual(kwargs["provider"], "OpenAI")
		self.assertEqual(kwargs["code"], "ABC")
		self.assertEqual(kwargs["code_verifier"], "test-verifier")

		mock_push.assert_called_once()
		args = mock_push.call_args.args
		# Blob is keyed by the mapped model-provider name so openclaw's
		# request-time auth lookup hits. The OAuth flow itself (authorize
		# URL, client_id, codex-cli params) still uses the OpenAI metadata.
		self.assertEqual(args[0], "openai")
		blob = args[1]
		self.assertEqual(blob["type"], "oauth")
		self.assertEqual(blob["provider"], "openai")
		self.assertEqual(blob["access"], access_jwt)
		self.assertEqual(blob["refresh"], "RT-456")
		self.assertEqual(blob["email"], "manager@acme.com")
		self.assertEqual(blob["accountId"], "9151840e-6317-4e8c-a575-8ea33beda869")
		self.assertEqual(blob["clientId"], "app_EMoamEEZ73f0CkXaXp7hrann")

		mock_save.assert_called_once()
		sk = mock_save.call_args.kwargs
		self.assertEqual(sk["provider"], "OpenAI")
		self.assertEqual(sk["model"], "gpt-5.5")
		self.assertEqual(sk["api_key"], "")
		self.assertEqual(sk["auth_mode"], "oauth")
		# force=True is mandatory in the re-authorize path: without it
		# Jarvis Settings.on_update's diff classifier sees no change
		# and skips the re-render + restart, so openclaw keeps serving
		# the previous (broken) auth state. Verified live 2026-06-11.
		self.assertTrue(sk.get("force"),
			"complete_paste_signin must pass force=True so a no-diff "
			"save still re-renders openclaw.json + restarts the container")

		settings = frappe.get_single("Jarvis Settings")
		self.assertEqual(settings.llm_oauth_account_email, "manager@acme.com")
		self.assertIsNotNone(settings.llm_oauth_connected_at)

		self.assertIsNone(frappe.cache.hget(_CACHE_KEY, nonce))

	@patch("jarvis.oauth.api.onboarding.save_llm_creds")
	@patch("jarvis.oauth.api.admin_client.post_push_oauth_blob")
	@patch("jarvis.oauth.api._exchange_code")
	def test_stale_nonce_model_recoerced_at_complete_time(
		self, mock_exchange, mock_push, mock_save,
	):
		"""Belt-and-suspenders: if a nonce somehow holds a non-codex model
		(e.g. _SUBSCRIPTION_MODELS tightened mid-flight, or a manually
		seeded cache row), complete_paste_signin must re-coerce before
		writing to the blob and save_llm_creds. Otherwise the customer's
		container ends up rendering openclaw.json with the bad model and
		every chat turn fails."""
		jwt = _jwt({
			"https://api.openai.com/auth": {
				"chatgpt_account_id": "acct-test",
			},
		})
		mock_exchange.return_value = {
			"access_token": jwt, "refresh_token": "RT", "expires_in": 3600,
			"id_token": "", "email": "manager@acme.com",
		}
		mock_save.return_value = {"last_sync_status": "ok"}
		nonce = self._seed(model="gpt-4o")  # bypasses begin_paste_signin's coercion

		oauth_api.complete_paste_signin(
			nonce=nonce,
			redirected_url="?code=ABC&state=test-state",
		)

		self.assertEqual(mock_save.call_args.kwargs["model"], "gpt-5.5",
			"complete_paste_signin must re-coerce a stale-cached non-codex model")
		# Blob doesn't carry the model field today, but the push provider id
		# remains tied to OAuth flow, not to the model.
		self.assertEqual(mock_push.call_args.args[0], "openai")

	@patch("jarvis.oauth.api._exchange_code",
	       side_effect=Exception("provider 400"))
	def test_token_exchange_failure_returns_error(self, _):
		"""Generic exception path - actual TokenExchangeError covered by
		the inner _exchange_code function's own tests. Here we just check
		that the endpoint surfaces the failure cleanly."""
		from jarvis.oauth import api as oa
		nonce = self._seed()
		with patch("jarvis.oauth.api._exchange_code",
		           side_effect=oa.TokenExchangeError("provider 400")):
			out = oauth_api.complete_paste_signin(
				nonce=nonce,
				redirected_url="?code=ABC&state=test-state",
			)
		self.assertFalse(out["ok"])
		self.assertEqual(out["error"]["code"], "token_exchange_failed")
		self.assertIsNotNone(frappe.cache.hget(_CACHE_KEY, nonce))


from jarvis import admin_client as _admin_module


class TestDisconnect(_OAuthApiBase):
	@patch("jarvis.oauth.api.admin_client.post_subscription_disconnect")
	def test_disconnect_clears_state(self, mock_disc):
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "oauth", update_modified=False)
		settings.db_set("llm_oauth_account_email", "x@y.com", update_modified=False)
		settings.db_set("llm_oauth_connected_at",
		                frappe.utils.now_datetime(), update_modified=False)
		frappe.cache.hset(_CACHE_KEY, "leftover_nonce", {"status": "pending"})
		frappe.db.commit()

		out = oauth_api.disconnect()
		self.assertTrue(out["ok"])
		mock_disc.assert_called_once()
		settings = frappe.get_single("Jarvis Settings")
		self.assertEqual(settings.llm_auth_mode, "api_key")
		self.assertEqual(settings.last_sync_status, "disconnected")
		self.assertFalse(settings.llm_oauth_account_email)
		self.assertIsNone(settings.llm_oauth_connected_at)
		self.assertIsNone(frappe.cache.hget(_CACHE_KEY, "leftover_nonce"))

	@patch("jarvis.oauth.api.admin_client.post_subscription_disconnect",
	       side_effect=_admin_module.AdminUnreachableError("net"))
	def test_disconnect_admin_failure(self, _):
		out = oauth_api.disconnect()
		self.assertFalse(out["ok"])
		self.assertEqual(out["error"]["code"], "disconnect_failed")


