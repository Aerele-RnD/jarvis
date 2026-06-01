import unittest

from jarvis.oauth.email_templates import build_share_signin_email


class TestBuildShareSigninEmail(unittest.TestCase):
	def _build(self, **overrides):
		kwargs = dict(
			sender_name="Alice", company="Acme",
			provider="OpenAI ChatGPT", one_liner='curl … | python3',
			minutes_left=8,
		)
		kwargs.update(overrides)
		return build_share_signin_email(**kwargs)

	def test_subject_mentions_provider(self):
		out = self._build()
		self.assertIn("ChatGPT", out["subject"])

	def test_body_contains_one_liner_verbatim(self):
		one_liner = ("curl -sSL https://acme.jarvis.aerele.in/codex-login | "
		             "JARVIS_BENCH=https://acme.jarvis.aerele.in "
		             "JARVIS_NONCE=abc JARVIS_PROVIDER=openai python3")
		out = self._build(one_liner=one_liner)
		self.assertIn(one_liner, out["body"])

	def test_body_includes_sender_and_minutes(self):
		out = self._build()
		self.assertIn("Alice", out["body"])
		self.assertIn("8 minute", out["body"])

	def test_body_no_device_code_language(self):
		"""REV-2 emails describe a one-liner, not a code-paste."""
		out = self._build()
		body_lower = out["body"].lower()
		self.assertNotIn("type this code", body_lower)
		self.assertNotIn("type the code", body_lower)
