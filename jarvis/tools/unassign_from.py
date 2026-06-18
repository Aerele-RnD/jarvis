"""Close a user's ToDo assignment on a document.

Wraps ``frappe.desk.form.assign_to.remove``. The underlying helper
sets the ToDo's status to ``Closed`` rather than deleting it - the
record stays for audit history. The auto-share created by ``assign_to``
is not revoked (a separate ``unshare_doc`` call handles that).
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import InvalidArgumentError
from jarvis.tools import require_doctype_and_name


def unassign_from(doctype: str, name: str, user: str) -> dict:
    """Close the ToDo assigning ``user`` to ``doctype/name``. Returns
    ``{doctype, name, user}``."""
    require_doctype_and_name(doctype, name)
    if not user:
        raise InvalidArgumentError("user is required")
    if not frappe.db.exists(doctype, name):
        raise InvalidArgumentError(f"unknown {doctype}: {name}")
    if not frappe.db.exists("User", user):
        raise InvalidArgumentError(f"unknown User: {user}")

    from frappe.desk.form.assign_to import remove as _assign_remove

    _assign_remove(doctype=doctype, name=name, assign_to=user)
    return {"doctype": doctype, "name": name, "user": user}
