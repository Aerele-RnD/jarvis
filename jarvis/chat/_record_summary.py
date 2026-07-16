"""Record summaries for confirmation cards: which fields to show, how to read them
safely, how to format them, and whether a proposed value actually changes anything.

``confirm_card.build_card`` owns card SHAPE; this module owns everything that
touches a doc or a value. Split out because the branching lives here and it needs
its own test surface.

Safety contract (see docs/confirmation-card-redesign-spec.md):
  - Every value is server-derived - from the perm-filtered dry-run ``would``, a
    perm-CHECKED + perm-filtered doc read, or the caller's own args. Never from
    model-authored prose: the card is the human's INDEPENDENT check on the agent.
  - ``frappe.get_doc`` checks NO permission unless a ``check_permission`` kwarg is
    passed (``frappe/model/document.py:141-145`` -> ``:336-349``), and it defaults
    to None. ``apply_fieldlevel_read_permissions`` is permlevel-only. So a doc read
    for a card MUST call ``has_permission`` itself.
  - Nothing here raises into a card: ``build_card`` is best-effort.
"""

from __future__ import annotations

import re

import frappe
from frappe.utils import cint, cstr, flt, get_datetime, getdate

_MAX_VAL = 200  # a scalar display value
_MAX_ROWS = 20  # records / fields per record / child rows
_MAX_COLS = 8  # columns in a rendered child table (NOT _MAX_ROWS: 20 columns is unusable)
_MAX_TABLES = 3  # child tables rendered per record; the rest degrade to "N rows"
_MAX_BODY = 8_000  # a single long-form body (skill instructions, wiki body, one email)
_MAX_BULK_BODY = 2_000  # per-message body in a bulk-email card
_MAX_FLOOR = 8  # fields the meta floor selects for a stored record

# A Password field or an obviously-secret key name - masked, never rendered. This
# lives HERE, not in confirm_card, so the dependency runs one way only
# (confirm_card -> _record_summary). The primitive must never import the card
# module: a module-level import back would be circular.
_SECRET_KEY_RE = re.compile(r"password|secret|token|api[_-]?key", re.IGNORECASE)

# ``format_value`` emits HTML for these (newlines -> <br>, markdown -> HTML,
# Text Editor -> a ql-snow div). Both frontends render through ESCAPED
# interpolation, so these would show literal tags. HTML Editor / Code fall through
# format_value raw, so bypassing them too is equivalent and simpler.
_HTML_FIELDTYPES = frozenset({
	"Text", "Small Text", "Long Text", "Markdown Editor", "Text Editor",
	"HTML Editor", "Code",
})
_TABLE_FIELDTYPES = frozenset({"Table", "Table MultiSelect"})


def _fieldtype(df) -> str | None:
	return getattr(df, "fieldtype", None) if df is not None else None


def is_secret(meta, key) -> bool:
	"""A Password field or an obviously-secret key name. ``meta`` may be None.

	Moved here from confirm_card so the primitive never imports the card module.
	"""
	if _SECRET_KEY_RE.search(str(key)):
		return True
	if meta:
		df = meta.get_field(key)
		if df and df.fieldtype == "Password":
			return True
	return False


def fmt(value, df=None, doc=None, limit: int = _MAX_VAL) -> str:
	"""A value as a short display string, formatted the way Frappe would show it.

	``translated=False`` is deliberate: format_value runs ``frappe._(value)`` on
	every string VALUE, not just labels (frappe/utils/formatters.py:59-60), so a
	non-English session could render something other than what is stored. Select
	options still translate inside their own branch, which is the only translation
	wanted.
	"""
	if isinstance(value, list):
		return f"{len(value)} row{'' if len(value) == 1 else 's'}"
	if isinstance(value, dict):
		return "..."
	fieldtype = _fieldtype(df)
	if fieldtype == "Check":
		# format_value has no Check branch (formatters.py:146) -> raw 1/0. cint is
		# mandatory: the string "0" is truthy and would render "Yes".
		out = "Yes" if cint(value) else "No"
	elif df is None or fieldtype in _HTML_FIELDTYPES:
		out = "" if value is None else cstr(value)
	else:
		try:
			out = cstr(frappe.format_value(value, df=df, doc=doc, translated=False))
		except Exception:
			# format_value raises for real: attribute access in get_field_currency
			# (meta.py:886), a bad link in get_cached_value (meta.py:897), an assert
			# in get_field_precision (meta.py:936).
			out = "" if value is None else cstr(value)
	return out if len(out) <= limit else out[: limit - 1] + "…"


def _cast_date(value):
	# getdate(None) and getdate("") return TODAY (frappe/utils/data.py:125-126), so
	# a bare getdate would make "set the due date to today" on an unset field compare
	# equal to itself and VANISH from the card. Empties must stay empty.
	if value in (None, ""):
		return None
	return getdate(value)


def _cast_datetime(value):
	# get_datetime(None) returns now() (data.py:164-165) - two calls microseconds
	# apart are unequal, so None vs None would render a phantom "(empty) -> (empty)".
	if value in (None, ""):
		return None
	out = get_datetime(value)
	if out is None:
		# get_datetime returns None for an INVALID string rather than raising, so two
		# different pieces of garbage would compare equal. Force the changed branch.
		raise ValueError(f"not a datetime: {value!r}")
	return out


