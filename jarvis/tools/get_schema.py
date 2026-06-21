import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError

TABLE_FIELDTYPES = {"Table", "Table MultiSelect"}


def _field_record_slim(f) -> dict:
	"""Minimum-token field shape: identifier, type, human label. This is
	the default response - enough for the agent to frame a get_list filter
	or a run_query column list without dumping the full Frappe meta into
	the transcript."""
	return {
		"fieldname": f.fieldname,
		"fieldtype": f.fieldtype,
		"label": f.label,
	}


def _field_record_full(f) -> dict:
	"""Full field shape: slim + options + reqd. Caller opts in via
	``verbose=True`` when the extra keys matter (write paths checking
	required, link-target inspection)."""
	return {
		"fieldname": f.fieldname,
		"fieldtype": f.fieldtype,
		"label": f.label,
		"options": f.options,
		"reqd": bool(f.reqd),
	}


def get_schema(doctype: str, verbose: bool = False) -> dict:
	"""Return meta for a DocType: name and field list.

	By default the response is the slim shape (``fieldname``,
	``fieldtype``, ``label`` per field) - enough for the agent to choose
	fields for a follow-up ``get_list`` or ``run_query``. Pass
	``verbose=True`` to include ``options`` (link targets, select choices)
	and ``reqd``; in that mode each Table / Table MultiSelect field also
	carries a ``child_fields`` list with the child DocType's slim shape
	(no recursion - Frappe doesn't allow nested tables).

	The slim default keeps transcripts small on big DocTypes (Employee
	alone has ~130 fields; the full shape pushed customers past their
	model's context window and forced auto-compaction). Operators
	triaging "is this field required" / "what does this link to" opt in
	with verbose for one call.

	Enforces read permission on the parent DocType for the current user.
	Child-table DocTypes are treated as part of the parent and are not
	permission-checked separately.
	"""
	if not doctype:
		raise InvalidArgumentError("doctype is required")

	if not frappe.db.exists("DocType", doctype):
		raise InvalidArgumentError(f"unknown DocType: {doctype}")

	if not frappe.has_permission(doctype, ptype="read"):
		raise PermissionDeniedError(f"no read permission on {doctype}")

	record_fn = _field_record_full if verbose else _field_record_slim

	meta = frappe.get_meta(doctype)
	fields = []
	for f in meta.fields:
		record = record_fn(f)
		if verbose and f.fieldtype in TABLE_FIELDTYPES and f.options:
			child_meta = frappe.get_meta(f.options)
			# Child fields use the same record shape as the parent. In the
			# slim default we don't expand child tables at all - the agent
			# can do a follow-up ``get_schema`` on the child DocType if
			# needed.
			record["child_fields"] = [_field_record_full(cf) for cf in child_meta.fields]
		fields.append(record)
	return {"doctype": doctype, "fields": fields}
