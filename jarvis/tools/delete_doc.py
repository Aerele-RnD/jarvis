"""Delete a Frappe document.

The **most destructive** mutating tool. Unlike cancel - which keeps the
row and adds a reversal entry - delete removes the row outright. Some
DocTypes retain an audit trail via the ``Version`` DocType; many don't.
Treat every delete as irreversible from the user's perspective.

Safety bounds:

- Calling user must have ``delete`` permission on the record.
- For submittable DocTypes: only Draft (0) or Cancelled (2) docs are
  deletable. Submitted (1) is refused - the user must cancel first
  (Frappe enforces this too; we pre-check for a clearer error).
- Some DocTypes block delete entirely via ``allow_delete = 0`` on their
  meta; Frappe's ``delete_doc`` will raise in that case and the error
  propagates unchanged.
- Linked records: if other docs reference this one (e.g. a Customer with
  Sales Invoices), Frappe raises ``LinkExistsError``. Let it propagate so
  the agent can tell the user "X cannot be deleted because Y references
  it" - clearer than a generic "delete failed".
"""

import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools import require_doctype_and_name


def delete_doc(doctype: str, name: str) -> dict:
    """Delete a Draft or Cancelled (or non-submittable) document.

    Returns ``{"deleted": True, "doctype": ..., "name": ...}`` on success.
    Raises:
      - InvalidArgumentError on empty args or attempting to delete a
        Submitted document
      - PermissionDeniedError when the calling user lacks delete
      - frappe.DoesNotExistError when the record doesn't exist
      - frappe.LinkExistsError when other records reference this one
    """
    require_doctype_and_name(doctype, name)

    if not frappe.has_permission(doctype, ptype="delete", doc=name):
        raise PermissionDeniedError(
            f"no delete permission on {doctype} '{name}'"
        )

    # Pre-load the doc to check docstatus - gives a clearer error than
    # Frappe's "cannot delete a submitted document" for the agent to
    # explain to the user.
    doc = frappe.get_doc(doctype, name)  # raises DoesNotExistError if missing
    if getattr(doc, "docstatus", 0) == 1:
        raise InvalidArgumentError(
            f"{doctype} '{name}' is Submitted (docstatus=1); cancel it "
            f"first (cancel_doc) before deleting"
        )

    frappe.delete_doc(doctype, name)  # raises LinkExistsError if referenced
    return {"deleted": True, "doctype": doctype, "name": name}
