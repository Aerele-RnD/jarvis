"""App-level custom/core classification for customization discovery.

Single source of truth for "custom" at app granularity: get_schema's doctype
flag, collect.py's two-union doctype discovery, and the [Context:] clause all
ride these helpers so they can never disagree. Every function fails toward
"nothing custom" - misreporting a core app as custom would flood the index;
the reverse merely omits a hint.
"""

from __future__ import annotations

import re

import frappe

# The core stack the persona skill families already teach (india_compliance
# included - it ships the india-compliance family). Anything else installed on
# the site is treated as the customer's own app. Operators can extend this per
# site via Jarvis Settings ``core_apps_override``.
_KNOWN_APPS = frozenset({
	"frappe",
	"erpnext",
	"hrms",
	"india_compliance",
	"payments",
	"webshop",
	"insights",
	"wiki",
	"jarvis",
})

_SETTINGS = "Jarvis Settings"


def known_apps() -> frozenset[str]:
	"""``_KNOWN_APPS`` plus operator additions from ``core_apps_override``
	(comma/newline separated). Any read failure falls back to the constant."""
	try:
		settings = frappe.get_cached_doc(_SETTINGS)
		raw = (settings.get("core_apps_override") or "").strip()
	except Exception:
		return _KNOWN_APPS
	if not raw:
		return _KNOWN_APPS
	extra = {p.strip().lower() for p in re.split(r"[,\n]", raw) if p.strip()}
	return _KNOWN_APPS | frozenset(extra)


def _installed_apps() -> list[str]:
	"""Seam over frappe.get_installed_apps. Tests patch THIS, never the frappe
	function - the framework itself resolves hooks through get_installed_apps,
	so a global mock breaks every dict-filter query (AppNotInstalledError)."""
	return frappe.get_installed_apps()


def custom_apps() -> list[str]:
	"""Installed apps outside the known core stack, in install order.
	Empty on a vanilla site and on any failure."""
	try:
		installed = _installed_apps()
	except Exception:
		return []
	known = known_apps()
	return [a for a in installed if a and a.lower() not in known]


def custom_module_names() -> set[str]:
	"""Module Def names belonging to custom apps - the module->app mapping that
	classifies app-shipped (custom=0) doctypes. Empty when no custom apps."""
	apps = custom_apps()
	if not apps:
		return set()
	try:
		return set(
			frappe.get_all("Module Def", filters={"app_name": ("in", apps)}, pluck="name")
		)
	except Exception:
		return set()


def known_module_names() -> set[str]:
	"""Module Def names belonging to KNOWN (core) apps - the reverse mapping:
	a Custom Field row stamped with one of these modules is app-shipped fixture
	schema, not the customer's customization, even when its
	is_system_generated flag predates that column. Empty on failure (then only
	the is_system_generated filter applies - fail toward over-reporting)."""
	try:
		return set(
			frappe.get_all(
				"Module Def",
				filters={"app_name": ("in", sorted(known_apps()))},
				pluck="name",
			)
		)
	except Exception:
		return set()


def is_custom_doctype_module(module: str | None) -> bool:
	"""True iff ``module`` belongs to a custom app. Never raises."""
	if not module:
		return False
	try:
		return module in custom_module_names()
	except Exception:
		return False
