"""Backfill scope='Org' on pre-scope Jarvis Wiki Page rows (wiki v2).

The new reqd Select defaults to 'Org', but defaults only apply on insert -
rows created before the field existed read NULL. Readers coalesce NULL to
Org, so this is belt-and-braces: it makes standard filters and the scope
permission SQL exact instead of relying on the coalesce forever.
"""

import frappe


def execute():
	if not frappe.db.has_column("Jarvis Wiki Page", "scope"):
		return
	frappe.db.sql(
		"""update `tabJarvis Wiki Page`
		set scope = 'Org'
		where scope is null or scope = ''"""
	)
