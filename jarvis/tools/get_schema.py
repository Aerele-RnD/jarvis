import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError


def get_schema(doctype: str) -> dict:
    """Return meta for a DocType: name and field list.

    Enforces read permission on the DocType for the current user.
    """
    if not doctype:
        raise InvalidArgumentError("doctype is required")

    if not frappe.db.exists("DocType", doctype):
        raise InvalidArgumentError(f"unknown DocType: {doctype}")

    if not frappe.has_permission(doctype, ptype="read"):
        raise PermissionDeniedError(f"no read permission on {doctype}")

    meta = frappe.get_meta(doctype)
    fields = [
        {
            "fieldname": f.fieldname,
            "fieldtype": f.fieldtype,
            "label": f.label,
            "options": f.options,
            "reqd": bool(f.reqd),
        }
        for f in meta.fields
    ]
    return {"doctype": doctype, "fields": fields}
