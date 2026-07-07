"""Jarvis Wiki Page DocType controller.

One page of durable org knowledge (a customer, supplier, item, process,
transactional-doctype convention, exception, integration, person or org-wide
note), keyed by a lowercase ``slug`` (``autoname: field:slug``). Pages are
written by the wiki ingest / voice-facts extraction
(``jarvis.chat.wiki.apply_extracted_page_updates``), the ``update_wiki`` agent
tool and the SPA's ``save_wiki_page`` endpoint; all of those funnel through
this controller, so the slug/length invariants hold no matter who wrote.

Slug grammar: alnum runs separated by single hyphens, with ``--`` reserved as
the type separator (``customer--acme-corp``, ``doctype--sales-invoice``).
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document

from jarvis.learning.sanitizer import (
	SANITIZED_PLACEHOLDER,
	scan_instruction_injection,
)

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-{1,2}[a-z0-9]+)*$")
MAX_SLUG_LEN = 140
MAX_SUMMARY_LEN = 500
MAX_BODY_LEN = 20000

# Cached "org has >=1 Active wiki page" flag consumed by the per-turn
# wiki_clause hot path; invalidated by every controller write below.
WIKI_HAS_PAGES_CACHE_KEY = "jarvis:wiki_has_active_pages"

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Instruction shapes neutralized in stored BODIES. Bodies are markdown, so
# headings/fences/--- stay (legitimate structure); these are pure injection
# tokens: ignore-previous phrasing, a forged role prefix, a forged
# <available_skills> tag and the jarvis__ tool-call token (defanged so a
# stored body read back by jarvis__read_wiki can never carry a runnable
# tool instruction).
_BODY_NEUTRALIZE = (
	(re.compile(r"ignore\s+(?:all\s+|the\s+|any\s+)?previous", re.IGNORECASE), "(sanitized)"),
	(re.compile(r"disregard\s+(?:all\s+|the\s+|any\s+)?(?:previous|above)", re.IGNORECASE), "(sanitized)"),
	(re.compile(r"(?im)^(\s*)(?:system|assistant|developer)\s*:"), r"\1(sanitized):"),
	(re.compile(r"<\s*/?\s*available_skills\s*>", re.IGNORECASE), "(sanitized)"),
	(re.compile(r"jarvis__"), "jarvis-"),
)


def _invalidate_has_pages_flag():
	frappe.cache().delete_value(WIKI_HAS_PAGES_CACHE_KEY)


class JarvisWikiPage(Document):
	def validate(self):
		self._validate_slug()
		self._sanitize_untrusted_text()
		self._validate_lengths()

	def after_insert(self):
		_invalidate_has_pages_flag()

	def on_update(self):
		# Covers every save, the archive path included (archive is a status
		# flip through doc.save).
		_invalidate_has_pages_flag()

	def on_trash(self):
		_invalidate_has_pages_flag()

	def _sanitize_untrusted_text(self):
		"""Wiki text is org-user-authored and flows into prompts (the per-turn
		[Context:] clause inlines summaries; ``jarvis__read_wiki`` returns
		bodies), so instruction-shaped content is neutralized at THIS write
		funnel — every writer (ingest, update_wiki tool, SPA save) lands here."""
		if self.summary:
			s = _CONTROL_RE.sub("", str(self.summary))
			self.summary = (
				SANITIZED_PLACEHOLDER if scan_instruction_injection(s) else s
			)
		if self.body_md:
			body = _CONTROL_RE.sub("", str(self.body_md))
			for pattern, repl in _BODY_NEUTRALIZE:
				body = pattern.sub(repl, body)
			self.body_md = body

	def _validate_slug(self):
		self.slug = (self.slug or "").strip().lower()
		if not self.slug:
			frappe.throw(_("Slug is required."))
		if len(self.slug) > MAX_SLUG_LEN:
			frappe.throw(
				_("Slug must be at most {0} characters.").format(MAX_SLUG_LEN)
			)
		if not SLUG_RE.match(self.slug):
			frappe.throw(
				_(
					"Slug must be lowercase letters and digits separated by "
					"single or double hyphens (e.g. customer--acme-corp)."
				)
			)

	def _validate_lengths(self):
		self.title = (self.title or "").strip()
		if self.summary and len(self.summary) > MAX_SUMMARY_LEN:
			frappe.throw(
				_("Summary must be at most {0} characters.").format(MAX_SUMMARY_LEN)
			)
		if self.body_md and len(self.body_md) > MAX_BODY_LEN:
			frappe.throw(
				_("Body must be at most {0} characters.").format(MAX_BODY_LEN)
			)
