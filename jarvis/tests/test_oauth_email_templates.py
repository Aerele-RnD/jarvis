import unittest

from jarvis.oauth.email_templates import build_share_code_email


class TestBuildShareCodeEmail(unittest.TestCase):
	def test_builds_subject_and_body(self):
		out = build_share_code_email(
			site="acme-frappe.cloud",
			provider="OpenAI",
			verification_uri="https://chatgpt.com/auth/device",
			user_code="JARV-9X3K",
			minutes_left=9,
			sender_name="Alice",
		)
		self.assertIn("acme-frappe.cloud", out["subject"])
		self.assertIn("JARV-9X3K", out["body"])
		self.assertIn("chatgpt.com/auth/device", out["body"])
		self.assertIn("OpenAI", out["body"])
		self.assertIn("9 minutes", out["body"])
		self.assertIn("Alice", out["body"])
