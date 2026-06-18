"""Create a ToDo + assign a user to a document.

Wraps ``frappe.desk.form.assign_to.add``. The underlying helper takes a
single ``args`` dict (Frappe's idiomatic form-bag shape); we accept
typed arguments and pack into the dict so the agent has a clean
signature.

Side-effects beyond the ToDo row: assignment auto-shares the
referenced document with the assignee (so they can read it) AND fires
a "you've been assigned" notification email by default.

ALWAYS-CONFIRM: a person gets a notification email.
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import InvalidArgumentError
from jarvis.tools import require_doctype_and_name


def assign_to(
    doctype: str,
    name: str,
    user: str,
    description: str | None = None,
    notify: bool = True,
    priority: str | None = None,
    date: str | None = None,
) -> dict:
    """Open a ToDo for ``user`` assigned to ``doctype/name``. Returns
    ``{doctype, name, user, description, notify, priority, date}``."""
    require_doctype_and_name(doctype, name)
    if not user:
        raise InvalidArgumentError("user is required")
    if not frappe.db.exists(doctype, name):
        raise InvalidArgumentError(f"unknown {doctype}: {name}")
    if not frappe.db.exists("User", user):
        raise InvalidArgumentError(f"unknown User: {user}")

    from frappe.desk.form.assign_to import add as _assign_add

    args = {
        "doctype": doctype,
        "name": name,
        "assign_to": [user],
        "description": description or "",
        "notify": int(bool(notify)),
    }
    if priority:
        args["priority"] = priority
    if date:
        args["date"] = date

    _assign_add(args)
    return {
        "doctype": doctype,
        "name": name,
        "user": user,
        "description": description,
        "notify": bool(notify),
        "priority": priority,
        "date": date,
    }
