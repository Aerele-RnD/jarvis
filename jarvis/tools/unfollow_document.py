"""Unsubscribe a user from a document's change events.

Wraps ``frappe.desk.form.document_follow.unfollow_document``. Idempotent
(no-op when the user isn't currently following).
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import InvalidArgumentError
from jarvis.tools import require_doctype_and_name


def unfollow_document(
    doctype: str,
    name: str,
    user: str | None = None,
) -> dict:
    """Unsubscribe ``user`` (or the session user) from
    ``doctype/name``. Returns ``{doctype, name, user, unfollowed}``."""
    require_doctype_and_name(doctype, name)
    if not frappe.db.exists(doctype, name):
        raise InvalidArgumentError(f"unknown {doctype}: {name}")
    target_user = user or frappe.session.user
    if user and not frappe.db.exists("User", user):
        raise InvalidArgumentError(f"unknown User: {user}")

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
