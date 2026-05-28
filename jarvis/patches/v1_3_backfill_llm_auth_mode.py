"""Backfill llm_auth_mode = 'api_key' for the existing Jarvis Settings row.

The new field has default='api_key', but defaults only apply on insert.
The single Jarvis Settings row predates the field, so we backfill the
sentinel that the controller's validate() / on_update() expect.
"""

import frappe


def execute():
	settings = frappe.get_single("Jarvis Settings")
	if not settings.llm_auth_mode:
		settings.db_set("llm_auth_mode", "api_key", update_modified=False)
		frappe.db.commit()
