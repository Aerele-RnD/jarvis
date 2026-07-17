"""Read-only collection of THIS site's customization metadata.

Feeds describe_customizations, which fences the result per user. This module
is deliberately permission-FREE (frappe.get_all ignores permissions) so a
future generator can reuse it with an anonymizer instead of the fence - the
permission logic lives in fence.py and nowhere else.

Set-based queries only: no get_meta loops, no roles_for_doctype/get_all_perms
(O(roles) per doctype - a 400-doctype tenant would pay minutes). Everything
here is a handful of get_all calls over small metadata tables; grouping is
plain Python.

Output contract (fence.py filters items, render.py derives every count from
list lengths - there are NO precomputed totals to recompute; keys always
present):

	{
	  "apps": ["fleet_mgmt"],                # custom app names, install order
	  "modules": {"Fleet": "fleet_mgmt"},    # custom Module Def name -> app
	  "custom_doctypes": [{"name", "module", "istable", "issingle",
	                       "is_submittable"}, ...],          # name-sorted
	  "core_customizations": [{"doctype", "custom_field_count",
	                           "notable_fields": [<=5],
	                           "property_setter_count"}, ...],
	  "workflows": [{"name", "doctype", "states": [...]}, ...],
	  "reports": [{"name", "doctype", "report_type"}, ...],
	  "print_formats": [{"name", "doctype"}, ...],
	  "scripts": {"server": {ref_doctype_or_"": count},
	              "client": {dt: count}},
	}
"""

from __future__ import annotations

from collections import Counter

import frappe
from frappe.utils import cint

from jarvis.site_profile import apps as sp_apps

# Cap the notable-fieldname list per core doctype: enough to orient the agent,
# never a field dump (get_schema is the field dump).
_MAX_NOTABLE_FIELDS = 5


def collect_profile() -> dict:
	custom_apps = sp_apps.custom_apps()
	modules = _module_map(custom_apps)
	custom_doctypes = _custom_doctypes(modules)
	custom_dt_names = {d["name"] for d in custom_doctypes}
	return {
		"apps": custom_apps,
		"modules": modules,
		"custom_doctypes": custom_doctypes,
		"core_customizations": _core_customizations(custom_dt_names),
		"workflows": _workflows(),
		"reports": _custom_reports(modules),
		"print_formats": _print_formats(modules),
		"scripts": _scripts_summary(custom_dt_names),
	}


def _module_map(custom_apps: list[str]) -> dict[str, str]:
	if not custom_apps:
		return {}
	rows = frappe.get_all(
		"Module Def",
		filters={"app_name": ("in", custom_apps)},
		fields=["name", "app_name"],
		limit_page_length=0,
	)
	return {r["name"]: r["app_name"] for r in rows}


def _custom_doctypes(modules: dict[str, str]) -> list[dict]:
	"""Two unions: UI-authored (custom=1) plus doctypes whose module belongs to
	a custom app - app-shipped doctypes have custom=0, so the naive custom=1
	filter misses exactly the case that matters most."""
	fields = ["name", "module", "istable", "issingle", "is_submittable"]
	seen: dict[str, dict] = {}
	filter_sets = [{"custom": 1}]
	if modules:
		filter_sets.append({"module": ("in", list(modules))})
	for filters in filter_sets:
		for row in frappe.get_all(
			"DocType", filters=filters, fields=fields, limit_page_length=0
		):
			row = dict(row)
			for flag in ("istable", "issingle", "is_submittable"):
				row[flag] = cint(row.get(flag))
			seen[row["name"]] = row
	return sorted(seen.values(), key=lambda d: d["name"])


