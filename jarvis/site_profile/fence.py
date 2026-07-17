"""Per-user permission fence over collect_profile() output.

The collector is permission-free; THIS layer drops every item attributable to
a doctype the caller cannot read - custom doctypes, custom-field groups,
workflows, reports, print formats, script buckets alike. The data shape holds
no precomputed CROSS-DOCTYPE totals: render derives every section count from
list lengths AFTER this filter, so "counts recomputed post-fence" holds by
construction (a clerk's index says 12 custom doctypes, never "12 of 31" - a
pre-filter count would leak existence). The per-doctype counts inside an item
(custom_field_count etc.) describe a doctype the user can already read.

App and module names pass unfenced: existence at app granularity is the
accepted coarse leak, matching the [Context:] clause.
"""

from __future__ import annotations

import frappe


def fence_for_user(data: dict, user: str | None = None) -> dict:
	"""Filter ``data`` (collect_profile shape) to what ``user`` may read.
	Returns a NEW dict, same shape, all keys present. Fails closed per item:
	a has_permission error hides that doctype rather than exposing it."""
	user = user or frappe.session.user
	verdicts: dict[str, bool] = {}

	def can_read(doctype: str | None) -> bool:
		# Unkeyed entries (a report with no ref_doctype, the "" script bucket)
		# name no doctype, so there is nothing to leak - they pass.
		if not doctype:
			return True
		if doctype not in verdicts:
			try:
				verdicts[doctype] = bool(
					frappe.has_permission(doctype, ptype="read", user=user)
				)
			except Exception:
				verdicts[doctype] = False
		return verdicts[doctype]

	return {
		"apps": list(data.get("apps") or []),
		"modules": dict(data.get("modules") or {}),
		"custom_doctypes": [
			d for d in (data.get("custom_doctypes") or []) if can_read(d.get("name"))
		],
		"core_customizations": [
			c for c in (data.get("core_customizations") or []) if can_read(c.get("doctype"))
		],
		"workflows": [
			w for w in (data.get("workflows") or []) if can_read(w.get("doctype"))
		],
		"reports": [
			r for r in (data.get("reports") or []) if can_read(r.get("doctype"))
		],
		"print_formats": [
			p for p in (data.get("print_formats") or []) if can_read(p.get("doctype"))
		],
		"scripts": {
			"server": {
				k: v
				for k, v in ((data.get("scripts") or {}).get("server") or {}).items()
				if can_read(k)
			},
			"client": {
				k: v
				for k, v in ((data.get("scripts") or {}).get("client") or {}).items()
				if can_read(k)
			},
		},
	}
