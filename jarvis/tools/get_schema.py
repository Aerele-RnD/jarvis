import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError

TABLE_FIELDTYPES = {"Table", "Table MultiSelect"}


def _field_record(f) -> dict:
	"""Per-field response shape. Five keys, all load-bearing:

	- ``fieldname`` / ``fieldtype`` / ``label``: identity + type +
	  human label.
	- ``options``: target DocType for Link / Table / Table MultiSelect /
	  Dynamic Link fields; enum values (newline-separated) for Select
	  fields. Empty string for primitive fields. Always included
	  because without it Link/Select/Table fields are opaque - the
	  agent can't follow them, can't filter on enum values, and can't
	  call ``get_schema`` on the child DocType.
	- ``reqd``: whether the field is mandatory on insert. Essential
	  for write paths (create_doc / update_doc); cheap on reads
	  (one bool per field).
	"""
	return {
		"fieldname": f.fieldname,
		"fieldtype": f.fieldtype,
		"label": f.label,
		"options": f.options,
		"reqd": bool(f.reqd),
	}


def get_schema(doctype: str, verbose: bool = False) -> dict:
	"""Return meta for a DocType: name and field list.

	Every field record carries ``fieldname``, ``fieldtype``, ``label``,
	``options``, and ``reqd``. The ``options`` value gives the agent
	the target DocType for Link fields, the enum values for Select
	fields, and the child DocType name for Table / Table MultiSelect
	fields. ``reqd`` is the mandatory flag the agent needs for writes.

	By default, Table / Table MultiSelect fields surface as ordinary
	records (with their child DocType named via ``options``) but
	WITHOUT the recursive ``child_fields`` expansion. The agent calls
	``get_schema`` on the child DocType when it needs the child's
	field list - that follow-up call is cheap, and the lazy expansion
	keeps transcripts from ballooning when the agent only cares about
	the parent.

	Pass ``verbose=True`` to inline each Table / Table MultiSelect
	field's child schema in the same call. Useful for operator triage
	("show me the full Sales Invoice + line-item structure in one
	shot") or when the agent needs to validate a write that touches
	parent + child in a single transaction. The child records use the
	same 5-key shape; no second level of recursion (Frappe doesn't
	allow nested tables).

	The slim-default + ``verbose=True`` toggle replaces the previous
	always-recurse behavior. The 2026-06-22 context-window failure on
	openai/gpt-5.5 (a chat where 8 schema dumps overflowed the model
	and openclaw's compaction tripped on a transport error) was
	driven by the recursive ``child_fields`` payload; trimming the
	recursion to opt-in is the durable fix. ``options`` and ``reqd``
	stay in the default because they carry semantic context
	(link/select targets, write-path requireds) that's cheap and
	useful.

	Enforces read permission on the parent DocType for the current
	user. Child-table DocTypes (when expanded under ``verbose=True``)
	are treated as part of the parent and are NOT permission-checked
	separately.
	"""
	if not doctype:
		raise InvalidArgumentError("doctype is required")

	if not frappe.db.exists("DocType", doctype):
		raise InvalidArgumentError(f"unknown DocType: {doctype}")

	if not frappe.has_permission(doctype, ptype="read"):
		raise PermissionDeniedError(f"no read permission on {doctype}")

	meta = frappe.get_meta(doctype)
	fields = []
	for f in meta.fields:
		record = _field_record(f)
		if verbose and f.fieldtype in TABLE_FIELDTYPES and f.options:
			child_meta = frappe.get_meta(f.options)
			record["child_fields"] = [_field_record(cf) for cf in child_meta.fields]
		fields.append(record)
	return {"doctype": doctype, "fields": fields}
