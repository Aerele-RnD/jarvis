import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError


def get_doc(doctype: str, name: str) -> dict:
    """Return a single document as a dict.

    Enforces read permission on the specific document for the current user.
    """
    if not doctype:
        raise InvalidArgumentError("doctype is required")
    if not name:
        raise InvalidArgumentError("name is required")

    if not frappe.db.exists(doctype, name):
        raise InvalidArgumentError(f"unknown {doctype}: {name}")

    if not frappe.has_permission(doctype, ptype="read", doc=name):
        raise PermissionDeniedError(f"no read permission on {doctype} {name}")

    doc = frappe.get_doc(doctype, name)
    return doc.as_dict(no_default_fields=False)
