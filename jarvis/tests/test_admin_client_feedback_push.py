"""Tests for admin_client.push_session_feedback / push_pulse_feedback.

Both are thin mirrors of push_chat_feedback: they just POST {"item": item} to
a different admin endpoint path. _post is mocked so these never hit a real
admin.
"""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from jarvis import admin_client


class TestAdminClientFeedbackPush(FrappeTestCase):
	@patch.object(admin_client, "_post")
	def test_push_session_feedback_posts_to_correct_path(self, mock_post):
		mock_post.return_value = {"ok": True}
		admin_client.push_session_feedback({"kind": "Session"})
		mock_post.assert_called_once()
		_, kwargs = mock_post.call_args
		self.assertIn("ingest_session_feedback", kwargs["path"])
		self.assertEqual(kwargs["body"], {"item": {"kind": "Session"}})

	@patch.object(admin_client, "_post")
	def test_push_pulse_feedback_posts_to_correct_path(self, mock_post):
		mock_post.return_value = {"ok": True}
		admin_client.push_pulse_feedback({"kind": "Pulse"})
		mock_post.assert_called_once()
		_, kwargs = mock_post.call_args
		self.assertIn("ingest_pulse_feedback", kwargs["path"])
		self.assertEqual(kwargs["body"], {"item": {"kind": "Pulse"}})
