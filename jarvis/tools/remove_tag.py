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
from jarvis.tools import require_doctype_and_name


def remove_tag(doctype: str, name: str, tag: str) -> dict:
    """Remove ``tag`` from ``doctype/name``. Returns
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

    from frappe.desk.doctype.tag.tag import remove_tag as _rt

    _rt(tag=tag, dt=doctype, dn=name)
    return {"doctype": doctype, "name": name, "tag": tag}
