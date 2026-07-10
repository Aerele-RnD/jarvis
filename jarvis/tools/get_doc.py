import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools import require_doctype_and_name


def get_doc(doctype: str, name: str) -> dict:
    """Return a single document as a dict.

    Enforces read permission on the specific document for the current user.
    """
    require_doctype_and_name(doctype, name)

    if not frappe.db.exists(doctype, name):
        raise InvalidArgumentError(f"unknown {doctype}: {name}")

    if not frappe.has_permission(doctype, ptype="read", doc=name):
        raise PermissionDeniedError(f"no read permission on {doctype} {name}")

    doc = frappe.get_doc(doctype, name)
    doc.apply_fieldlevel_read_permissions()
    return doc.as_dict(no_default_fields=False)
