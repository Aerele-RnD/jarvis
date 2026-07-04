"""Normalize legacy Jarvis Settings.preset values.

`preset` was a Select (options: Cost-saver / Balanced / Max-reliability); it is
now a free-form Data field validated against the lowercase admin-catalog keys
(cost-saver / balanced / max-reliability / ...). A row still holding an old
capitalized label would make the next save_llm_pool raise
ValidationError("unknown preset 'Balanced'"), blocking every LLM-pool edit until
cleared. The old Select could only ever hold these three labels, so map exactly
those to their keys and leave anything else (already-lowercase keys, or blank)
untouched. #200 review #12.
"""

import frappe

_LEGACY_MAP = {
	"Cost-saver": "cost-saver",
	"Balanced": "balanced",
	"Max-reliability": "max-reliability",
}


def execute():
	settings = frappe.get_single("Jarvis Settings")
	preset = (settings.preset or "").strip()
	if preset in _LEGACY_MAP:
		settings.db_set("preset", _LEGACY_MAP[preset], update_modified=False)
		frappe.db.commit()
