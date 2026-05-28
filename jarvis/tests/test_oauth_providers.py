import unittest

from jarvis.oauth.providers import PROVIDER_OAUTH_MAP, REQUIRED_KEYS, get_provider


class TestProviderOAuthMap(unittest.TestCase):
	def test_supported_providers_present(self):
		self.assertIn("OpenAI", PROVIDER_OAUTH_MAP)
		self.assertIn("Google Gemini", PROVIDER_OAUTH_MAP)

	def test_anthropic_absent(self):
		# Excluded by spec — no openclaw adapter
		self.assertNotIn("Anthropic", PROVIDER_OAUTH_MAP)

	def test_every_entry_has_required_keys(self):
		for label, entry in PROVIDER_OAUTH_MAP.items():
			for key in REQUIRED_KEYS:
				self.assertIn(key, entry, f"{label!r} missing {key!r}")

	def test_get_provider_returns_entry(self):
		entry = get_provider("OpenAI")
		self.assertEqual(entry["openclaw_auth_mode"], "subscription")
		self.assertTrue(entry["device_code_endpoint"].startswith("https://"))

	def test_get_provider_raises_for_unknown(self):
		from jarvis.exceptions import InvalidArgumentError

		with self.assertRaises(InvalidArgumentError):
			get_provider("Anthropic")
