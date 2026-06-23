"""Unsubscribe a user from a document's change events.

Wraps ``frappe.desk.form.document_follow.unfollow_document``. Idempotent
(no-op when the user isn't currently following).
"""
from __future__ import annotations

import frappe

from jarvis.tools import desk_action


@desk_action(check_user_arg="user")
def unfollow_document(
    doctype: str,
    name: str,
    user: str | None = None,
) -> dict:
    """Unsubscribe ``user`` (or the session user) from
    ``doctype/name``. Returns ``{doctype, name, user, unfollowed}``."""
    target_user = user or frappe.session.user

    from frappe.desk.form.document_follow import (
        unfollow_document as _unfollow,
    )

    result = _unfollow(doctype=doctype, doc_name=name, user=target_user)
    return {
        "doctype": doctype,
        "name": name,
        "user": target_user,
        "unfollowed": bool(result),
    }
