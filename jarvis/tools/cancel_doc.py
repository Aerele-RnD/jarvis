"""Cancel a submitted Frappe document.

Inverse of submit. Moves docstatus 1 → 2 and fires the DocType's
``on_cancel`` hooks. In ERPNext that typically creates **reversal
entries** rather than deleting anything:

- Sales/Purchase Invoice cancel → posts negative GL entries
- Stock Entry cancel → returns the stock movement
- Payment Entry cancel → reverses the money movement
- Sales/Purchase Order cancel → releases reserved stock

A cancelled document keeps its row + history. To "undo a cancel" the
business workflow is **amend**: Frappe creates a new Draft copy with the
same data so it can be edited and re-submitted. Amend is a separate tool
(not yet built).

Safety bounds:

- DocType must be submittable.
- Calling user must have ``cancel`` permission on the record.
- Doc must be in Submitted state (``docstatus == 1``). Draft (0) and
  already-Cancelled (2) are refused with clear errors.
- ``doc.cancel()`` runs ``on_cancel`` hooks, which may themselves fail
  (e.g., trying to cancel an invoice that's already partly paid raises a
  Frappe ValidationError); those propagate unchanged so the agent surfaces
  the real reason.
"""

import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools import require_doctype_and_name


def cancel_doc(doctype: str, name: str) -> dict:
    """Cancel a Submitted document.

    Returns the cancelled document as a dict (with ``docstatus: 2``).
    Raises:
      - InvalidArgumentError on empty args, non-submittable DocType,
        or wrong starting docstatus (Draft or already Cancelled)
      - PermissionDeniedError when the calling user lacks cancel
      - frappe.DoesNotExistError when the record doesn't exist
      - frappe.ValidationError from the DocType's on_cancel hook
    """
    require_doctype_and_name(doctype, name)

    meta = frappe.get_meta(doctype)
    if not meta.is_submittable:
        raise InvalidArgumentError(
            f"{doctype} is not submittable - cancellation only applies to "
            f"docstatus-tracked DocTypes"
        )

    if not frappe.has_permission(doctype, ptype="cancel", doc=name):
        raise PermissionDeniedError(
            f"no cancel permission on {doctype} '{name}'"
        )

    doc = frappe.get_doc(doctype, name)
    if doc.docstatus == 0:
        raise InvalidArgumentError(
            f"{doctype} '{name}' is in Draft (docstatus=0); only Submitted "
            f"docs can be cancelled. To discard a Draft, use delete_doc."
        )
    if doc.docstatus == 2:
        raise InvalidArgumentError(
            f"{doctype} '{name}' is already cancelled (docstatus=2)"
        )

    doc.cancel()  # runs on_cancel hooks; sets docstatus=2
    doc.apply_fieldlevel_read_permissions()
    return doc.as_dict()
