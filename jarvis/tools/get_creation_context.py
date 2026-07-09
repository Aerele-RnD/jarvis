"""Assemble creation context for the agent to DECIDE field values from.

When about to create a record, the agent calls this with the target doctype and
whatever it already knows (the party, a category, a type - a ``context`` dict of
field hints). It returns the doctype's writable field map (what's mandatory,
what Frappe auto-fills, what's read-only) plus the existing records MOST SIMILAR
to the one being created, so the agent reads real examples and decides the
values itself. It retrieves and structures context; it never picks a value.

Similarity is context-driven, not party-only: the party (customer/supplier/
employee) is simply the strongest hint when present. Semantic kinship (a *table*
resembles a *desk*, not a *chicken*) is bridged by the model - it supplies the
category hint (``item_group=Furniture``); this tool retrieves structurally on
it. See jarvis-persona AGENTS.md for the create flow.
"""

import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError

# Layout / no-value fieldtypes - never in the field map or record values.
_LAYOUT_FIELDTYPES = {
    "Section Break", "Column Break", "Tab Break", "HTML", "Heading",
    "Button", "Fold", "Image",
}
# Scalar header fieldtypes worth echoing as a similar record's values. Long
# text / code / attachments / child tables are excluded as noise (the full
# ``example`` still carries child rows).
_VALUE_FIELDTYPES = {
    "Data", "Link", "Dynamic Link", "Select", "Autocomplete", "Check",
    "Int", "Float", "Currency", "Percent", "Date", "Datetime", "Time",
    "Small Text", "Rating", "Duration",
}
# Fieldtypes we can filter on to locate "similar" records.
_FILTERABLE_FIELDTYPES = {"Link", "Dynamic Link", "Select", "Data", "Check"}
# Fieldname hints that mark a "classifier" field, for facet suggestions.
_CLASSIFIER_HINTS = ("group", "category", "type", "class", "status", "nature")
# Link targets treated as the strongest similarity anchor (kept longest during
# relaxation). Not exhaustive - any Link still ranks above Select/Data hints.
_PARTY_DOCTYPES = {
    "Customer", "Supplier", "Employee", "Lead", "Contact", "Student", "Member",
}

_MAX_LIMIT = 20
_MAX_VALUE_FIELDS = 40  # cap header fields echoed per similar record


def get_creation_context(
    doctype: str,
    context: dict | str | None = None,
    limit: int = 5,
) -> dict:
    """Field map + the most similar existing records, to decide a create from.

    ``context`` is what the agent already knows about the record - keyed by
    fieldname where possible (``{"customer": "Acme"}``, ``{"item_group":
    "Furniture"}``); a loose ``{"party": "Acme"}`` is resolved to the matching
    Link field. Similar records are found by filtering on those hints
    (progressively relaxed, strongest hint kept longest), else recent records of
    the type. Returns ``{doctype, fields, mandatory, similar, example,
    match_note, facets, note}``. Decides no values - the agent reads and decides.
    """
    if not doctype:
        raise InvalidArgumentError("doctype is required")
    if not frappe.db.exists("DocType", doctype):
        raise InvalidArgumentError(f"unknown doctype: {doctype}")
    meta = frappe.get_meta(doctype)
    if meta.istable:
        raise InvalidArgumentError(
            f"{doctype} is a child table; create its parent instead"
        )
    if meta.issingle:
        raise InvalidArgumentError(
            f"{doctype} is a Single (settings) doctype; not created via this flow"
        )
    if not frappe.has_permission(doctype, ptype="create"):
        raise PermissionDeniedError(f"no create permission on {doctype}")
    if limit <= 0 or limit > _MAX_LIMIT:
        raise InvalidArgumentError(f"limit must be between 1 and {_MAX_LIMIT}")

    if isinstance(context, str):
        try:
            context = frappe.parse_json(context)
        except Exception:
            raise InvalidArgumentError(
                'context must be a dict / JSON object, e.g. {"customer": "Acme"}'
            )
    if not isinstance(context, dict):
        context = {}

    fields = _field_map(meta)
    mandatory = [f["fieldname"] for f in fields if f["mandatory"]]

    filters, matched = _resolve_context_filters(meta, context)
    value_fields = [
        f["fieldname"] for f in fields if f["fieldtype"] in _VALUE_FIELDTYPES
    ][:_MAX_VALUE_FIELDS]
    similar, match_note = _similar_records(doctype, filters, value_fields, limit)

    example = None
    if similar:
        # One FULL example (incl. child rows) so the agent can learn the row
        # shape when mapping a document. get_list already proved row-level
        # read; strip fields above the user's permlevel and drop framework
        # bookkeeping so no hidden field leaks and the payload stays lean.
        name = similar[0]["name"]
        if frappe.has_permission(doctype, ptype="read", doc=name):
            doc = frappe.get_doc(doctype, name)
            doc.apply_fieldlevel_read_permissions()
            example = doc.as_dict(no_default_fields=True)

    facets = {}
    if not matched and frappe.has_permission(doctype, ptype="read"):
        facets = _facets(doctype, meta)

    return {
        "doctype": doctype,
        "fields": fields,
        "mandatory": mandatory,
        "similar": similar,
        "example": example,
        "match_note": match_note,
        "facets": facets,
        "note": (
            "Reference only - decide each field yourself from these examples "
            "and the user's input; never copy blindly. Set every `mandatory` "
            "field that is not already `auto` before create_doc; skip "
            "`auto`/`readonly` fields (Frappe fills those). Ask the user only "
            "about mandatory fields you cannot determine."
        ),
    }


