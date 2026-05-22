"""Jarvis Conversation DocType controller.

One row per chat thread, owned by the Frappe user who created it. The
openclaw session_key is populated on the first agent turn and reused for
subsequent turns so openclaw-side context is preserved within a thread.
"""

import frappe
from frappe.model.document import Document


class JarvisConversation(Document):
	def before_insert(self):
		if not self.last_active_at:
			self.last_active_at = frappe.utils.now()
		if not self.status:
			self.status = "Active"
