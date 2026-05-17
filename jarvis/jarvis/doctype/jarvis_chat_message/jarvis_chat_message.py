"""Jarvis Chat Message DocType controller.

One row per user message, assistant response, or tool call within a
conversation. The 'streaming' flag is True while an assistant message is
mid-stream; the worker flips it to False on lifecycle end (or sets error
on lifecycle error). Tool rows carry tool_name, tool_args, tool_result,
tool_status fields populated by jarvis.api.call_tool when invoked from a
chat session.
"""

import frappe
from frappe.model.document import Document


class JarvisChatMessage(Document):
	pass
