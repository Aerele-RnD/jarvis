"""Tests for jarvis.chat.policy - the subscription/credits validation seam."""

from frappe.tests.utils import FrappeTestCase

from jarvis.chat.policy import validate_can_send


class TestValidateCanSend(FrappeTestCase):
	def test_administrator_can_send(self):
		ok, reason = validate_can_send("Administrator")
		self.assertTrue(ok)
		self.assertIsNone(reason)

	def test_any_user_can_send_today(self):
		"""Phase 3 fills in subscription/credit logic. Today any non-empty user is fine."""
		ok, reason = validate_can_send("nobody@example.invalid")
		self.assertTrue(ok)
		self.assertIsNone(reason)

	def test_empty_user_is_rejected(self):
		ok, reason = validate_can_send("")
		self.assertFalse(ok)
		self.assertIsNotNone(reason)

	def test_guest_is_rejected(self):
		ok, reason = validate_can_send("Guest")
		self.assertFalse(ok)
		self.assertIsNotNone(reason)
