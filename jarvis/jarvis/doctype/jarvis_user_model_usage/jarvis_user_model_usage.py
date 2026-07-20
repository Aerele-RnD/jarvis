"""Jarvis User Model Usage — child table of Jarvis User Settings.

One row per (user, model, month_key). Holds the model's month-to-date token
counters plus the admin-set per-model cap (monthly_token_limit, 0 = unlimited).
Rows are written ONLY by server code in jarvis.chat.usage via atomic SQL (never
a desk save), so this controller stays minimal.
"""

from frappe.model.document import Document


class JarvisUserModelUsage(Document):
	# Identity is (parent, model, month_key). Counters + cap are mutated only by
	# jarvis.chat.usage; no validation hook needed.
	pass
