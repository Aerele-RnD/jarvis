"""Canonical subscription-tier model catalogue.

Two modules used to declare this independently (chat/api.py as
dicts of lists, oauth/api.py as dicts of sets) and the resulting
list-vs-set drift was a punch-list item from the 2026-06-16
review. Centralizing here means one declaration, no drift.

Each entry maps a customer-facing provider label to the list of
model ids accepted by that provider's codex / gemini-cli auth
tunnel. Note: these are CLI-specific names (NOT OpenAI's public
API names like "gpt-4o"); see customer-app/chat-subscription-
onboarding.md "Why these model names look weird" for the
rationale.

Mirrors in JS: jarvis_chat.js / jarvis_account.js /
jarvis_onboarding.js. Keep all three JS files in sync with this
Python catalogue. The fleet-agent's
verify-openclaw-assumptions.sh asserts at image-bump time that
the openclaw catalog still contains "gpt-5.5"; update the JS
mirrors atomically with this list and re-run that script
before bumping the image pin.

Lists (not sets) so the dict is JSON-serializable when
chat/api.py returns it to the browser. The ``in`` membership
checks oauth/api.py needs are O(N) on a 3-item list rather
than O(1) on a set, but N=3 makes the perf difference
meaningless.
"""

from __future__ import annotations

SUBSCRIPTION_MODELS: dict[str, list[str]] = {
	"OpenAI": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"],
	"Google Gemini": [
		"gemini-2.5-pro",
		"gemini-2.5-flash",
		"gemini-3.1-flash",
	],
	# Model ids MUST exist in cli-proxy-api's embedded catalogue for the pinned
	# image (v7.2.35). NB: "grok-4.5" is NOT in that catalogue (use grok-4.3 /
	# grok-build-0.1); "kimi-k2.7-code" IS present.
	"xAI Grok": ["grok-4.3", "grok-build-0.1"],
	"Kimi (Moonshot)": ["kimi-k2.7-code", "kimi-k2.6"],
}

DEFAULT_MODEL: dict[str, str] = {
	"OpenAI": "gpt-5.5",
	"Google Gemini": "gemini-2.5-pro",
	"xAI Grok": "grok-4.3",
	"Kimi (Moonshot)": "kimi-k2.7-code",
}
