"""Backfill manual_links='[]' on pre-existing Jarvis Wiki Page rows.

The new JSON field reads NULL on rows created before it existed. Readers coalesce
NULL to [] (jarvis.chat.wiki_graph._manual_link_targets), so this is belt-and-
braces — it makes the stored value explicit for the add_wiki_link append path.
"""

import frappe


def execute():
	if not frappe.db.has_column("Jarvis Wiki Page", "manual_links"):
		return
	frappe.db.sql(
		"""update `tabJarvis Wiki Page`
		set manual_links = '[]'
		where manual_links is null or manual_links = ''"""
	)
