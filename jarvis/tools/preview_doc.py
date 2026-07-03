"""Dry-run a document create: full ERP pipeline, nothing persisted.

``create_doc`` inserts blind - the agent only discovers what ERPNext's
``set_missing_values`` chain / regional hooks resolved (party address, GST
fields, payment schedule, totals) AFTER the record exists. This tool runs the
exact same ``doc.insert()`` inside a savepoint and rolls back, returning the
resolved header plus which fields the server filled and which integrity
fields stayed empty - so the agent can show a faithful pre-create review and
fix master-data gaps (e.g. a supplier with no linked Address) FIRST.

Same guards as ``create_doc``; the calling user needs create permission.
"""
import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.create_doc import PROTECTED_FIELDS, _set_title_from_title_field

# Header fieldtypes worth echoing back (child tables + layout/HTML excluded).
_HEADER_TYPES = {
    "Data", "Link", "Dynamic Link", "Select", "Autocomplete", "Date",
    "Datetime", "Time", "Currency", "Float", "Int", "Check", "Percent",
    "Small Text",
}

# Integrity-bearing fieldname fragments: emptiness here is worth surfacing
# (a bare link field elsewhere is usually just an unused feature).
_INTEGRITY_FRAGMENTS = (
    "address", "contact", "payment_terms", "taxes_and_charges", "gstin",
    "place_of_supply", "tax_category", "due_date",
)


def preview_doc(doctype: str, values: dict) -> dict:
    """Validate + resolve a would-be document without creating it.

    Runs ``doc.insert()`` (controller validate, set_missing_values, regional
    hooks, payment schedule, autoname) inside a savepoint, captures the
    resolved document, then rolls back - no record, no consumed name. Returns
    ``{valid, resolved, server_filled, empty_fields, items_count, totals}``;
    a rejected document returns ``{valid: false, error}`` instead of raising,
    so drafts can be fixed and retried cheaply. Use before ``create_doc`` on
    consequential documents (invoices, orders); then create the confirmed
    draft with ``create_doc``.
    """
    if not doctype:
        raise InvalidArgumentError("doctype is required")
    if not isinstance(values, dict) or not values:
        raise InvalidArgumentError("values must be a non-empty dict")

    protected = sorted(set(values.keys()) & PROTECTED_FIELDS)
    if protected:
        raise InvalidArgumentError(
            f"refusing to write protected field(s): {', '.join(protected)}"
        )

    if not frappe.has_permission(doctype, ptype="create"):
        raise PermissionDeniedError(f"no create permission on {doctype}")

    doc = frappe.new_doc(doctype)
    for field, value in values.items():
        doc.set(field, value)
    _set_title_from_title_field(doc)

    # Same sandbox discipline as api._run_preview: neutralize commits for the
    # duration (a hook calling frappe.db.commit() would RELEASE the savepoint
    # and persist the "dry run"), unique savepoint name so nested previews
    # can't collide.
    db = frappe.db
    real_commit = db.commit
    db.commit = lambda *a, **k: None
    sp = "jpd_" + frappe.generate_hash(length=10)
    db.savepoint(sp)
    try:
        doc.insert()
        result = _summarize(doc, values)
    except Exception as e:
        db.commit = real_commit
        db.rollback(save_point=sp)
        frappe.clear_messages()
        return {"valid": False, "error": _error_text(e)}
    db.commit = real_commit
    db.rollback(save_point=sp)
    return result


def _summarize(doc, caller_values: dict) -> dict:
    resolved: dict = {}
    empty_fields: list[str] = []
    for df in doc.meta.fields:
        if df.fieldtype not in _HEADER_TYPES:
            continue
        val = doc.get(df.fieldname)
        if val not in (None, ""):
            resolved[df.fieldname] = val
        elif any(f in df.fieldname for f in _INTEGRITY_FRAGMENTS):
            empty_fields.append(df.fieldname)
    server_filled = sorted(
        f for f in resolved
        if f not in caller_values and f not in ("naming_series",)
    )
    totals = {
        f: doc.get(f)
        for f in ("net_total", "total_taxes_and_charges", "grand_total", "rounded_total")
        if doc.meta.has_field(f) and doc.get(f) is not None
    }
    return {
        "valid": True,
        "resolved": resolved,
        "server_filled": server_filled,
        "empty_fields": empty_fields,
        "items_count": len(doc.get("items") or []) if doc.meta.has_field("items") else None,
        "totals": totals,
        "note": "dry run only - nothing was created; use create_doc to create",
    }


def _error_text(e: Exception) -> str:
    from frappe.utils import strip_html_tags

    msg = str(e) or type(e).__name__
    try:
        return strip_html_tags(msg)
    except Exception:
        return msg
