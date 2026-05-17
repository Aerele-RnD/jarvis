"""Jarvis Chat Session DocType controller.

Maps a single openclaw session key to the Frappe user who initiated the session.
Rows are inserted by demo.py (and eventually the real session-create path) at
session-create time. The jarvis-openclaw-plugin's before_tool_call hook calls
back to jarvis.api.lookup_user_by_session to retrieve the user from this table.
"""

import frappe
from frappe.model.document import Document


class JarvisChatSession(Document):
    # Minimal controller — all validation is handled by field constraints.
    # session_key is unique+mandatory; user is a mandatory Link to User.

    def before_insert(self):
        if not self.created_at:
            self.created_at = frappe.utils.now()
