"""Close a user's ToDo assignment on a document.

Wraps ``frappe.desk.form.assign_to.remove``. The underlying helper
sets the ToDo's status to ``Closed`` rather than deleting it - the
record stays for audit history. The auto-share created by ``assign_to``
is not revoked (a separate ``unshare_doc`` call handles that).
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import InvalidArgumentError
from jarvis.tools import desk_action


@desk_action(check_user_arg="user")
def unassign_from(doctype: str, name: str, user: str) -> dict:
    """Close the ToDo assigning ``user`` to ``doctype/name``. Returns
    ``{doctype, name, user}``."""
    if not user:
        raise InvalidArgumentError("user is required")

    from frappe.desk.form.assign_to import remove as _assign_remove

    _assign_remove(doctype=doctype, name=name, assign_to=user)
    return {"doctype": doctype, "name": name, "user": user}
