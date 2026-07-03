"""Dry-run a document create: full ERP pipeline, nothing persisted.

``create_doc`` inserts blind - the agent only discovers what ERPNext's
``set_missing_values`` chain / regional hooks resolved (party address, GST
fields, payment schedule, totals) AFTER the record exists. This tool runs the
exact same ``doc.insert()`` inside the shared preview sandbox (commits
neutralized, savepoint rollback, commit-callback queues kept clean - see
``_preview_sandbox``) and returns the resolved header plus which fields the
server filled and which integrity fields stayed empty - so the agent can show
a faithful pre-create review and fix master-data gaps (e.g. a supplier with
no linked Address) FIRST.

Permission contract: same guards as ``create_doc`` (shared
``_validate_create_args``).
"""
import frappe

from jarvis.tools._preview_sandbox import preview_sandbox
from jarvis.tools.create_doc import _set_title_from_title_field, _validate_create_args

# Header fieldtypes worth echoing back (child tables + layout/HTML excluded).
_HEADER_TYPES = {
    "Data", "Link", "Dynamic Link", "Select", "Autocomplete", "Date",
    "Datetime", "Time", "Currency", "Float", "Int", "Check", "Percent",
    "Small Text",
}

# Exact integrity-bearing fieldnames: emptiness here is worth surfacing.
# Deliberately an allow-list of the writable source fields - substring
# matching swept in read-only display mirrors (contact_display/_mobile/_email)
# and unrelated flags, so one missing contact link produced four "gaps".
_INTEGRITY_FIELDS = {
    "supplier_address", "customer_address", "company_address",
    "shipping_address", "shipping_address_name", "dispatch_address",
    "billing_address", "contact_person", "payment_terms_template",
    "due_date", "place_of_supply", "tax_category", "taxes_and_charges",
}

_TOTAL_FIELDS = ("net_total", "total_taxes_and_charges", "grand_total", "rounded_total")


def _norm(v):
    """Fold the falsy-numeric family together: the insert pipeline writes 0
    where a bare new_doc holds None, and that difference is not 'the server
    filled this field'."""
    return 0 if v in (None, 0, 0.0, False) else v


def preview_doc(doctype: str, values: dict) -> dict:
    """Validate + resolve a would-be document without creating it.

    Runs ``doc.insert()`` (controller validate, set_missing_values, regional
    hooks, payment schedule, autoname) inside the preview sandbox, captures
    the resolved document, then rolls back - no record, no consumed name, no
    queued webhooks/notifications. Returns ``{valid, resolved, server_filled,
    empty_fields, items_count, totals}``; a rejected document returns
    ``{valid: false, error}`` instead of raising, so drafts can be fixed and
    retried cheaply. Use before ``create_doc`` on consequential documents
    (invoices, orders); then create the confirmed draft with ``create_doc``.
    Side effects fired directly inside hooks (inline HTTP calls) are not
    sandboxed.
    """
    _validate_create_args(doctype, values)

    doc = frappe.new_doc(doctype)
    for field, value in values.items():
        doc.set(field, value)
    _set_title_from_title_field(doc)

    try:
        with preview_sandbox():
            doc.insert()
    except Exception as e:
        frappe.clear_messages()
        return {"valid": False, "error": _error_text(e)}
    # Summarize OUTSIDE the try: a summarization bug must never mislabel a
    # document that validated cleanly as {valid: false}. The in-memory doc
    # keeps its resolved fields after the rollback; nothing below hits the DB.
    return _summarize(doc, values)


def _summarize(doc, caller_values: dict) -> dict:
    # Baseline = a bare new_doc: a value only counts as "server filled" when
    # it differs from the untouched default, so zero-default flags/amounts
    # don't flood the payload as fake auto-fill.
    baseline = frappe.new_doc(doc.doctype)
    resolved: dict = {}
    server_filled: list[str] = []
    empty_fields: list[str] = []
    for df in doc.meta.fields:
        if df.fieldtype not in _HEADER_TYPES:
            continue
        name = df.fieldname
        val = doc.get(name)
        if val in (None, ""):
            if name in _INTEGRITY_FIELDS and not df.read_only:
                empty_fields.append(name)
            continue
        if name in _TOTAL_FIELDS or name.startswith("base_"):
            continue  # totals live in `totals`; base_* company mirrors add no signal
        if name in caller_values:
            resolved[name] = val
        elif _norm(val) != _norm(baseline.get(name)):
            resolved[name] = val
            server_filled.append(name)
    totals = {
        f: doc.get(f)
        for f in _TOTAL_FIELDS
        if doc.meta.has_field(f) and doc.get(f) is not None
    }
    return {
        "valid": True,
        "resolved": resolved,
        "server_filled": sorted(server_filled),
        "empty_fields": empty_fields,
        "items_count": len(doc.get("items") or []) if doc.meta.has_field("items") else None,
        "totals": totals,
        "note": (
            "dry run only - nothing was persisted or queued; use create_doc "
            "to create. Side effects fired directly inside hooks (inline "
            "HTTP calls) are not sandboxed."
        ),
    }


def _error_text(e: Exception) -> str:
    from frappe.utils import strip_html_tags

    msg = str(e) or type(e).__name__
    try:
        return strip_html_tags(msg)
    except Exception:
        return msg
