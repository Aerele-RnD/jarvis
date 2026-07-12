"""Apply a Workflow action to a document (Approve / Reject / ...).

The WRITE half of workflow support (read half: ``get_workflow_transitions``).
Frappe-workflow-governed DocTypes advance by applying a named *action*, which
the engine validates (is it a legal transition from the current state for this
user's roles?), checks self-approval on, then commits by internally
save()/submit()/cancel()-ing the doc per the target state's docstatus - firing
the usual on_submit / on_cancel side effects.

Consequential: a transition can post to the GL, move stock, or cancel a doc,
exactly like submit_doc / cancel_doc. It is confirmation-gated in api.py.

We wrap Frappe's own ``frappe.model.workflow.apply_workflow`` - it does all the
validation and permission enforcement; we only guard the "no workflow here"
case up front and shape the result.
"""

import frappe
from frappe.model.workflow import apply_workflow, get_workflow_name

from jarvis.exceptions import InvalidArgumentError
from jarvis.tools import require_doctype_and_name


def apply_workflow_action(doctype: str, name: str, action: str) -> dict:
    """Apply ``action`` to the doc's workflow and return the updated doc.

    Raises:
      - InvalidArgumentError on empty args, a DocType with no active workflow
        (use submit_doc / update_doc instead), or an action the workflow does
        not offer from the current state
      - frappe.DoesNotExistError when the record doesn't exist
      - frappe.ValidationError for a self-approval violation, a failed
        transition condition, or the DocType's own validate()/on_submit rules

    When the DocType submits in the background (``queue_in_background``), the
    transition is enqueued rather than committed inline; the result is then
    ``{"queued": True}`` (no doc dict, because nothing is committed yet).
    """
    require_doctype_and_name(doctype, name)
    if not action or not str(action).strip():
        raise InvalidArgumentError("action is required")
    action = str(action).strip()

    if not get_workflow_name(doctype):
        raise InvalidArgumentError(
            f"{doctype} is not governed by an active Workflow; use submit_doc / "
            f"update_doc / cancel_doc instead of a workflow action."
        )

    doc = frappe.get_doc(doctype, name)  # raises DoesNotExistError if missing
    result = apply_workflow(doc, action)  # validates transition + role + self-approval

    # Background-queued submittable DocTypes: apply_workflow enqueues the
    # submit/cancel and early-returns None - nothing is committed synchronously,
    # so don't report a state/docstatus as if it were.
    if result is None:
        return {"doctype": doctype, "name": name, "action": action, "queued": True}

    result.apply_fieldlevel_read_permissions()
    return result.as_dict()
