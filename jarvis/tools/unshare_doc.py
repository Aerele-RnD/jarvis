"""Revoke a user's share permissions on a document.

Wraps ``frappe.share.remove``. Removes the DocShare row entirely; the
target user falls back to whatever DocType-level perms they had before
the share was granted (which may still leave them with access).
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import InvalidArgumentError
from jarvis.tools import require_doctype_and_name


def unshare_doc(doctype: str, name: str, user: str) -> dict:
    """Remove the DocShare granting ``user`` access to ``doctype/name``.
    Returns ``{doctype, name, user}``."""
    require_doctype_and_name(doctype, name)
    if not user:
        raise InvalidArgumentError("user is required")
    if not frappe.db.exists(doctype, name):
        raise InvalidArgumentError(f"unknown {doctype}: {name}")
    if not frappe.db.exists("User", user):
        raise InvalidArgumentError(f"unknown User: {user}")

    from frappe.share import remove as _share_remove

    _share_remove(doctype=doctype, name=name, user=user)
    return {"doctype": doctype, "name": name, "user": user}
