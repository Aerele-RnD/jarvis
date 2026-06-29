"""run_method - call a whitelisted Frappe server method by name.

The generic escape hatch for whitelisted RPCs the dedicated tools do not
wrap - e.g. ERPNext's ``make_*`` document mappers
(``make_sales_invoice``, ``make_delivery_note`` ...) and doctype-specific
whitelisted actions. Runs under the calling user's identity
(``jarvis.api.call_tool`` has already ``set_user``), so the method's own
``@frappe.whitelist()`` gate and permission checks apply.

Consequential by default: it can mutate. The persona confirms before
calling it, ``api._run_tool`` audits it, and it supports ``preview``
(dry-run via a rolled-back savepoint).
"""
import fnmatch

import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError


def run_method(method: str, args: dict | None = None) -> dict:
    """Call a whitelisted server method ``method`` with keyword ``args``.

    ``method`` is a dotted path, e.g.
    ``erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice``.
    Only ``@frappe.whitelist()`` methods are callable; anything else raises
    PermissionDeniedError. An optional site-config allowlist
    (``jarvis_run_method_allowlist``: a list of fnmatch patterns) further
    narrows what may be called - recommended in production.

    Returns the method's return value verbatim (often a document dict).
    """
    if not method:
        raise InvalidArgumentError("method is required")
    if args is not None and not isinstance(args, dict):
        raise InvalidArgumentError("args must be a dict")

    allow = frappe.conf.get("jarvis_run_method_allowlist")
    if allow and not any(fnmatch.fnmatch(method, pat) for pat in allow):
        raise PermissionDeniedError(
            f"method {method!r} is not in jarvis_run_method_allowlist"
        )

    try:
        fn = frappe.get_attr(method)
    except Exception:
        raise InvalidArgumentError(f"unknown method: {method}")

    # Enforce @frappe.whitelist(): raises frappe.PermissionError if not.
    try:
        frappe.is_whitelisted(fn)
    except frappe.PermissionError as e:
        raise PermissionDeniedError(
            str(e) or f"method {method} is not whitelisted"
        ) from e

    try:
        return frappe.call(fn, **(args or {}))
    except frappe.PermissionError as e:
        raise PermissionDeniedError(
            str(e) or f"no permission to call {method}"
        ) from e
