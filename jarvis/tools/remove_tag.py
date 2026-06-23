"""Remove a tag from a document.

Wraps ``frappe.desk.doctype.tag.tag.remove_tag``. No-op when the tag
isn't on the doc (idempotent).
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import (
    InvalidArgumentError,
    PermissionDeniedError,
)
from jarvis.tools import desk_action


@desk_action()
def remove_tag(doctype: str, name: str, tag: str) -> dict:
    """Remove ``tag`` from ``doctype/name``. Returns
    ``{doctype, name, tag}``."""
    if not tag:
        raise InvalidArgumentError("tag is required")
    if not frappe.has_permission(doctype, "write", doc=name):
        raise PermissionDeniedError(
            f"no write permission on {doctype} {name}",
        )

    from frappe.desk.doctype.tag.tag import remove_tag as _rt

    _rt(tag=tag, dt=doctype, dn=name)
    return {"doctype": doctype, "name": name, "tag": tag}
