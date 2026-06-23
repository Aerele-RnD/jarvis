"""Subscribe a user to a document's change events.

Wraps ``frappe.desk.form.document_follow.follow_document``. A
followed doc fires the Document Follow notification email to the
subscriber on every modification - the agent uses this for "let me
know when X changes" / "subscribe X to this Customer" flows.

By default ``user`` is the session user, so the agent can follow a
doc on behalf of the customer without naming them.
"""
from __future__ import annotations

import frappe

from jarvis.tools import desk_action


@desk_action(check_user_arg="user")
def follow_document(
    doctype: str,
    name: str,
    user: str | None = None,
) -> dict:
    """Subscribe ``user`` (or the session user) to ``doctype/name``.
    Returns ``{doctype, name, user, followed}`` where ``followed`` is
    True on the wire path that actually inserted a follow row, False
    when the doc was already being followed (idempotent)."""
    target_user = user or frappe.session.user

    from frappe.desk.form.document_follow import (
        follow_document as _follow,
    )

    result = _follow(doctype=doctype, doc_name=name, user=target_user)
    return {
        "doctype": doctype,
        "name": name,
        "user": target_user,
        "followed": bool(result),
    }
