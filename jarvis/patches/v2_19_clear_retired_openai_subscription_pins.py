"""Unpin conversations still on an OpenAI subscription model retired upstream.

gpt-5.4 and gpt-5.4-mini were retired from the ChatGPT/Codex catalog: the tenant's
cliproxy answers "unknown provider" for them (measured 2026-09-06 on the pinned
binary). A stored ``Jarvis Conversation.model_override`` is forwarded as-is on later
turns (send_message only re-validates a FRESH override), so a subscription tenant
with such a pin would keep sending a dead id. Clearing the pin returns the
conversation to the workspace default model.

Scoped to sites that use an OpenAI chat subscription, either directly
(``llm_auth_mode`` oauth/subscription with an OpenAI provider) or through an
enabled subscription pool row whose accounts sit on the ``openai`` upstream. An
api-key site keeps its pins: the OpenAI API still serves these ids.

Plain SQL on the conversation table, no document hooks, so ``bench migrate`` does
not fan out per conversation.
"""

import json

import frappe

RETIRED_SUBSCRIPTION_MODELS = ("gpt-5.4", "gpt-5.4-mini")
_SUBSCRIPTION_MODES = {"oauth", "subscription"}
_OPENAI = {"openai", "openai-codex"}


def execute():
	if not _site_uses_openai_subscription():
		return
	cleared = frappe.db.sql(
		"""UPDATE `tabJarvis Conversation` SET model_override = NULL
		WHERE model_override IN %(retired)s""",
		{"retired": RETIRED_SUBSCRIPTION_MODELS},
	)
	frappe.logger().info("cleared retired OpenAI subscription pins: %s", cleared)


def _site_uses_openai_subscription() -> bool:
	mode = (frappe.db.get_single_value("Jarvis Settings", "llm_auth_mode") or "").strip().lower()
	provider = (frappe.db.get_single_value("Jarvis Settings", "llm_provider") or "").strip().lower()
	if mode in _SUBSCRIPTION_MODES and provider in _OPENAI:
		return True
	return _pool_has_openai_subscription()


def _pool_has_openai_subscription() -> bool:
	settings = frappe.get_single("Jarvis Settings")
	for row in settings.get("models") or []:
		if not row.enabled or (row.credential_type or "") != "subscription":
			continue
		try:
			accounts = json.loads(row.get_password("subscription_accounts", raise_exception=False) or "[]")
		except (ValueError, TypeError):
			continue
		if any((a.get("upstream") or "").lower() == "openai" for a in accounts if isinstance(a, dict)):
			return True
	return False
