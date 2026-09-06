"""Tests for v2_19: conversations pinned to a retired OpenAI subscription model are unpinned.

gpt-5.4 and gpt-5.4-mini were retired from the ChatGPT/Codex catalog (2026-09-06). A
stored ``Jarvis Conversation.model_override`` is forwarded as-is on later turns (it is
only re-validated when a fresh override is passed), so a subscription tenant with such a
pin would keep sending a dead id. Clearing the pin returns the conversation to the
workspace default; api-key tenants keep their pins because the OpenAI API still serves
those ids.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.api import create_conversation

CONV = "Jarvis Conversation"
SETTINGS = "Jarvis Settings"
_FIELDS = ("llm_auth_mode", "llm_provider")


class _PinPatchBase(FrappeTestCase):
	def setUp(self):
		snap = {f: frappe.db.get_single_value(SETTINGS, f) for f in _FIELDS}
		self.addCleanup(lambda: [frappe.db.set_single_value(SETTINGS, f, v) for f, v in snap.items()])

	def _site(self, mode, provider):
		frappe.db.set_single_value(SETTINGS, "llm_auth_mode", mode)
		frappe.db.set_single_value(SETTINGS, "llm_provider", provider)

	def _pinned(self, model):
		name = create_conversation()
		frappe.db.set_value(CONV, name, "model_override", model)
		return name

	def _run(self):
		from jarvis.patches.v2_19_clear_retired_openai_subscription_pins import execute

		execute()

	def _pin_of(self, name):
		return frappe.db.get_value(CONV, name, "model_override") or ""


class TestClearRetiredPinsOnSubscriptionSite(_PinPatchBase):
	def setUp(self):
		super().setUp()
		self._site("subscription", "openai")

	def test_retired_pins_are_cleared(self):
		a, b = self._pinned("gpt-5.4"), self._pinned("gpt-5.4-mini")
		self._run()
		self.assertEqual((self._pin_of(a), self._pin_of(b)), ("", ""))

	def test_live_pins_are_kept(self):
		keep = self._pinned("gpt-5.5")
		self._run()
		self.assertEqual(self._pin_of(keep), "gpt-5.5")


class TestRetiredPinsSurviveOnApiKeySite(_PinPatchBase):
	def test_api_key_site_is_untouched(self):
		from unittest.mock import patch

		from jarvis.patches import v2_19_clear_retired_openai_subscription_pins as p

		self._site("api_key", "openai")
		keep = self._pinned("gpt-5.4-mini")
		# The shared test site may still carry a subscription pool row; an api-key
		# site by definition has none.
		with patch.object(p, "_pool_has_openai_subscription", return_value=False):
			self._run()
		self.assertEqual(self._pin_of(keep), "gpt-5.4-mini")
