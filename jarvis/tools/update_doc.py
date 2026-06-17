"""Update a Frappe document with permission-aware writes.

This is the first **mutating** tool in Jarvis. Every guarantee that the
read tools rely on (per-user permissions, no leakage, etc.) carries over
to writes - Frappe's permission engine checks ``write`` on the target
DocType + record, not just ``read``.

Safety bounds enforced here (on top of Frappe's standard validation):

- Calling user must have ``write`` permission on the target record
  (``frappe.has_permission(doctype, ptype="write", doc=name)``)
- A small allow-list of mutable fields is NOT used - Frappe itself
  enforces field-level permissions and DocType-level read_only flags
- System fields (``name``, ``owner``, ``creation``, ``modified``,
  ``modified_by``, ``doctype``, ``docstatus``, ``idx``, ``parent``,
  ``parentfield``, ``parenttype``) are refused - they're maintained by
  Frappe, not user-editable, and an LLM shouldn't be poking at them
- ``docstatus`` changes are refused - submit/cancel/amend go through
  dedicated workflows (future tools), not raw field writes
- Empty ``changes`` dict is refused so the agent doesn't accidentally
  call this with no-op intent
"""

import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools import require_doctype_and_name

# Fields Frappe maintains itself or that govern DocType identity. An LLM
# rewriting these would corrupt the row.
PROTECTED_FIELDS = frozenset({
    "name",
    "owner",
    "creation",
    "modified",
    "modified_by",
    "doctype",
    "docstatus",
    "idx",
    "parent",
    "parentfield",
    "parenttype",
})


def update_doc(doctype: str, name: str, changes: dict) -> dict:
    """Apply ``changes`` to a single document and save it.

    Returns the saved document as a dict (matching ``get_doc``'s shape).
    Raises:
      - InvalidArgumentError on empty args, empty changes, attempts to
        write protected fields
      - PermissionDeniedError when the calling user lacks write on the
        target record
      - frappe.DoesNotExistError when the record doesn't exist
      - frappe.ValidationError when the DocType's own validate() rejects
    """
    require_doctype_and_name(doctype, name)
    if not isinstance(changes, dict) or not changes:
        raise InvalidArgumentError("changes must be a non-empty dict")

    protected = sorted(set(changes.keys()) & PROTECTED_FIELDS)
    if protected:
        raise InvalidArgumentError(
            f"refusing to write protected field(s): {', '.join(protected)}"
        )

    if not frappe.has_permission(doctype, ptype="write", doc=name):
        raise PermissionDeniedError(
            f"no write permission on {doctype} '{name}'"
        )

    doc = frappe.get_doc(doctype, name)  # raises DoesNotExistError if missing
    for field, value in changes.items():
        doc.set(field, value)
    doc.save()  # runs DocType validate() and on_update hooks
    return doc.as_dict()
