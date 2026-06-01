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
		# codex-cli-specific authorize params — required by auth.openai.com
		# for the codex client_id, otherwise it returns a generic
		# "unknown_error" page mid-flow.
		self.assertEqual(q["originator"], ["codex_cli_rs"])
		self.assertEqual(q["id_token_add_organizations"], ["true"])
		self.assertEqual(q["codex_cli_simplified_flow"], ["true"])
		self.assertIn("api.connectors.read", q["scope"][0])
		self.assertIn("api.connectors.invoke", q["scope"][0])

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


class TestPackBlob(unittest.TestCase):
	def test_pack_blob_openai_shape(self):
		helper = _load_helper()
		blob = helper.pack_blob(
			provider="openai",
			access_token="AT",
			refresh_token="RT",
			expires_in=3600,
			email="manager@acme.com",
			now_ts=1_700_000_000,
		)
		self.assertEqual(blob["type"], "oauth")
		self.assertEqual(blob["provider"], "openai-codex")
		self.assertEqual(blob["access"], "AT")
		self.assertEqual(blob["refresh"], "RT")
		# expires is ms since epoch = (now + expires_in) * 1000
		self.assertEqual(blob["expires"], (1_700_000_000 + 3600) * 1000)
		self.assertEqual(blob["email"], "manager@acme.com")
		self.assertEqual(blob["clientId"], "app_EMoamEEZ73f0CkXaXp7hrann")

	def test_pack_blob_gemini_uses_gemini_provider_id(self):
		helper = _load_helper()
		blob = helper.pack_blob(
			provider="gemini", access_token="A", refresh_token="R",
			expires_in=3600, email="x@y", now_ts=0,
		)
		self.assertEqual(blob["provider"], "google-gemini-cli")


import json


class TestExtractEmailFromIdToken(unittest.TestCase):
	def test_extracts_email_from_jwt_payload(self):
		helper = _load_helper()
		# Forge a JWT: header.payload.signature; only middle segment matters
		payload = base64.urlsafe_b64encode(
			json.dumps({"email": "user@example.com", "sub": "123"}).encode()
		).rstrip(b"=").decode()
		jwt = f"HEADER.{payload}.SIG"
		self.assertEqual(helper.email_from_id_token(jwt), "user@example.com")

	def test_returns_empty_on_missing_email(self):
		helper = _load_helper()
		payload = base64.urlsafe_b64encode(
			json.dumps({"sub": "no-email-here"}).encode()
		).rstrip(b"=").decode()
		self.assertEqual(helper.email_from_id_token(f"H.{payload}.S"), "")

	def test_returns_empty_on_malformed_token(self):
		helper = _load_helper()
		self.assertEqual(helper.email_from_id_token("not-a-jwt"), "")
		self.assertEqual(helper.email_from_id_token(""), "")


class TestValidateBenchUrl(unittest.TestCase):
	def test_https_anywhere_ok(self):
		helper = _load_helper()
		helper._validate_bench_url("https://acme.jarvis.aerele.in")  # no raise

	def test_http_127_ok(self):
		helper = _load_helper()
		helper._validate_bench_url("http://127.0.0.1:8000")

	def test_http_localhost_ok(self):
		helper = _load_helper()
		helper._validate_bench_url("http://localhost:8000")

	def test_http_localhost_subdomain_ok(self):
		"""Frappe convention: <site>.localhost. RFC 6761 reserves .localhost
		for loopback, so any subdomain qualifies."""
		helper = _load_helper()
		helper._validate_bench_url("http://jarvis.localhost:8000")
		helper._validate_bench_url("http://jarvis-test.localhost:8000")
		helper._validate_bench_url("http://Foo.LOCALHOST")  # case-insensitive

	def test_http_external_host_rejected(self):
		helper = _load_helper()
		with self.assertRaises(SystemExit):
			helper._validate_bench_url("http://acme.jarvis.aerele.in")

	def test_http_localhost_lookalike_rejected(self):
		"""Domains that merely *contain* "localhost" don't qualify."""
		helper = _load_helper()
		with self.assertRaises(SystemExit):
			helper._validate_bench_url("http://localhost.evil.com")
