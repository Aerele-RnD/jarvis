"""Jarvis User Preference DocType controller.

One durable row per user (doc name = user email) holding per-user Jarvis
preferences. Today it carries the proactive business-note greeting state
machine: the once-ever gate and the permanent "Don't ask again" flag, which
must survive ``bench clear-cache`` and Redis eviction (hence a DB table, not
cache). Written only by whitelisted backend functions under the session user
with ``ignore_permissions`` (SM write-from-Desk exists to fix a stuck state).
"""

from frappe.model.document import Document


class JarvisUserPreference(Document):
	pass
