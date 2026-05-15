import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError

MAX_LIMIT = 1000


def get_list(
    doctype: str,
    fields: list[str] | None = None,
    filters: dict | list | None = None,
    order_by: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List documents with filters.

    Frappe's get_list applies per-user record permissions automatically.
    We additionally enforce DocType-level read permission and cap the limit.
    """
    if not doctype:
        raise InvalidArgumentError("doctype is required")
    if limit <= 0 or limit > MAX_LIMIT:
        raise InvalidArgumentError(f"limit must be between 1 and {MAX_LIMIT}")

    if not frappe.has_permission(doctype, ptype="read"):
        raise PermissionDeniedError(f"no read permission on {doctype}")

    return frappe.get_list(
        doctype,
        fields=fields or ["name"],
        filters=filters or {},
        order_by=order_by,
        limit=limit,
    )
