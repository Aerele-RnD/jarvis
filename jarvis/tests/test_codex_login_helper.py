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
