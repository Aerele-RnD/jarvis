"""Per-site customizations hint for the trusted ``[Context: ...]`` line.

Counts + app names ONLY - never doctype names. The clause is shown to every
user on the site (a context line is not user-fenced the way a tool result
is), so it may leak existence only at app/count granularity; names stay
behind the permission-fenced ``jarvis__describe_customizations`` tool this
clause points at.

Cached per site (flat key, short TTL as backstop) and invalidated by the
same doc_events that bust the schema cache - the clause deliberately counts
ONLY sources those events cover (custom doctypes, custom fields, workflows,
plus the installed-app list, which changes only via migrate and is refreshed
by after_migrate). Reports/print formats/scripts are counted by the TOOL but
not by this clause: their doc_events aren't wired, and a stale count in a
trusted system line is worse than a narrower clause.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

from jarvis.site_profile import apps as sp_apps

SETTINGS = "Jarvis Settings"
_CLAUSE_CACHE_KEY = "jarvis:customizations_clause"
_CLAUSE_TTL_S = 300
_CLAUSE_MAX_CHARS = 200

_DIRECTIVE = "call jarvis__describe_customizations before assuming standard fields"


def clause_enabled() -> bool:
	"""Operator toggle; NULL=ON. Same tabSingles probe as wiki_enabled - both
	a loaded Document and get_single_value coerce an unset Check to 0, which
	would break the default-on contract."""
	rows = frappe.db.sql(
		"select value from `tabSingles` where doctype=%s and field=%s",
		(SETTINGS, "enable_customizations_clause"),
	)
	if not rows or rows[0][0] is None:
		return True
	return bool(cint(rows[0][0]))


def customizations_clause() -> str:
	"""The clause (leading ``"; "``), ``""`` on a vanilla site, when the
	toggle is off, or when ANYTHING fails - never raises. Hot path: one
	tabSingles probe + one redis read; the build runs only on a cache miss."""
	try:
		if not clause_enabled():
			return ""
		cache = frappe.cache()
		cached = cache.get_value(_CLAUSE_CACHE_KEY)
		if cached is not None:
			return cached
		clause = _build_clause()
		cache.set_value(_CLAUSE_CACHE_KEY, clause, expires_in_sec=_CLAUSE_TTL_S)
		return clause
	except Exception:
		frappe.log_error(
			title="customizations clause build failed", message=frappe.get_traceback()
		)
		return ""


def _build_clause() -> str:
	apps = [_fold(a) for a in sp_apps.custom_apps()]
	modules = sp_apps.custom_module_names()
	n_doctypes, n_cf_doctypes, n_workflows = _counts(modules)
	if not apps and not n_doctypes and not n_cf_doctypes and not n_workflows:
		return ""

	counts = []
	if n_doctypes:
		counts.append(f"{n_doctypes} custom doctypes")
	if n_cf_doctypes:
		counts.append(f"custom fields on {n_cf_doctypes} core doctypes")
	if n_workflows:
		counts.append(f"{n_workflows} workflows")
	counts_part = ", ".join(counts)

	# Shrink ladder for the app list: full -> 2 shown -> 1 shown -> count
	# only. First variant within budget wins; the last is guaranteed tiny, so
	# the cap holds without ever slicing the directive mid-word.
	for shown in (len(apps), 2, 1, 0):
		clause = _compose(apps, shown, counts_part)
		if len(clause) <= _CLAUSE_MAX_CHARS:
			return clause
	return _compose(apps, 0, counts_part)


def _compose(apps: list[str], shown: int, counts_part: str) -> str:
	bits = []
	if apps:
		if shown <= 0:
			bits.append(f"{len(apps)} custom apps")
		elif len(apps) > shown:
			bits.append(
				f"custom app(s) {', '.join(apps[:shown])} +{len(apps) - shown} more"
			)
		else:
			bits.append(f"custom app(s) {', '.join(apps)}")
	if counts_part:
		bits.append(counts_part)
	return f"; site customizations: {' - '.join(bits)} - {_DIRECTIVE}"


def _counts(modules: set[str]) -> tuple[int, int, int]:
	"""(custom doctypes, core doctypes carrying custom fields, active
	workflows) - the same two-union + is_system_generated + known-module
	rules as site_profile/collect.py, reduced to counts."""
	names = set(frappe.get_all("DocType", filters={"custom": 1}, pluck="name"))
	if modules:
		names |= set(
			frappe.get_all(
				"DocType", filters={"module": ("in", list(modules))}, pluck="name"
			)
		)
	known_modules = sp_apps.known_module_names()
	cf_doctypes = {
		r["dt"]
		for r in frappe.get_all(
			"Custom Field",
			filters={"is_system_generated": 0},
			fields=["dt", "module"],
		)
		if r.get("dt") and r["dt"] not in names
		and not (r.get("module") and r["module"] in known_modules)
	}
	n_workflows = frappe.db.count("Workflow", {"is_active": 1})
	return len(names), len(cf_doctypes), cint(n_workflows)


def _fold(name: str) -> str:
	"""Neutralize an org-authored string entering the trusted bracket: app
	names are code slugs, but the fold is cheap insurance (no backticks, no
	bracket close, no clause forgery)."""
	text = " ".join(str(name or "").split())
	return text.replace("`", "'").replace("]", ")").replace(";", ",")


def clear_clause_cache(doc=None, method=None) -> None:
	"""doc_event handler (hooks.py, same events as clear_schema_cache) +
	manual invalidation hook. Never raises."""
	try:
		cache = frappe.cache()
		cache.delete_value(_CLAUSE_CACHE_KEY)
		# The telemetry custom-doctype set derives from the same schema
		# events, so it invalidates here too (lazy import: telemetry is
		# optional to this module's core job).
		from jarvis.telemetry import DOCTYPE_SET_CACHE_KEY

		cache.delete_value(DOCTYPE_SET_CACHE_KEY)
	except Exception:
		pass


def after_migrate() -> None:
	"""Recompute after migrate (the installed-app list only changes here).
	Best-effort: never blocks a migrate."""
	try:
		clear_clause_cache()
		customizations_clause()
	except Exception:
		frappe.log_error(
			title="customizations clause after_migrate failed",
			message=frappe.get_traceback(),
		)
