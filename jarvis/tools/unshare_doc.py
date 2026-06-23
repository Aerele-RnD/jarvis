"""Revoke a user's share permissions on a document.

Wraps ``frappe.share.remove``. Removes the DocShare row entirely; the
target user falls back to whatever DocType-level perms they had before
the share was granted (which may still leave them with access).
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import InvalidArgumentError
from jarvis.tools import desk_action


@desk_action(check_user_arg="user")
def unshare_doc(doctype: str, name: str, user: str) -> dict:
    """Remove the DocShare granting ``user`` access to ``doctype/name``.
    Returns ``{doctype, name, user}``."""
    if not user:
        raise InvalidArgumentError("user is required")

    from frappe.share import remove as _share_remove

    _share_remove(doctype=doctype, name=name, user=user)
    return {"doctype": doctype, "name": name, "user": user}