def _field_map(meta) -> list[dict]:
    out = []
    for df in meta.fields:
        if df.fieldtype in _LAYOUT_FIELDTYPES or not df.fieldname:
            continue
        rec = {
            "fieldname": df.fieldname,
            "label": df.label,
            "fieldtype": df.fieldtype,
            "options": df.options,
            "mandatory": bool(df.reqd),
            "auto": bool(df.fetch_from) or (df.default not in (None, "")),
            "readonly": bool(df.read_only),
        }
        cond = getattr(df, "mandatory_depends_on", None)
        if cond:
            rec["mandatory_if"] = cond
        if df.fetch_from:
            rec["fetch_from"] = df.fetch_from
        out.append(rec)
    return out


def _resolve_context_filters(meta, context: dict) -> tuple[list, list]:
    """Turn context hints into ``[(field, value)]`` filters + matched fieldnames.

    A hint keyed by a real filterable fieldname is used directly. A loose hint
    (key not a field) is resolved to the Link field whose target holds a record
    named ``value`` - so ``{"party": "Acme"}`` finds ``customer``/``supplier``
    generically. Filters are sorted strongest-first (party Link > other Link >
    Select/Data) so relaxation keeps the anchor longest regardless of key order.
    """
    field_by_name = {df.fieldname: df for df in meta.fields}
    filters: list = []
    matched: list = []
    for key, value in context.items():
        if value in (None, ""):
            continue
        df = field_by_name.get(key)
        if df and df.fieldtype in _FILTERABLE_FIELDTYPES:
            filters.append((key, value))
            matched.append(key)
            continue
        resolved = _resolve_link_field(meta, value)
        if resolved and resolved not in matched:
            filters.append((resolved, value))
            matched.append(resolved)

    def _strength(field: str) -> int:
        df = field_by_name.get(field)
        if not df:
            return 0
        if df.fieldtype in ("Link", "Dynamic Link"):
            return 3 if df.options in _PARTY_DOCTYPES else 2
        return 1

    filters.sort(key=lambda fv: _strength(fv[0]), reverse=True)  # stable: ties keep order
    return filters, matched


def _resolve_link_field(meta, value):
    if not isinstance(value, str):
        return None
    for df in meta.fields:
        if df.fieldtype == "Link" and df.options:
            # Only probe link targets the user may read - don't turn this into
            # an existence oracle over doctypes they have no access to.
            if not frappe.has_permission(df.options, ptype="read"):
                continue
            try:
                if frappe.db.exists(df.options, value):
                    return df.fieldname
            except Exception:
                continue
    return None


def _similar_records(doctype, filters, fields, limit) -> tuple[list, str]:
    """Fetch the most-similar records via progressive relaxation.

    Try all filters; if none match, drop the last (weakest, filters are sorted
    strongest-first) and retry; if nothing matches, return the most recent
    records of the type. Permission-safe - ``frappe.get_list`` only returns rows
    the acting user may read.
    """
    read_fields = list(dict.fromkeys(["name", *fields]))
    active = list(filters)
    while active:
        rows = frappe.get_list(
            doctype,
            filters={f: v for f, v in active},
            fields=read_fields,
            order_by="creation desc",
            limit=limit,
        )
        if rows:
            note = "matched on " + ", ".join(f"{f}={v}" for f, v in active)
            if len(active) < len(filters):
                note += " (relaxed)"
            return rows, note
        active = active[:-1]
    rows = frappe.get_list(
        doctype, fields=read_fields, order_by="creation desc", limit=limit
    )
    if not rows:
        return [], "no existing records"
    return rows, "recent - no context matched"


def _facets(doctype, meta) -> dict:
    """Distinct values of up to 2 classifier fields, so the agent can pick a
    hint (e.g. see that ``Furniture`` exists) and re-call with context."""
    picks = []
    for df in meta.fields:
        if len(picks) >= 2:
            break
        if df.fieldname == "naming_series":
            continue  # a naming series is noise, not a classifier
        if df.fieldtype == "Select" or (
            df.fieldtype == "Link"
            and any(h in (df.fieldname or "").lower() for h in _CLASSIFIER_HINTS)
        ):
            picks.append(df.fieldname)
    out = {}
    for f in picks:
        try:
            # get_list (not get_all) so distinct values respect row-level perms.
            rows = frappe.get_list(
                doctype, fields=[f], group_by=f, order_by=f, limit=15
            )
            vals = [r.get(f) for r in rows if r.get(f) not in (None, "")]
            if vals:
                out[f] = vals
        except Exception:
            continue
    return out
