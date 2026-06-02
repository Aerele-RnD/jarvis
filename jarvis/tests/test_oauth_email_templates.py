import unittest

from jarvis.oauth.email_templates import build_share_paste_signin_email


class TestBuildSharePasteSigninEmail(unittest.TestCase):
	def _build(self, **overrides):
		kwargs = dict(
			sender_name="Alice", company="Acme",
			provider="OpenAI ChatGPT",
			authorize_url="https://auth.openai.com/oauth/authorize?response_type=code&...",
			bench_url="https://acme.jarvis.aerele.in",
			minutes_left=8,
		)
		kwargs.update(overrides)
		return build_share_paste_signin_email(**kwargs)

	def test_subject_mentions_provider(self):
		out = self._build()
		self.assertIn("ChatGPT", out["subject"])

	def test_body_contains_authorize_url(self):
		out = self._build()
		self.assertIn("https://auth.openai.com/oauth/authorize", out["body"])

	def test_body_links_back_to_bench(self):
		out = self._build()
		self.assertIn("acme.jarvis.aerele.in/jarvis-account", out["body"])

	def test_body_includes_sender_and_minutes(self):
		out = self._build()
		self.assertIn("Alice", out["body"])
		self.assertIn("8 minute", out["body"])

	def test_body_no_terminal_or_curl_language(self):
		out = self._build()
		body_lower = out["body"].lower()
		self.assertNotIn("terminal", body_lower)
		self.assertNotIn("curl ", body_lower)
		self.assertNotIn("python3", body_lower)
