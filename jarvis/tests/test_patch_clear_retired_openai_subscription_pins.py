"""Tests for v2_19: conversations pinned to a retired OpenAI subscription model are unpinned.

gpt-5.4 and gpt-5.4-mini were retired from the ChatGPT/Codex catalog (2026-09-06). A
stored ``Jarvis Conversation.model_override`` is forwarded as-is on later turns (it is
only re-validated when a fresh override is passed), so a subscription tenant with such a
pin would keep sending a dead id. Clearing the pin returns the conversation to the
workspace default; api-key tenants keep their pins because the OpenAI API still serves
those ids.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.api import create_conversation

CONV = "Jarvis Conversation"
SETTINGS = "Jarvis Settings"
POOL_ROW = "Jarvis LLM Pool Model"
_FIELDS = ("llm_auth_mode", "llm_provider", "llm_model")
REPLACEMENT = "gpt-5.6-terra"


class _PinPatchBase(FrappeTestCase):
	def setUp(self):
		snap = {f: frappe.db.get_single_value(SETTINGS, f) for f in _FIELDS}
		self.addCleanup(lambda: [frappe.db.set_single_value(SETTINGS, f, v) for f, v in snap.items()])
		self.addCleanup(frappe.clear_cache, doctype=SETTINGS)

	def _site(self, mode, provider, model=""):
		frappe.db.set_single_value(SETTINGS, "llm_auth_mode", mode)
		frappe.db.set_single_value(SETTINGS, "llm_provider", provider)
		frappe.db.set_single_value(SETTINGS, "llm_model", model)

	def _subscription_row(self, model, upstream="openai"):
		accounts = [
			{"upstream": upstream, "account_ref": "SUB_patchtest", "label": "patch test", "oauth_blob": {}}
		]
		row = frappe.get_doc(
			{
				"doctype": POOL_ROW,
				"parent": SETTINGS,
				"parenttype": SETTINGS,
				"parentfield": "models",
				"idx": 99,
				"enabled": 1,
				"provider": "openai",
				"model": model,
				"tier": "strong",
				"credential_type": "subscription",
				"rotation": "sticky",
				"subscription_accounts": json.dumps(accounts),
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.db.delete, POOL_ROW, {"name": row.name})
		frappe.clear_cache(doctype=SETTINGS)
		return row.name

	def _row_model(self, name):
		return frappe.db.get_value(POOL_ROW, name, "model")

	def _pinned(self, model):
		# create_conversation commits. Inside a FrappeTestCase that commit would
		# make this test's Jarvis Settings writes durable while the cleanup
		# restore below stays uncommitted and is rolled back at class end, so
		# every later test that saves Jarvis Settings on the legacy path would
		# hit "API-key auth mode requires llm_api_key".
		with patch.object(frappe.db, "commit"):
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

	def test_retired_workspace_default_is_repointed(self):
		# turn_handler resolves conv.model_override or settings.llm_model, so a
		# retired workspace default keeps every unpinned conversation broken.
		self._site("subscription", "openai", model="gpt-5.4")
		self._run()
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "llm_model"), REPLACEMENT)

	def test_live_workspace_default_is_kept(self):
		self._site("subscription", "openai", model="gpt-5.5")
		self._run()
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "llm_model"), "gpt-5.5")

	def test_retired_subscription_pool_row_is_repointed(self):
		# _allowed_pin_models admits any pool-row id, so a retired row stays pinnable
		# unless the row itself moves; repointing keeps its account entry.
		retired, live = self._subscription_row("gpt-5.4-mini"), self._subscription_row("gpt-5.5")
		self._run()
		self.assertEqual((self._row_model(retired), self._row_model(live)), (REPLACEMENT, "gpt-5.5"))


class TestRetiredPinsSurviveOnApiKeySite(_PinPatchBase):
	def test_api_key_site_is_untouched(self):
		from jarvis.patches import v2_19_clear_retired_openai_subscription_pins as p

		self._site("api_key", "openai", model="gpt-5.4")
		keep = self._pinned("gpt-5.4-mini")
		# The shared test site may still carry a subscription pool row; an api-key
		# site by definition has none.
		with patch.object(p, "_openai_subscription_pool_rows", return_value=[]):
			self._run()
		self.assertEqual(self._pin_of(keep), "gpt-5.4-mini")
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "llm_model"), "gpt-5.4")
