"""Render a site's customization inventory into a budgeted markdown index.

The caller (site_profile/collect.py, not this module) walks the DB and hands
us a plain dict of custom apps/doctypes/customizations/workflows/reports/
print-formats/scripts. This module is PURE (no frappe import, no DB) so the
shed ladder and truncation math are unit-testable without a site.

The rendered doc is an INDEX for the agent, not a schema dump - it tells the
agent WHAT exists so it knows to call jarvis__get_schema before touching it.
Because the doc rides in every turn's context, the ``## How to go deeper``
recipe section is reserved first: it is never collapsed or dropped, and every
other section sheds detail through six tiers before the floor tier's
"+N more modules" line gives an unconditional size guarantee.
"""

DEFAULT_BUDGET = 18000
EMPTY_MESSAGE = "No customizations detected - standard ERPNext. Use the standard skills and `get_schema`."

_SCOPE_TO_KEY = {
	"doctypes": "custom_doctypes",
	"custom_fields": "core_customizations",
	"workflows": "workflows",
	"reports": "reports",
	"print_formats": "print_formats",
}

_TITLE = "# This site's customizations (live index)"
_GUIDANCE = (
	"This is an INDEX, not a schema dump. Always call jarvis__get_schema before "
	"reading or writing any doctype listed here."
)
_RECIPE = (
	"## How to go deeper\n"
	"For field-level truth call jarvis__get_schema('<DocType>'); to find records use "
	"jarvis__get_list / jarvis__query; do not assume standard fields on customized doctypes."
)


def apply_scope_match(data: dict, scopes: set[str] | None, match: str | None) -> dict:
	"""Filter ``data`` (same shape, a NEW dict) down to the requested ``scopes``
	and/or a case-insensitive substring ``match``. ``scopes=None`` keeps every
	section; otherwise unselected sections become empty. ``modules`` is kept
	whenever "apps" or "doctypes" is selected (doctype grouping needs it)."""
	out = {
		"apps": list(data.get("apps") or []),
		"modules": dict(data.get("modules") or {}),
		"custom_doctypes": list(data.get("custom_doctypes") or []),
		"core_customizations": list(data.get("core_customizations") or []),
		"workflows": list(data.get("workflows") or []),
		"reports": list(data.get("reports") or []),
		"print_formats": list(data.get("print_formats") or []),
		"scripts": {
			"server": dict((data.get("scripts") or {}).get("server") or {}),
			"client": dict((data.get("scripts") or {}).get("client") or {}),
		},
	}

	if scopes is not None:
		if "apps" not in scopes:
			out["apps"] = []
		for scope, key in _SCOPE_TO_KEY.items():
			if scope not in scopes:
				out[key] = []
		if "scripts" not in scopes:
			out["scripts"] = {"server": {}, "client": {}}
		if not ({"apps", "doctypes"} & scopes):
			out["modules"] = {}

	if match:
		out["apps"] = [a for a in out["apps"] if match in (a or "").lower()]
		out["custom_doctypes"] = [
			d
			for d in out["custom_doctypes"]
			if match in (d.get("name") or "").lower() or match in (d.get("module") or "").lower()
		]
		out["core_customizations"] = [
			c
			for c in out["core_customizations"]
			if match in (c.get("doctype") or "").lower()
			or any(match in (f or "").lower() for f in c.get("notable_fields") or [])
		]
		out["workflows"] = [
			w
			for w in out["workflows"]
			if match in (w.get("name") or "").lower() or match in (w.get("doctype") or "").lower()
		]
		out["reports"] = [
			r
			for r in out["reports"]
			if match in (r.get("name") or "").lower() or match in (r.get("doctype") or "").lower()
		]
		out["print_formats"] = [
			p
			for p in out["print_formats"]
			if match in (p.get("name") or "").lower() or match in (p.get("doctype") or "").lower()
		]
		out["scripts"] = {
			lang: {k: v for k, v in bucket.items() if match in (k or "").lower()}
			for lang, bucket in out["scripts"].items()
		}

	return out


