"""Direct apply for chat action cards (the record draft panel).

The agent emits a ``jarvis-action`` block; the SPA renders it in a side-panel
editor and posts the FINAL values here — no LLM turn in the apply path. All
mutations route through the existing permission-checked tools
(``jarvis.tools.create_doc`` etc.), so this module adds routing + a receipt,
not a second write path.
"""

import frappe
from frappe import _

from jarvis.chat.api import _NON_EDIT_FIELDTYPES, _next_seq
from jarvis.exceptions import InvalidArgumentError

MSG = "Jarvis Chat Message"
CONV = "Jarvis Conversation"

# Child-grid columns can be any data-bearing fieldtype except nested tables
# (no grid-in-grid in v1).
_SKIP_CHILD_FIELDTYPES = _NON_EDIT_FIELDTYPES | {"Table", "Table MultiSelect"}


def _field_dict(df) -> dict:
	return {
		"fieldname": df.fieldname,
		"label": df.label or df.fieldname,
		"fieldtype": df.fieldtype,
		"options": df.options or "",
		"reqd": int(df.reqd or 0),
		"read_only": int(df.read_only or 0),
	}


def _child_columns(child_doctype: str) -> list[dict]:
	"""Grid columns for one child table: the child's in_list_view fields (what
	the Desk grid shows), falling back to the first 4 editable fields when the
	child marks none."""
	meta = frappe.get_meta(child_doctype)
	editable = [
		df for df in meta.fields
		if df.fieldname and df.fieldtype not in _SKIP_CHILD_FIELDTYPES
	]
	listed = [df for df in editable if df.in_list_view]
	return [_field_dict(df) for df in (listed or editable[:4])]


@frappe.whitelist()
def get_doctype_form_meta(doctype: str) -> dict:
	"""Form metadata for the draft panel: main fields INCLUDING Table fields,
	plus per-table child columns — one call, so the panel never fans out.
	Gated on read permission of the parent (child meta rides on that gate)."""
	doctype = (doctype or "").strip()
	if not doctype or not frappe.db.exists("DocType", doctype):
		return {"ok": False, "reason": _("unknown doctype")}
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("You don't have access to {0}.").format(doctype), frappe.PermissionError)
	meta = frappe.get_meta(doctype)
	fields, tables = [], {}
	for df in meta.fields:
		if not df.fieldname:
			continue
		if df.fieldtype == "Table" and df.options:
			fields.append(_field_dict(df))
			tables[df.fieldname] = {
				"child_doctype": df.options,
				"label": df.label or df.fieldname,
				"columns": _child_columns(df.options),
			}
			continue
		if df.fieldtype in _NON_EDIT_FIELDTYPES:
			continue
		fields.append(_field_dict(df))
	return {
		"ok": True,
		"doctype": doctype,
		"is_submittable": int(meta.is_submittable or 0),
		"title_field": meta.get("title_field") or "",
		"fields": fields,
		"tables": tables,
	}


@frappe.whitelist()
def load_doc(doctype: str, name: str) -> dict:
	"""Current values of one document (main fields + child rows restricted to
	the form-meta columns) so the panel can pre-fill an update draft. Gated on
	WRITE permission — this endpoint exists to edit."""
	doctype = (doctype or "").strip()
	name = (name or "").strip()
	if not doctype or not name:
		raise InvalidArgumentError("doctype and name are required")
	if not frappe.db.exists(doctype, name):
		raise frappe.DoesNotExistError(f"{doctype} {name} not found")
	if not frappe.has_permission(doctype, "write", doc=name):
		frappe.throw(_("You can't edit {0} {1}.").format(doctype, name), frappe.PermissionError)
	fm = get_doctype_form_meta(doctype)
	doc = frappe.get_doc(doctype, name)
	values = {}
	for f in fm["fields"]:
		if f["fieldtype"] == "Table":
			continue
		v = doc.get(f["fieldname"])
		values[f["fieldname"]] = "" if v is None else v
	tables = {}
	for tf, spec in fm["tables"].items():
		cols = [c["fieldname"] for c in spec["columns"]]
		tables[tf] = [
			{c: row.get(c) for c in cols} for row in (doc.get(tf) or [])
		]
	return {
		"ok": True, "doctype": doctype, "name": name,
		"docstatus": int(doc.docstatus or 0),
		"values": values, "tables": tables,
	}
