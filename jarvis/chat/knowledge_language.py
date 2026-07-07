"""Org-wide knowledge-language preference (design D6).

Reads the ``Jarvis Settings.knowledge_language`` Select ("English" default /
"Original") and renders the prompt block every knowledge-WRITING LLM funnel
appends to its system prompt: voice-fact extraction
(``jarvis.learning.voice_facts``), wiki ingest (``jarvis.chat.wiki``) and the
insight-to-skill drafts (``jarvis.chat.learned_api``). English mode translates
non-English source material; Original keeps the source's dominant language.

Chat STT transcription is deliberately NOT covered: a conversation transcript
stays verbatim in the spoken language (conversation != knowledge store).

The field is a Select, not a Check, so a plain ``get_single_value`` with an
English fallback is safe on v16 (no tabSingles row-existence probe needed -
that dance is only for Check fields whose unset value coerces to 0).
"""

from __future__ import annotations

import frappe

SETTINGS = "Jarvis Settings"

DEFAULT_LANGUAGE = "English"
_LANGUAGES = ("English", "Original")

_ENGLISH_DIRECTIVE = (
	"Write all output (facts, wiki content, skill text) in English; translate "
	"source material when needed; keep proper nouns (party/item/person names) "
	"in original script followed by a Latin transliteration in parentheses."
)
_ORIGINAL_DIRECTIVE = "Write output in the dominant language of the source material."


def get_knowledge_language() -> str:
	"""The org-wide knowledge language: "English" (default) or "Original".

	Falsy or unknown stored values coalesce to English - Frappe never backfills
	Single defaults, so a pre-existing Settings row reads null until the
	``voice_facts.after_migrate`` seeding runs."""
	try:
		value = (frappe.db.get_single_value(SETTINGS, "knowledge_language") or "").strip()
	except Exception:
		# Consumers embed this inside job/endpoint prompt builders; a broken
		# Settings read must never take the extraction down with it.
		return DEFAULT_LANGUAGE
	return value if value in _LANGUAGES else DEFAULT_LANGUAGE


def language_directive() -> str:
	"""The language prompt block (always non-empty) appended to the
	knowledge-writing system prompts."""
	if get_knowledge_language() == "Original":
		return _ORIGINAL_DIRECTIVE
	return _ENGLISH_DIRECTIVE
