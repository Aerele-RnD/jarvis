"""Discover the whitelisted server methods a DocType's form exposes as custom
buttons, so the agent knows what ``run_method`` can call for that doctype
instead of guessing dotted paths.

Best-effort + fail-safe: this is a DISCOVERY hint, not an allowlist. We read the
DocType's assembled form JS (the canonical ``<dt>.js`` + regional override +
cross-app ``doctype_js`` hooks + enabled ``Client Script`` (Form) rows - all
unioned for us by Frappe's ``FormMeta``) and scrape the dotted ``method:`` string
literals that ``frappe.call`` / ``frappe.xcall`` / ``open_mapped_doc`` /
``map_current_doc`` pass, then keep only the ones that resolve to a real
``@frappe.whitelist()`` function (the same gate ``run_method`` enforces). A
missed method just means one fewer hint - the agent falls back to its own
knowledge and the ``unknown method`` error loop - so incompleteness is fine and
this module never raises.

Only PATH-A methods (module-level, full dotted path) are surfaced: those are
exactly what ``run_method`` can call. Relative doc-methods (bare names dispatched
via ``run_doc_method``) are intentionally skipped - surfacing a method the agent
cannot actually call would only waste a turn.
"""

from __future__ import annotations

import inspect
import re

import frappe

# `method: "a.b.c"` as passed to frappe.call / open_mapped_doc / map_current_doc,
# and `xcall("a.b.c")`. We keep only DOTTED names below (a real module path);
# bare relative names are doc-methods run_method can't reach.
_METHOD_KEY_RE = re.compile(r"""method\s*:\s*["']([\w.]+)["']""")
_XCALL_RE = re.compile(r"""\.xcall\(\s*["']([\w.]+)["']""")

# Cap the list so a pathological form can't bloat the model context (get_schema
# already trims for exactly this reason).
_MAX_ACTIONS = 25

# Bound how many DISTINCT candidates we resolve (each `frappe.get_attr` imports a
# module; failed imports aren't cached). A pathological/large Client Script can't
# turn one cache-miss get_schema into thousands of import attempts. Real forms
# have a few dozen; this only bites abuse.
_MAX_CANDIDATES = 200


def get_doc_actions(doctype: str) -> list[dict]:
	"""Up to ``_MAX_ACTIONS`` whitelisted server methods this DocType's form
	exposes as buttons, each ``{"method", "label", "args"}``. Never raises -
	returns ``[]`` on any failure or when nothing usable is found."""
	try:
		js = _assembled_form_js(doctype)
		if not js:
			return []
		installed_apps = frozenset(frappe.get_installed_apps())
		seen: set[str] = set()
		actions: list[dict] = []
		for dotted in _iter_candidates(js):
			if dotted in seen:
				continue
			seen.add(dotted)
			if len(seen) > _MAX_CANDIDATES:
				break
			try:
				entry = _validated_action(dotted, installed_apps)
			except Exception:
				# One odd candidate must never sink the whole batch.
				continue
			if entry is not None:
				actions.append(entry)

		actions.sort(key=_sort_key(doctype))
		return actions[:_MAX_ACTIONS]
	except Exception:
		# Fail-safe: any unexpected error (FormMeta, get_installed_apps, ...)
		# degrades to no hint rather than breaking the caller.
		return []


def _sort_key(doctype: str):
	"""Stable ordering that keeps the DocType's OWN actions ahead of foreign ones
	when the cap bites: e.g. on Sales Order, ``...sales_order.mapper.make_*`` sorts
	before ``...purchase_order...make_inter_company_sales_order``. Alphabetical
	within each group so rebuilds are byte-identical (cache-friendly)."""
	own_segment = frappe.scrub(doctype)

	def key(action: dict):
		is_own = own_segment in action["method"].split(".")
		return (0 if is_own else 1, action["method"])

	return key


def _assembled_form_js(doctype: str) -> str:
	"""The DocType's full client form script, unioned across the canonical
	``<dt>.js``, regional override, cross-app ``doctype_js`` hooks and enabled
	``Client Script`` (Form) rows - exactly what Frappe ships to the form.
	``FormMeta`` skips asset loading for child tables, so those yield empty JS."""
	from frappe.desk.form.meta import get_meta as get_form_meta

	meta = get_form_meta(doctype)
	return (meta.get("__js") or "") + "\n" + (meta.get("__custom_js") or "")


def _iter_candidates(js: str):
	"""Yield the DOTTED method names referenced in the form JS. Dotted == a
	module-level function (path-a, ``run_method``-callable); bare names are
	relative doc-methods (path-b) and are skipped."""
	for regex in (_METHOD_KEY_RE, _XCALL_RE):
		for match in regex.finditer(js):
			name = match.group(1)
			if "." in name:
				yield name


def _validated_action(dotted: str, installed_apps) -> dict | None:
	"""Resolve ``dotted`` and confirm it's a real whitelisted method, dropping
	scrape false-positives and not-installed-app references. Returns None if it
	isn't callable via ``run_method``.

	Deliberately avoids the throwing APIs ``run_method`` uses at call time
	(``frappe.get_attr`` on an uninstalled app and ``frappe.is_whitelisted`` on a
	non-whitelisted fn both ``frappe.throw``, which appends to ``message_log``
	*before* raising - the caught exception doesn't unwind that, so it would leak
	stray ``_server_messages`` on every cache-miss get_schema). The installed-app
	pre-check mirrors ``get_attr``'s own gate, and membership in
	``frappe.whitelisted`` is exactly what ``is_whitelisted`` tests - minus the
	throw."""
	if dotted.split(".", 1)[0] not in installed_apps:
		return None
	try:
		fn = frappe.get_attr(dotted)
	except (AttributeError, ImportError):
		return None
	if fn not in frappe.whitelisted:
		return None
	return {
		"method": dotted,
		"label": _humanize(dotted),
		"args": _arg_names(fn),
	}


def _arg_names(fn) -> list[str]:
	"""Positional/keyword parameter names, so the agent knows what to pass. Skips
	``*args``/``**kwargs``; empty on un-introspectable builtins."""
	try:
		params = inspect.signature(fn).parameters
	except (TypeError, ValueError):
		return []
	return [
		name
		for name, p in params.items()
		if p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
	]


def _humanize(dotted: str) -> str:
	"""``erpnext...make_sales_invoice`` -> ``Make Sales Invoice``. A readable
	nicety; the dotted ``method`` is the load-bearing value."""
	tail = dotted.rsplit(".", 1)[-1]
	return tail.replace("_", " ").strip().title()
