"""Grant per-record permissions to a user (or to "Everyone").

Wraps ``frappe.share.add``. The DocShare row this creates is what
overrides the DocType-level permissions for a specific record - useful
when the agent is asked to "share this invoice with sales" or "let X
view this customer's history".

ALWAYS-CONFIRM: granting share permission means the target user can
re-share the record further. The descriptor's agent-facing copy is
explicit about that escalation risk.
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import InvalidArgumentError
from jarvis.tools import require_doctype_and_name


def share_doc(
    doctype: str,
    name: str,
    user: str | None = None,
    read: bool = True,
    write: bool = False,
    submit: bool = False,
    share: bool = False,
    everyone: bool = False,
    notify: bool = False,
) -> dict:
    """Grant the given permission flags on ``doctype/name`` to ``user``
    (or to every user when ``everyone=True``). Returns
    ``{doctype, name, user, everyone, read, write, submit, share}``.
    """
    require_doctype_and_name(doctype, name)
    if not frappe.db.exists(doctype, name):
        raise InvalidArgumentError(f"unknown {doctype}: {name}")
    if not everyone and not user:
        raise InvalidArgumentError(
            "either user or everyone=True is required",
        )
    if user and not frappe.db.exists("User", user):
        raise InvalidArgumentError(f"unknown User: {user}")

    from frappe.share import add as _share_add

    _share_add(
        doctype=doctype, name=name, user=user,
        read=int(bool(read)), write=int(bool(write)),
        submit=int(bool(submit)), share=int(bool(share)),
        everyone=int(bool(everyone)), notify=int(bool(notify)),
    )
    return {
        "doctype": doctype,
        "name": name,
        "user": user,
        "everyone": bool(everyone),
        "read": bool(read),
        "write": bool(write),
        "submit": bool(submit),
        "share": bool(share),
    }
