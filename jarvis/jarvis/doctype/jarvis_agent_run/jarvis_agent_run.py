"""Jarvis Agent Run DocType controller.

One row per auditor/operator execution (manual or scheduled), modeled on
``Jarvis Macro Run``. Rows are server-generated (the scheduler / the
persistence bridge insert them with ``ignore_permissions`` and reassign the
owner to the installation owner), so the ``All`` role gets ``if_owner`` READ
only — the customer sees their own run history but cannot forge rows.
``status=partial`` marks a scan that hit the turn envelope (never masquerades
as ``completed``).
"""

from frappe.model.document import Document


class JarvisAgentRun(Document):
	pass