def _core_customizations(custom_dt_names: set[str]) -> list[dict]:
	"""Custom Fields + Property Setters per CORE doctype. Excludes
	is_system_generated rows (app-shipped fixture fields - e.g. a compliance
	app's fields on Customer - are the app's own schema, not this customer's
	customization) and rows on custom doctypes (their fields are just their
	schema - get_schema territory)."""
	cf_rows = frappe.get_all(
		"Custom Field",
		filters={"is_system_generated": 0},
		fields=["dt", "fieldname", "reqd", "in_list_view", "hidden", "fieldtype"],
		order_by="dt asc, idx asc",
		limit_page_length=0,
	)
	by_dt: dict[str, dict] = {}
	for row in cf_rows:
		dt = row.get("dt")
		if not dt or dt in custom_dt_names:
			continue
		entry = by_dt.setdefault(
			dt, {"doctype": dt, "custom_field_count": 0, "notable_fields": [],
				"property_setter_count": 0}
		)
		entry["custom_field_count"] += 1
		if len(entry["notable_fields"]) < _MAX_NOTABLE_FIELDS and _is_notable(row):
			entry["notable_fields"].append(row["fieldname"])

	ps_counts = Counter(
		r["doc_type"]
		for r in frappe.get_all(
			"Property Setter", fields=["doc_type"], limit_page_length=0
		)
		if r.get("doc_type") and r["doc_type"] not in custom_dt_names
	)
	for dt, n in ps_counts.items():
		entry = by_dt.setdefault(
			dt, {"doctype": dt, "custom_field_count": 0, "notable_fields": [],
				"property_setter_count": 0}
		)
		entry["property_setter_count"] = n
	return sorted(by_dt.values(), key=lambda e: e["doctype"])


def _is_notable(row: dict) -> bool:
	if cint(row.get("reqd")) or cint(row.get("in_list_view")):
		return True
	return not cint(row.get("hidden")) and row.get("fieldtype") in ("Link", "Select")


def _workflows() -> list[dict]:
	wf_rows = frappe.get_all(
		"Workflow",
		filters={"is_active": 1},
		fields=["name", "document_type"],
		order_by="name asc",
		limit_page_length=0,
	)
	if not wf_rows:
		return []
	states = frappe.get_all(
		"Workflow Document State",
		filters={"parent": ("in", [w["name"] for w in wf_rows]), "parenttype": "Workflow"},
		fields=["parent", "state"],
		order_by="idx asc",
		limit_page_length=0,
	)
	states_by_wf: dict[str, list[str]] = {}
	for s in states:
		states_by_wf.setdefault(s["parent"], []).append(s["state"])
	return [
		{"name": w["name"], "doctype": w.get("document_type") or "",
			"states": states_by_wf.get(w["name"], [])}
		for w in wf_rows
	]


def _custom_reports(modules: dict[str, str]) -> list[dict]:
	"""Operator-created reports (is_standard='No') plus reports SHIPPED by a
	custom app (is_standard='Yes' but module belongs to it) - same two-union
	reasoning as doctypes."""
	seen: dict[str, dict] = {}
	filter_sets = [{"is_standard": "No", "disabled": 0}]
	if modules:
		filter_sets.append({"module": ("in", list(modules)), "disabled": 0})
	for filters in filter_sets:
		for row in frappe.get_all(
			"Report",
			filters=filters,
			fields=["name", "ref_doctype", "report_type"],
			limit_page_length=0,
		):
			seen[row["name"]] = {
				"name": row["name"],
				"doctype": row.get("ref_doctype") or "",
				"report_type": row.get("report_type") or "",
			}
	return sorted(seen.values(), key=lambda r: r["name"])


def _print_formats(modules: dict[str, str]) -> list[dict]:
	seen: dict[str, dict] = {}
	filter_sets = [{"standard": "No", "disabled": 0}]
	if modules:
		filter_sets.append({"module": ("in", list(modules)), "disabled": 0})
	for filters in filter_sets:
		for row in frappe.get_all(
			"Print Format",
			filters=filters,
			fields=["name", "doc_type"],
			limit_page_length=0,
		):
			seen[row["name"]] = {"name": row["name"], "doctype": row.get("doc_type") or ""}
	return sorted(seen.values(), key=lambda p: p["name"])


def _scripts_summary(custom_dt_names: set[str]) -> dict:
	"""Existence counts only - script names/bodies never enter the index.
	The empty-string bucket collects scripts not tied to a doctype (API
	scripts, scheduler events); it carries nothing to fence."""
	server = Counter()
	for row in frappe.get_all(
		"Server Script",
		filters={"disabled": 0},
		fields=["script_type", "reference_doctype"],
		limit_page_length=0,
	):
		key = row.get("reference_doctype") or ""
		if key in custom_dt_names:
			continue  # scripts on custom doctypes are part of that doctype's story
		server[key] += 1
	client = Counter()
	for row in frappe.get_all(
		"Client Script", filters={"enabled": 1}, fields=["dt"], limit_page_length=0
	):
		key = row.get("dt") or ""
		if key in custom_dt_names:
			continue
		client[key] += 1
	return {"server": dict(server), "client": dict(client)}
