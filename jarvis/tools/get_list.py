import frappe

from jarvis.exceptions import (
    InvalidArgumentError,
    PermissionDeniedError,
    ResultTooLargeError,
)

MAX_LIMIT = 1000

# Row guard: refuse a result over this size unless the caller passes
# ``confirm_large=True``. Sits below ``MAX_LIMIT`` (the hard ceiling on
# Frappe's ``limit`` parameter) and above the default ``limit=20`` so
# narrow queries fit silently and only the agent's wide ``limit=N``
# calls trigger the guard. See ``ResultTooLargeError`` for the
# 2026-06-22 outage that motivated this.
ROW_GUARD = 200


def get_list(
    doctype: str,
    fields: list[str] | None = None,
    filters: dict | list | None = None,
    order_by: str | None = None,
    limit: int = 20,
    confirm_large: bool = False,
) -> list[dict]:
    """List documents with filters.

    Frappe's get_list applies per-user record permissions automatically.
    We additionally enforce DocType-level read permission and cap the limit.

    Row guard: results above ``ROW_GUARD`` (200) rows raise
    ``ResultTooLargeError`` unless ``confirm_large=True``. The agent
    should respond by narrowing the filter, aggregating the question
    via ``run_query``, or - for genuine export workflows - retrying
    with ``confirm_large=True``.
    """
    if not doctype:
        raise InvalidArgumentError("doctype is required")
    if limit <= 0 or limit > MAX_LIMIT:
        raise InvalidArgumentError(f"limit must be between 1 and {MAX_LIMIT}")

    if not frappe.has_permission(doctype, ptype="read"):
        raise PermissionDeniedError(f"no read permission on {doctype}")

    rows = frappe.get_list(
        doctype,
        fields=fields or ["name"],
        filters=filters or {},
        order_by=order_by,
        limit=limit,
    )
    if len(rows) > ROW_GUARD and not confirm_large:
        raise ResultTooLargeError(
            row_count=len(rows),
            limit=ROW_GUARD,
            tool="get_list",
        )
    return rows
