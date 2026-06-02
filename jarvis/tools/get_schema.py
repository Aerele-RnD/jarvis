import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError

TABLE_FIELDTYPES = {"Table", "Table MultiSelect"}


def _field_record(f) -> dict:
	return {
		"fieldname": f.fieldname,
		"fieldtype": f.fieldtype,
		"label": f.label,
		"options": f.options,
		"reqd": bool(f.reqd),
	}


def get_schema(doctype: str) -> dict:
	"""Return meta for a DocType: name and field list.

	Child tables are expanded inline - each Table / Table MultiSelect field carries
	a `child_fields` list with the schema of the linked child DocType, so the agent
	gets the full hierarchy in one call. Frappe doesn't allow nested tables, so
	expansion depth is bounded at 1.

	Enforces read permission on the parent DocType for the current user. Child-table
	DocTypes are treated as part of the parent and are not permission-checked
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
		if f.fieldtype in TABLE_FIELDTYPES and f.options:
			child_meta = frappe.get_meta(f.options)
			record["child_fields"] = [_field_record(cf) for cf in child_meta.fields]
		fields.append(record)
	return {"doctype": doctype, "fields": fields}
