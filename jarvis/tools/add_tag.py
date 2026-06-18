"""Tag a document for categorisation.

Wraps ``frappe.desk.doctype.tag.tag.add_tag``. Tags are free-form
labels that show up in the Desk list filters; the agent can use them
to bucket records (e.g. tag a Sales Order as 'urgent', tag a Customer
as 'follow-up').

Permission: ``add_tag`` requires write permission on the target doc
(implicitly: it modifies the doc's ``_user_tags`` field).
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import (
    InvalidArgumentError,
    PermissionDeniedError,
)
from jarvis.tools import require_doctype_and_name


def add_tag(
    doctype: str,
    name: str,
    tag: str,
    color: str | None = None,
) -> dict:
    """Add ``tag`` to ``doctype/name``. ``color`` is an optional hex
    code (e.g. ``#ff0000``) for the Tag record. Returns
    ``{doctype, name, tag}``."""
    require_doctype_and_name(doctype, name)
    if not tag:
        raise InvalidArgumentError("tag is required")
    if not frappe.db.exists(doctype, name):
        raise InvalidArgumentError(f"unknown {doctype}: {name}")
    if not frappe.has_permission(doctype, "write", doc=name):
        raise PermissionDeniedError(
            f"no write permission on {doctype} {name}",
        )

    from frappe.desk.doctype.tag.tag import add_tag as _at

    _at(tag=tag, dt=doctype, dn=name, color=color)
    return {"doctype": doctype, "name": name, "tag": tag}