def render_profile_md(data: dict, budget: int = DEFAULT_BUDGET, empty_message: str = EMPTY_MESSAGE) -> str:
	"""Render ``data`` into markdown that never exceeds ``budget`` bytes.

	Tries tiers 0 (full detail) through 6 (module rollups only), first fit
	wins. If tier 6 still doesn't fit, the module rollup list itself is
	truncated with a "+N more modules" line - an unconditional size guarantee
	that never cuts mid-line.
	"""
	if _is_empty(data):
		return empty_message
	for tier in range(7):
		doc = _build(data, tier)
		if len(doc) <= budget:
			return doc
	# Both the apps section's "(modules: ...)" list and the floor doctypes
	# rollup enumerate the same module names, so a pathological module count
	# can blow the budget from either side. Shrink both in lockstep, widest
	# first, so the guarantee holds regardless of which one dominates.
	total_modules = len(data.get("modules") or {})
	doc = _build(data, 6)
	for limit in range(total_modules - 1, -1, -1):
		doc = _build(data, 6, module_limit=limit)
		if len(doc) <= budget:
			return doc
	return doc  # last resort: budget smaller than the fixed recipe/title cost


def _is_empty(data: dict) -> bool:
	if (
		data.get("apps")
		or data.get("custom_doctypes")
		or data.get("core_customizations")
		or data.get("workflows")
		or data.get("reports")
		or data.get("print_formats")
	):
		return False
	scripts = data.get("scripts") or {}
	return not (scripts.get("server") or scripts.get("client"))


def _build(data: dict, tier: int, module_limit: int | None = None) -> str:
	parts = [_TITLE, "", _GUIDANCE]
	sections = [
		_custom_apps_section(data, module_limit),
		_custom_doctypes_section(data, tier, module_limit),
		_core_customizations_section(data, tier),
		_workflows_section(data, tier),
		_reports_section(data, tier),
		_print_formats_and_scripts_section(data, tier),
	]
	for section in sections:
		if section:
			parts.append("")
			parts.append(section)
	parts.append("")
	parts.append(_RECIPE)
	return "\n".join(parts) + "\n"


def _custom_apps_section(data: dict, module_limit: int | None = None) -> str | None:
	apps = data.get("apps") or []
	if not apps:
		return None
	modules = data.get("modules") or {}
	by_app: dict = {}
	for mod, app in modules.items():
		by_app.setdefault(app, []).append(mod)
	lines = ["## Custom apps"]
	for app in apps:
		mods = sorted(by_app.get(app, []))
		if not mods:
			lines.append(f"- {app}")
			continue
		if module_limit is not None and len(mods) > module_limit:
			shown = mods[:module_limit]
			extra = len(mods) - module_limit
			names = ", ".join(shown) if shown else ""
			sep = ", " if shown else ""
			lines.append(f"- {app} (modules: {names}{sep}+{extra} more)")
		else:
			lines.append(f"- {app} (modules: {', '.join(mods)})")
	return "\n".join(lines)


def _group_doctypes_by_module(doctypes: list, modules: dict) -> list:
	"""Group ``doctypes`` by module, named modules (alphabetical) first, then
	a single "Other customizations" bucket for doctypes whose module isn't in
	``modules`` (UI-authored custom=1 doctypes filed under a core module).
	Returns a list of ``(label, app_or_None, items)`` tuples."""
	named: dict = {}
	other = []
	for d in doctypes:
		mod = d.get("module")
		if mod in modules:
			named.setdefault(mod, []).append(d)
		else:
			other.append(d)
	groups = [(mod, modules[mod], named[mod]) for mod in sorted(named)]
	if other:
		groups.append(("Other customizations", None, other))
	return groups


def _workflow_lookup(data: dict) -> dict:
	"""doctype -> workflow name, first match wins when a doctype has more than one."""
	lookup: dict = {}
	for w in data.get("workflows") or []:
		dt = w.get("doctype")
		if dt and dt not in lookup:
			lookup[dt] = w.get("name")
	return lookup


def _doctype_line(d: dict, workflow_by_doctype: dict) -> str:
	ann = []
	if d.get("is_submittable"):
		ann.append("submittable")
	if d.get("issingle"):
		ann.append("single")
	if d.get("istable"):
		ann.append("child table")
	wf = workflow_by_doctype.get(d.get("name"))
	if wf:
		ann.append(f"workflow: {wf}")
	if ann:
		return f"- {d['name']} - {', '.join(ann)}"
	return f"- {d['name']}"


