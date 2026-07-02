"""Jarvis Macro Run — execution state for one run of a Jarvis Macro.

Created when a macro starts; the server-side chaining hook in
``jarvis.chat.turn_handler`` reads it (via ``jarvis.chat.macros.advance_after_turn``)
to decide whether to enqueue the next step, and the SPA renders progress from the
``status``/``current_step``/``total_steps`` fields.
"""

from frappe.model.document import Document


class JarvisMacroRun(Document):
	pass
