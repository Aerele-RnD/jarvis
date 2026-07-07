"""Jarvis Voice Note DocType controller.

One row per captured voice-note transcript, owned by the user who recorded it
(``if_owner`` permission; System Manager gets org-wide read for the Business
processing status). Business-context notes are mined by the daily
``jarvis.learning.voice_facts`` sweep into learned-pattern candidates and wiki
updates; Conversation-context notes feed the wiki ingest directly.

Validation lives here so it runs on every insert/save regardless of whether
the write came from the SPA endpoint (``jarvis.chat.voice_notes_api``), the
Desk, or a test.
"""

import frappe
from frappe import _
from frappe.model.document import Document

MAX_TRANSCRIPT_LEN = 20000


class JarvisVoiceNote(Document):
	def validate(self):
		self._validate_transcript()
		self._validate_context()

	def _validate_transcript(self):
		self.transcript = (self.transcript or "").strip()
		if not self.transcript:
			frappe.throw(_("Transcript is required."))
		if len(self.transcript) > MAX_TRANSCRIPT_LEN:
			frappe.throw(
				_("Transcript must be at most {0} characters.").format(MAX_TRANSCRIPT_LEN)
			)
		if (self.duration_s or 0) < 0:
			self.duration_s = 0

	def _validate_context(self):
		context_type = self.context_type or "Business"
		if context_type == "Conversation" and not self.conversation:
			frappe.throw(
				_("A Conversation-context voice note must link a conversation.")
			)
