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
