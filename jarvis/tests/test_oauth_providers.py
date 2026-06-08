"""Tests for jarvis.oauth.providers - provider OAuth metadata."""
import unittest
from urllib.parse import urlparse, parse_qs

from jarvis.oauth import providers


class TestGetProvider(unittest.TestCase):
	def test_openai_returns_codex_metadata(self):
		p = providers.get_provider("OpenAI")
		self.assertEqual(p["authorize"], "https://auth.openai.com/oauth/authorize")
		self.assertEqual(p["token"], "https://auth.openai.com/oauth/token")
		self.assertEqual(p["userinfo"], "https://api.openai.com/v1/userinfo")
		self.assertEqual(p["client_id"], "app_EMoamEEZ73f0CkXaXp7hrann")
		self.assertEqual(p["openclaw_provider"], "openai-codex")
		self.assertIn("openid", p["scope"])
		self.assertIn("api.connectors.read", p["scope"])
		self.assertIn("api.connectors.invoke", p["scope"])

	def test_gemini_returns_gemini_cli_metadata(self):
		p = providers.get_provider("Google Gemini")
		self.assertEqual(p["authorize"], "https://accounts.google.com/o/oauth2/v2/auth")
		self.assertEqual(p["openclaw_provider"], "google-gemini-cli")
		# Userinfo flipped from None to the Google v1 endpoint after the
		# scope drift bug fix - the bundled gemini-cli OAuth client doesn't
		# have `openid` registered, so no id_token comes back and email is
		# fetched via Bearer-authenticated userinfo instead.
		self.assertEqual(p["userinfo"], "https://www.googleapis.com/oauth2/v1/userinfo?alt=json")
		# Lock in the scope contract - matches openclaw's gemini-cli SCOPES.
		# Reject the previously-broken `generative-language` and the
		# `openid`/`email`/`profile` short forms that aren't registered on
		# the gemini-cli OAuth client.
		self.assertIn("https://www.googleapis.com/auth/cloud-platform", p["scope"])
		self.assertIn("https://www.googleapis.com/auth/userinfo.email", p["scope"])
		self.assertIn("https://www.googleapis.com/auth/userinfo.profile", p["scope"])
		self.assertNotIn("generative-language", p["scope"])
		self.assertNotIn("openid", p["scope"])

	def test_unknown_provider_raises(self):
		with self.assertRaises(providers.UnknownProviderError):
			providers.get_provider("Anthropic")


class TestBuildAuthorizeUrl(unittest.TestCase):
	def test_openai_authorize_url_has_codex_specific_params(self):
		url = providers.build_authorize_url(
			provider="OpenAI",
			redirect_uri="http://localhost:1455/auth/callback",
			code_challenge="CHALLENGE",
			state="STATE",
		)
		parsed = urlparse(url)
		self.assertEqual(parsed.netloc, "auth.openai.com")
		self.assertEqual(parsed.path, "/oauth/authorize")
		q = parse_qs(parsed.query)
		self.assertEqual(q["response_type"], ["code"])
		self.assertEqual(q["client_id"], ["app_EMoamEEZ73f0CkXaXp7hrann"])
		self.assertEqual(q["redirect_uri"], ["http://localhost:1455/auth/callback"])
		self.assertEqual(q["code_challenge"], ["CHALLENGE"])
		self.assertEqual(q["code_challenge_method"], ["S256"])
		self.assertEqual(q["state"], ["STATE"])
		self.assertEqual(q["originator"], ["codex_cli_rs"])
		self.assertEqual(q["id_token_add_organizations"], ["true"])
		self.assertEqual(q["codex_cli_simplified_flow"], ["true"])
		self.assertIn("api.connectors.read", q["scope"][0])

	def test_gemini_authorize_url_requests_offline_access(self):
		url = providers.build_authorize_url(
			provider="Google Gemini",
			redirect_uri="http://localhost:1455/auth/callback",
			code_challenge="C", state="S",
		)
		q = parse_qs(urlparse(url).query)
		self.assertEqual(q["access_type"], ["offline"])
		self.assertEqual(q["prompt"], ["consent"])
