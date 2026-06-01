"""Unit tests for the codex-login helper. The helper is a static-asset
.py file served to laptops; we importlib-load it here to test functions
in isolation."""
import base64
import hashlib
import importlib.util
import os
import unittest


def _load_helper():
	here = os.path.dirname(__file__)
	path = os.path.join(here, "..", "public", "codex_login.py")
	path = os.path.normpath(path)
	spec = importlib.util.spec_from_file_location("codex_login", path)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


class TestPKCE(unittest.TestCase):
	def test_generate_pkce_pair_lengths(self):
		helper = _load_helper()
		verifier, challenge = helper.generate_pkce()
		# RFC 7636: verifier 43-128 chars, base64url(no padding)
		self.assertGreaterEqual(len(verifier), 43)
		self.assertLessEqual(len(verifier), 128)
		self.assertNotIn("=", verifier)
		# challenge = base64url(sha256(verifier)) — 43 chars, no padding
		self.assertEqual(len(challenge), 43)
		self.assertNotIn("=", challenge)

	def test_generate_pkce_challenge_matches_verifier(self):
		helper = _load_helper()
		verifier, challenge = helper.generate_pkce()
		expected = base64.urlsafe_b64encode(
			hashlib.sha256(verifier.encode()).digest()
		).rstrip(b"=").decode()
		self.assertEqual(challenge, expected)


from urllib.parse import urlparse, parse_qs


class TestAuthorizeURL(unittest.TestCase):
	def test_openai_authorize_url_has_required_params(self):
		helper = _load_helper()
		url = helper.build_authorize_url(
			provider="openai", redirect_uri="http://localhost:1455/auth/callback",
			code_challenge="CHAL", state="STATE",
		)
		parsed = urlparse(url)
		self.assertEqual(parsed.scheme, "https")
		self.assertEqual(parsed.netloc, "auth.openai.com")
		self.assertEqual(parsed.path, "/oauth/authorize")
		q = parse_qs(parsed.query)
		self.assertEqual(q["response_type"], ["code"])
		self.assertEqual(q["client_id"], ["app_EMoamEEZ73f0CkXaXp7hrann"])
		self.assertEqual(q["redirect_uri"], ["http://localhost:1455/auth/callback"])
		self.assertEqual(q["code_challenge"], ["CHAL"])
		self.assertEqual(q["code_challenge_method"], ["S256"])
		self.assertEqual(q["state"], ["STATE"])
		self.assertIn("openid", q["scope"][0])
		self.assertIn("offline_access", q["scope"][0])

	def test_gemini_authorize_url_has_offline_access(self):
		helper = _load_helper()
		url = helper.build_authorize_url(
			provider="gemini", redirect_uri="http://localhost:1455/auth/callback",
			code_challenge="C", state="S",
		)
		parsed = urlparse(url)
		self.assertEqual(parsed.netloc, "accounts.google.com")
		q = parse_qs(parsed.query)
		# Google requires these for a refresh_token to be returned
		self.assertEqual(q["access_type"], ["offline"])
		self.assertEqual(q["prompt"], ["consent"])

	def test_unknown_provider_raises(self):
		helper = _load_helper()
		with self.assertRaises(ValueError):
			helper.build_authorize_url(
				provider="claude", redirect_uri="http://x", code_challenge="c", state="s",
			)