# Cast a value the way the SAVE would, per fieldtype. Deliberately NOT the display
# form: fmt_money at precision 2 renders 100.005 and 100.001 identically, so a
# display compare drops a REAL change from a gated card. flt takes no precision
# here - rounding is exactly what caused that bug.
_CAST = {
	"Currency": flt,
	"Float": flt,
	"Percent": flt,
	"Int": cint,
	"Long Int": cint,
	"Check": cint,
	"Date": _cast_date,
	"Datetime": _cast_datetime,
}


def same_value(a, b, df=None) -> bool:
	"""True when saving ``b`` over a stored ``a`` would not change the stored value.

	Answers the question the no-op guard actually exists for, rather than "do these
	two render the same". Comparing DISPLAY forms hides real changes; comparing raw
	values shows phantom ones (the DB holds a typed 100.0, the model sends "100").
	Casting both sides the way the save does gets both right.

	An uncastable value counts as CHANGED - never hide a row because we could not
	compare it.
	"""
	cast = _CAST.get(_fieldtype(df), cstr)
	try:
		return cast(a) == cast(b)
	except Exception:
		return False


def pick_fields(meta) -> list[str]:
	"""The meta floor: which fields identify a STORED record at a glance.

	Selection only - never used for proposed content, which renders whole (a
	proposed field outside the floor is one the save will write, so hiding it would
	let you approve a value you never saw).

	Order: title, list-view columns, mandatory fields, status, grand_total/total.
	Frappe's own link_preview (frappe/desk/link_preview.py) falls back to ``reqd``
	when no preview fields are set - a record's required fields are its essence -
	and that is the idea borrowed here. ``docstatus`` is not a DocField, so it is
	not selectable; summary_rows renders it as a synthetic row instead.
	"""
	if not meta:
		return []
	out: list[str] = []
	seen: set[str] = set()

	def add(fieldname):
		if not fieldname or fieldname == "name" or fieldname in seen:
			return
		df = meta.get_field(fieldname)
		if df is None or df.fieldtype in _TABLE_FIELDTYPES:
			return
		seen.add(fieldname)
		out.append(fieldname)

	try:
		add(meta.get_title_field())
	except Exception:
		pass
	try:
		for fieldname in meta.get_list_fields() or []:
			add(fieldname)
	except Exception:
		pass
	for df in meta.fields or []:
		if df.reqd:
			add(df.fieldname)
	if getattr(meta, "is_submittable", 0):
		add("status")
	for fieldname in ("grand_total", "total"):
		if meta.has_field(fieldname):
			add(fieldname)
			break

	def is_long(fieldname):
		df = meta.get_field(fieldname)
		return bool(df) and df.fieldtype in _HTML_FIELDTYPES

	ordered = [f for f in out if not is_long(f)] + [f for f in out if is_long(f)]
	return ordered[:_MAX_FLOOR]


_DOCSTATUS_LABEL = {0: "Draft", 1: "Submitted", 2: "Cancelled"}


def summary_rows(doctype: str, name: str) -> dict | None:
	"""``{"title", "rows"}`` for a STORED record, or None when it is missing or the
	caller cannot read it.

	The caller renders a NAME-ONLY row on None. ``title`` is returned only from this
	function's successful, permission-checked path - never source a card header from
	a separate db.get_value(title_field): that read is unchecked and the title field
	is typically the party name, i.e. the data being protected.
	"""
	try:
		# Fresh DB load, NOT get_cached_doc: a cache could serve sandbox-mutated
		# state from the park-time dry-run.
		doc = frappe.get_doc(doctype, name)
	except frappe.DoesNotExistError:
		# frappe.throw leaves an entry in message_log that would leak into the turn.
		frappe.clear_messages()
		return None
	except Exception:
		frappe.clear_messages()
		return None

	# get_doc checks NO permission unless the check_permission kwarg is passed
	# (document.py:141-145 -> :336-349, defaults to None). has_permission returns a
	# bool; the kwarg throws, and a card must degrade rather than raise.
	try:
		if not doc.has_permission("read"):
			return None
	except Exception:
		return None

	try:
		doc.apply_fieldlevel_read_permissions()
	except Exception:
		return None

	meta = doc.meta
	rows = []
	for fieldname in pick_fields(meta):
		# A permlevel-restricted field is delattr'd by the filter above
		# (document.py:1264) and is dropped by the confirmed save too - never show a
		# phantom value.
		if not hasattr(doc, fieldname):
			continue
		value = doc.get(fieldname)
		if value is None or (not isinstance(value, list) and cstr(value).strip() == ""):
			continue
		df = meta.get_field(fieldname)
		label = df.label if df and df.label else fieldname
		shown = "[hidden]" if is_secret(meta, fieldname) else fmt(value, df, doc)
		rows.append({"label": label, "value": shown})
		if len(rows) >= _MAX_ROWS:
			break

	if getattr(meta, "is_submittable", 0):
		# docstatus is not a DocField, so pick_fields cannot select it.
		rows.append({
			"label": "Docstatus",
			"value": _DOCSTATUS_LABEL.get(cint(doc.get("docstatus")), "?"),
		})

	title = ""
	try:
		title_field = meta.get_title_field()
		if title_field and title_field != "name" and hasattr(doc, title_field):
			title = fmt(doc.get(title_field), meta.get_field(title_field), doc)
	except Exception:
		title = ""
	return {"title": title, "rows": rows}
