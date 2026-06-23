"""Add a comment to any document.

Wraps ``frappe.desk.form.utils.add_comment``. ``comment_email`` and
``comment_by`` are auto-populated from the session user so the agent
doesn't have to specify "who" the comment is from.

Comment is distinct from Communication: a Comment is a free-form note
attached to the doc's timeline (no email side-effect); a Communication
is the structured audit row for emails / phone / SMS. The agent picks
based on intent - "add a note" -> add_comment, "email the customer" ->
send_email.

Permission: ``add_comment`` requires read perm on the reference doc;
the underlying helper enforces this via
``frappe.get_lazy_doc(..., check_permission=True)``.
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import InvalidArgumentError
from jarvis.tools import desk_action


@desk_action()
def add_comment(doctype: str, name: str, content: str) -> dict:
    """Add a Comment to ``doctype/name`` with ``content`` as the body.

    Returns ``{comment_name, doctype, name, content}`` where
    ``comment_name`` is the new Comment doc id (so a follow-up
    update_comment can target it).
    """
    if content is None or content == "":
        raise InvalidArgumentError("content is required")

    from frappe.desk.form.utils import add_comment as _ac

    session_user = frappe.session.user
    user_full_name = frappe.db.get_value("User", session_user, "full_name") or session_user

    comment = _ac(
        reference_doctype=doctype,
        reference_name=name,
        content=content,
        comment_email=session_user,
        comment_by=user_full_name,
    )
    return {
        "comment_name": comment.name if comment else None,
        "doctype": doctype,
        "name": name,
        "content": content,
    }
