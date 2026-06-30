import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError

TABLE_FIELDTYPES = {"Table", "Table MultiSelect"}
_SCHEMA_TTL = 300  # seconds; schema is user-independent + changes rarely


def _field_record(f) -> dict:
	"""Per-field response shape. Five keys, all load-bearing:

	- ``fieldname`` / ``fieldtype`` / ``label``: identity + type + human label.
	- ``options``: target DocType for Link / Table / Table MultiSelect /
	  Dynamic Link fields; enum values (newline-separated) for Select fields.
	  Empty string for primitive fields. Without it Link/Select/Table fields
	  are opaque - the agent can't follow them, filter on enum values, or
	  ``get_schema`` the child DocType.
	- ``reqd``: whether the field is mandatory on insert. Essential for write
	  paths (create_doc / update_doc); cheap on reads.
	"""
	return {
		"fieldname": f.fieldname,
		"fieldtype": f.fieldtype,
		"label": f.label,
		"options": f.options,
		"reqd": bool(f.reqd),
	}


def _workflow_for(doctype: str):
	"""The active Workflow's states for ``doctype``, or None. Live
	introspection so the agent reads the real state machine instead of a
	(possibly drifted) Skill note."""
	wf = frappe.db.get_value("Workflow", {"document_type": doctype, "is_active": 1}, "name")
	if not wf:
		return None
	doc = frappe.get_doc("Workflow", wf)
	return {
		"name": wf,
		"state_field": doc.workflow_state_field,
		"states": [s.state for s in doc.states],
	}


def _build_schema(doctype: str, verbose: bool) -> dict:
	meta = frappe.get_meta(doctype)
	fields = []
	for f in meta.fields:
		record = _field_record(f)
		if verbose and f.fieldtype in TABLE_FIELDTYPES and f.options:
			child_meta = frappe.get_meta(f.options)
			record["child_fields"] = [_field_record(cf) for cf in child_meta.fields]
		fields.append(record)
	return {
		"doctype": doctype,
		"is_submittable": bool(meta.is_submittable),
		"autoname": meta.autoname,
		"naming_rule": getattr(meta, "naming_rule", None),
		"title_field": meta.title_field,
		"workflow": _workflow_for(doctype),
		"fields": fields,
	}


def _as_bool(value) -> bool:
	"""Coerce a possibly-stringified flag to bool. A JSON client may send
	``"false"``/``"0"``; ``bool("false")`` is True, so treat common falsy
	strings as False rather than trusting plain ``bool()``."""
	if isinstance(value, str):
		return value.strip().lower() in ("1", "true", "yes", "on")
	return bool(value)


def clear_cache_for(doctype: str) -> None:
	"""Drop both cached schema variants (slim + verbose) for a DocType."""
	cache = frappe.cache()
	cache.delete_value(f"jarvis_schema:{doctype}:0")
	cache.delete_value(f"jarvis_schema:{doctype}:1")


def clear_schema_cache(doc, method=None) -> None:
	"""doc_event handler (wired in hooks.py): when a schema-defining doc is
	saved or trashed, bust the cached schema for the DocType it affects so the
	agent never builds a write off a stale field list within the TTL window."""
	dtype = getattr(doc, "doctype", None)
	dt = None
	if dtype == "DocType":
		dt = doc.name
	elif dtype == "Custom Field":
		dt = getattr(doc, "dt", None)
	elif dtype == "Property Setter":
		dt = getattr(doc, "doc_type", None)
	elif dtype == "Workflow":
		dt = getattr(doc, "document_type", None)
	if dt:
		clear_cache_for(dt)


def get_schema(doctype: str, verbose: bool = False, refresh: bool = False) -> dict:
	"""Return live meta for a DocType: identity + the write-relevant
	doctype-level flags + the field list.

	Top level: ``doctype``, ``is_submittable`` (docstatus lifecycle applies),
	``autoname`` / ``naming_rule`` (how name is assigned), ``title_field``,
	``workflow`` ({name, state_field, states} or None), and ``fields``.
	Every field record carries ``fieldname``, ``fieldtype``, ``label``,
	``options`` (Link target / Select enum / child DocType), and ``reqd``.

	By default Table / Table MultiSelect fields surface as ordinary records
	(child DocType named via ``options``) WITHOUT recursive ``child_fields`` -
	the agent calls ``get_schema`` on the child when it needs that list (cheap;
	keeps transcripts small). Pass ``verbose=True`` to inline each child's
	schema in one call (one level only; Frappe forbids nested tables). The
	slim default is the durable fix for the 2026-06-22 gpt-5.5 context overflow
	where 8 recursive schema dumps overran the model.

	Result is cached in Redis for ~5 min (schema is the same for every user).
	The cache is busted automatically when a Custom Field / Property Setter /
	DocType / Workflow change fires its doc_event (see hooks.py), so a
	customization shows up immediately rather than after the TTL. The
	read-permission check below runs on EVERY call regardless of cache, so
	caching never leaks a schema to a user who can't read the DocType. Pass
	``refresh=True`` to force a re-read (busts both slim + verbose variants).

	Enforces read permission on the parent DocType for the current user. Child
	tables (under ``verbose=True``) are part of the parent, not checked
	separately.
	"""
	verbose = _as_bool(verbose)
	refresh = _as_bool(refresh)

	if not doctype:
		raise InvalidArgumentError("doctype is required")

	if not frappe.db.exists("DocType", doctype):
		raise InvalidArgumentError(f"unknown DocType: {doctype}")

	if not frappe.has_permission(doctype, ptype="read"):
		raise PermissionDeniedError(f"no read permission on {doctype}")

	cache = frappe.cache()
	key = f"jarvis_schema:{doctype}:{int(verbose)}"
	if refresh:
		clear_cache_for(doctype)  # bust BOTH variants, not just the current one
	else:
		cached = cache.get_value(key)
		if cached is not None:
			return cached
	result = _build_schema(doctype, verbose)
	cache.set_value(key, result, expires_in_sec=_SCHEMA_TTL)
	return result
