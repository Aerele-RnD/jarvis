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

    # frappe.share.remove() (without ignore_permissions) deletes the DocShare
    # row via frappe.delete_doc, which checks DELETE permission on the
    # DocShare doctype itself - a System-Manager-only role table with no
    # if_owner - so it denies every ordinary user, even one with legitimate
    # share rights on the target document. The correct boundary is "share"
    # permission on the TARGET doc (mirroring share_doc's implicit check via
    # frappe.share.add -> check_share_permission), then bypass the DocShare
    # ACL explicitly - the same pattern frappe.share.set_docshare_permission
    # uses (share.flags.ignore_permissions = True before deleting).
    frappe.has_permission(doctype, "share", doc=name, throw=True)

    from frappe.share import remove as _share_remove

    _share_remove(doctype=doctype, name=name, user=user,
                   flags={"ignore_permissions": True})
    return {"doctype": doctype, "name": name, "user": user}