def _custom_doctypes_section(data: dict, tier: int, module_limit: int | None = None) -> str | None:
	doctypes = data.get("custom_doctypes") or []
	if not doctypes:
		return None
	groups = _group_doctypes_by_module(doctypes, data.get("modules") or {})
	lines = ["## Custom DocTypes (by module)"]

	if tier >= 6:
		shown = groups if module_limit is None else groups[:module_limit]
		for mod, app, items in shown:
			label = f"{mod} ({app})" if app else mod
			lines.append(f"- {label}: {len(items)} doctypes")
		if module_limit is not None and module_limit < len(groups):
			lines.append(f"- ... +{len(groups) - module_limit} more modules")
		return "\n".join(lines)

	if tier >= 5:
		for mod, app, items in groups:
			label = f"{mod} ({app})" if app else mod
			names = ", ".join(d["name"] for d in items)
			lines.append(f"### {label} - {len(items)} doctypes: {names}")
		return "\n".join(lines)

	workflow_by_doctype = _workflow_lookup(data)
	for mod, app, items in groups:
		label = f"{mod} ({app})" if app else mod
		lines.append(f"### {label} - {len(items)} doctypes")
		for d in items:
			lines.append(_doctype_line(d, workflow_by_doctype))
	return "\n".join(lines)


def _core_customization_line(c: dict, tier: int) -> str:
	line = f"- {c.get('doctype')}: {c.get('custom_field_count', 0)} custom fields"
	notable = c.get("notable_fields") or []
	if notable and tier < 4:
		line += f" (notable: {', '.join(notable)})"
	ps = c.get("property_setter_count", 0)
	if ps:
		line += f" (+{ps} property setters)"
	return line


def _core_customizations_section(data: dict, tier: int) -> str | None:
	items = data.get("core_customizations") or []
	if not items:
		return None
	lines = ["## Customized core doctypes (Custom Fields)"]
	if tier >= 6:
		lines.append(f"- Custom fields on {len(items)} core doctypes")
		return "\n".join(lines)
	for c in items:
		lines.append(_core_customization_line(c, tier))
	return "\n".join(lines)


def _workflows_section(data: dict, tier: int) -> str | None:
	items = data.get("workflows") or []
	if not items:
		return None
	lines = ["## Active workflows"]
	if tier >= 6:
		lines.append(f"- {len(items)} active workflows")
		return "\n".join(lines)
	for w in items:
		states = " -> ".join(w.get("states") or [])
		lines.append(f"- {w.get('name')} on {w.get('doctype')} ({states})")
	return "\n".join(lines)


def _reports_section(data: dict, tier: int) -> str | None:
	items = data.get("reports") or []
	if not items:
		return None
	lines = ["## Custom reports"]
	if tier >= 3:
		lines.append(f"- {len(items)} custom reports")
		return "\n".join(lines)
	for r in items:
		lines.append(f"- {r.get('name')} ({r.get('report_type')}, on {r.get('doctype')})")
	return "\n".join(lines)


def _print_formats_line(items: list) -> str:
	by_doctype: dict = {}
	for pf in items:
		by_doctype.setdefault(pf.get("doctype"), []).append(pf.get("name"))
	parts = [f"{dt} ({', '.join(names)})" for dt, names in by_doctype.items()]
	return "- Print formats: " + ", ".join(parts)


def _scripts_bucket_str(bucket: dict) -> str:
	return ", ".join(f"{key or '(unbound)'} ({count})" for key, count in bucket.items())


def _scripts_line(server: dict, client: dict) -> str:
	clauses = []
	if server:
		clauses.append(f"Server scripts on: {_scripts_bucket_str(server)}")
	if client:
		clauses.append(f"Client scripts on: {_scripts_bucket_str(client)}")
	return "- " + " . ".join(clauses)


def _print_formats_and_scripts_section(data: dict, tier: int) -> str | None:
	pf = data.get("print_formats") or []
	scripts = data.get("scripts") or {}
	server = scripts.get("server") or {}
	client = scripts.get("client") or {}
	if not pf and not server and not client:
		return None

	lines = ["## Custom print formats & scripts"]
	if pf:
		if tier >= 2:
			lines.append(f"- {len(pf)} custom print formats")
		else:
			lines.append(_print_formats_line(pf))
	if server or client:
		if tier >= 1:
			clauses = []
			if server:
				clauses.append(f"Server scripts on {len(server)} doctypes")
			if client:
				clauses.append(f"Client scripts on {len(client)} doctypes")
			lines.append("- " + " . ".join(clauses))
		else:
			lines.append(_scripts_line(server, client))
	return "\n".join(lines)
