"""Submit a Frappe document.

The third mutating tool. ``submit`` is qualitatively bigger than
``update`` / ``create`` - it moves the doc from Draft (docstatus=0) to
Submitted (docstatus=1), which triggers the DocType's ``on_submit``
hooks. For ERPNext that's where the real-world side effects live:

- Sales/Purchase Invoice → posts to General Ledger
- Stock Entry / Delivery Note → updates stock balances
- Payment Entry → moves money on the books
- Sales Order / Purchase Order → reserves stock, opens fulfilment

Submitted documents are generally **immutable** - changes require
cancellation (which creates reversal entries, leaving an audit trail
rather than a clean undo). The persona must emphasise that ``submit_doc``
is one of the consequential actions and demand explicit confirmation.

Safety bounds:

- DocType must be submittable (``meta.is_submittable``) - otherwise
  ``submit`` is a no-op concept on that DocType and we refuse with a
  clear error instead of a confusing Frappe traceback.
- Calling user must have ``submit`` permission on the record (record-level
  via ``frappe.has_permission(doctype, ptype="submit", doc=name)``).
- Doc must be in Draft state (``docstatus == 0``). Already-submitted and
  cancelled docs are refused.
- ``doc.submit()`` re-runs validate() - DocType business rules still apply,
  and a missing required field or broken link will reject the submission.
"""

import frappe
from frappe.model.workflow import get_workflow_name

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools import require_doctype_and_name


def submit_doc(doctype: str, name: str) -> dict:
    """Submit a Draft document.

    Returns the submitted document as a dict, including the new
    ``docstatus: 1``. Raises:
      - InvalidArgumentError on empty args, non-submittable DocType,
        a workflow-governed DocType (advance via apply_workflow_action),
        or wrong starting docstatus
      - PermissionDeniedError when the calling user lacks submit on the record
      - frappe.DoesNotExistError when the record doesn't exist
      - frappe.ValidationError from the DocType's own validate() hook
    """
    require_doctype_and_name(doctype, name)

    meta = frappe.get_meta(doctype)
    if not meta.is_submittable:
        raise InvalidArgumentError(
            f"{doctype} is not submittable - submit only applies to "
            f"docstatus-tracked DocTypes"
        )

    # A workflow-governed doctype must advance through its state machine, not a
    # direct submit (which would jump the doc straight to a submitted state,
    # skipping approval steps). Desk hides the Submit button here too.
    if get_workflow_name(doctype):
        raise InvalidArgumentError(
            f"{doctype} is governed by a Workflow; advance it with "
            f"apply_workflow_action (e.g. Approve/Reject) instead of "
            f"submitting directly. Use get_workflow_transitions to see the "
            f"actions available to you."
        )

    if not frappe.has_permission(doctype, ptype="submit", doc=name):
        raise PermissionDeniedError(
            f"no submit permission on {doctype} '{name}'"
        )

    doc = frappe.get_doc(doctype, name)  # raises DoesNotExistError if missing
    if doc.docstatus == 1:
        raise InvalidArgumentError(
            f"{doctype} '{name}' is already submitted (docstatus=1)"
        )
    if doc.docstatus == 2:
        raise InvalidArgumentError(
            f"{doctype} '{name}' is cancelled (docstatus=2); cancelled "
            f"docs cannot be re-submitted (amend creates a new draft)"
        )

    doc.submit()  # runs validate() + on_submit hooks; sets docstatus=1
    doc.apply_fieldlevel_read_permissions()
    return doc.as_dict()
