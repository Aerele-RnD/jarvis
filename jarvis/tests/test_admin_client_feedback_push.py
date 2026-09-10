"""Tests for admin_client.push_session_feedback / push_pulse_feedback.

Both mirror push_chat_feedback's shape (POST {"item": item} to an admin
endpoint path) with one deliberate difference: a SHORT timeout, because both
run synchronously inside a customer web request. _post is mocked so these
never hit a real admin.
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

	@patch.object(admin_client, "_post")
	def test_both_pushes_use_a_short_timeout_not_the_150s_default(self, mock_post):
		"""Both are called synchronously from a whitelisted submit endpoint, so an
		admin that hangs rather than refuses would otherwise pin a customer web
		worker for DEFAULT_TIMEOUT_S (2.5 minutes) per submit."""
		mock_post.return_value = {"ok": True}
		for push in (admin_client.push_session_feedback, admin_client.push_pulse_feedback):
			with self.subTest(push=push.__name__):
				mock_post.reset_mock()
				push({"kind": "x"})
				_, kwargs = mock_post.call_args
				self.assertEqual(kwargs["timeout_s"], admin_client._FEEDBACK_TIMEOUT_S)
				self.assertLess(kwargs["timeout_s"], admin_client.DEFAULT_TIMEOUT_S)
				self.assertLessEqual(kwargs["timeout_s"], 15)
