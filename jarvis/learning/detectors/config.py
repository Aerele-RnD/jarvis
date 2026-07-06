"""Masters/Config detector postprocess (plan section 4.2, Masters/Config).

Both Tier-1 config detectors are org-wide (company=None) and multi-source, so
they live entirely in postprocess functions rather than a single SQL constant:

  * cfg-naming-series merges three sources per doctype - realized usage (the
    naming_series column on recent documents), the configured options
    (DocType meta + Property Setter), and tabSeries current counters.
  * cfg-default-vs-usage compares a configured default (per plan section 4.2,
    Price List comes from the Selling Settings single, which has no is_default
    field) against realized usage, and proposes only on divergence.
"""

from __future__ import annotations

from collections import defaultdict

# Hard per-detector row cap (plan §4.3 fix 7): a curated OOM backstop for the
# unit-grain usage SQL; the nightly row budget pauses across detectors.
HARD_ROW_LIMIT = 200000

# Current-era doctypes whose naming series is worth learning. Fixed whitelist:
# the table name is interpolated, so it must never come from user input.
NAMING_SERIES_DOCTYPES = (
	"Sales Invoice",
	"Sales Order",
	"Purchase Order",
	"Purchase Invoice",
	"Quotation",
	"Delivery Note",
	"Payment Entry",
	"Journal Entry",
)

_PROPERTY_SETTER_SQL = """
SELECT value AS options
FROM `tabProperty Setter`
WHERE doc_type = %(dt)s AND field_name = 'naming_series' AND property = 'options'
LIMIT 1
"""

_SERIES_CURRENT_SQL = """
SELECT name AS series, current AS current
FROM `tabSeries`
WHERE name = %(prefix)s
LIMIT 1
"""

# Realized price-list usage, org-wide (unit = distinct Sales Invoice).
DEFAULT_PRICE_LIST_USAGE_SQL = f"""
SELECT si.name AS unit_id,
       si.selling_price_list AS consequent,
       si.posting_date AS day,
       si.creation AS created
FROM `tabSales Invoice` si
WHERE si.docstatus = 1
  AND si.posting_date >= %(window_start)s
  AND si.selling_price_list IS NOT NULL AND si.selling_price_list != ''
LIMIT {HARD_ROW_LIMIT}
"""


def _usage_sql(table: str) -> str:
	return (
		"SELECT `naming_series` AS consequent, name AS unit_id, "
		"DATE(creation) AS day, creation AS created "
		f"FROM `tab{table}` "
		"WHERE naming_series IS NOT NULL AND naming_series != '' "
		"AND creation >= %(window_start)s AND docstatus <= 1 "
		f"LIMIT {HARD_ROW_LIMIT}"
	)


def _series_prefix(series: str) -> str:
	"""tabSeries stores the counter under the literal prefix (the part before
	the hash placeholder), e.g. 'ACC-SINV-.YYYY.-' -> 'ACC-SINV-.YYYY.-' with
	the '#' run stripped. We take everything up to the first '#'."""
	return (series or "").split("#", 1)[0]


def postprocess_naming_series(rows, spec, company, patterndb, params):
	"""Merge realized naming-series usage with configured options + tabSeries
	current counters, one candidate per doctype with a dominant series."""
	from jarvis.learning import compat
	from jarvis.learning.executor import evaluate_segment

	out = []
	for doctype in NAMING_SERIES_DOCTYPES:
		if not compat.has_field(doctype, "naming_series"):
			continue
		try:
			usage = patterndb.timed_select(_usage_sql(doctype), params)
		except Exception:
			continue
		units = {}
		for r in usage or []:
			series = r.get("consequent")
			if not series:
				continue
			units[r.get("unit_id")] = (series, r.get("day"), r.get("created"))
		if not units:
			continue
		counts: dict = defaultdict(int)
		for series, _d, _c in units.values():
			counts[series] += 1
		mode = max(counts.items(), key=lambda kv: (kv[1], str(kv[0])))[0]

		configured = _configured_options(doctype, patterndb)
		current = _series_current(patterndb, mode)
		raw = evaluate_segment(
			spec,
			antecedent_value=doctype,
			consequent_value=mode,
			k=counts[mode],
			n_units=len(units),
			base_rate=0.0,
			days=[d for _s, d, _c in units.values()],
			created=[c for _s, _d, c in units.values()],
			single_antecedent=True,
			names_party=False,
			template="naming-series",
			vars={"doctype": doctype, "series": mode},
			extra_evidence={
				"configured_options": configured,
				"series_current": current,
				"used_series_share": round(counts[mode] / len(units), 4),
			},
			patterndb=patterndb,
		)
		if raw:
			out.append(raw)
	return out


def postprocess_default_vs_usage(rows, spec, company, patterndb, params):
	"""cfg-default-vs-usage (Price List baseline): the configured default lives
	on the Selling Settings single; propose only when realized usage diverges
	from it."""
	from jarvis.learning.executor import evaluate_segment, month_key, singles_value

	configured = singles_value(patterndb, "Selling Settings", "selling_price_list")
	if not configured:
		return []
	usage = patterndb.timed_select(DEFAULT_PRICE_LIST_USAGE_SQL, params)
	units = {}
	for r in usage or []:
		value = r.get("consequent")
		if not value:
			continue
		units[r.get("unit_id")] = (value, r.get("day"), r.get("created"))
	if not units:
		return []
	counts: dict = defaultdict(int)
	for value, _d, _c in units.values():
		counts[value] += 1
	mode = max(counts.items(), key=lambda kv: (kv[1], str(kv[0])))[0]
	if str(mode) == str(configured):
		return []  # realized usage matches config -> nothing to reconcile

	exceptions = [
		{"unit": uid, "value": v, "month": month_key(d)}
		for uid, (v, d, _c) in units.items()
		if v != mode
	][:20]
	raw = evaluate_segment(
		spec,
		antecedent_value="selling_price_list",
		consequent_value=mode,
		k=counts[mode],
		n_units=len(units),
		base_rate=0.0,
		days=[d for _v, d, _c in units.values()],
		created=[c for _v, _d, c in units.values()],
		exceptions=exceptions,
		single_antecedent=True,
		names_party=False,
		template="default-vs-usage",
		vars={"field_label": "price list", "used": mode, "configured": configured},
		extra_evidence={"configured_default": configured},
		patterndb=patterndb,
	)
	return [raw] if raw else []


def _configured_options(doctype: str, patterndb) -> list:
	"""Configured naming_series options: Property Setter override wins, else the
	shipped DocType meta options."""
	try:
		ps = patterndb.sql_select(_PROPERTY_SETTER_SQL, {"dt": doctype})
		if ps and ps[0].get("options"):
			return [o for o in str(ps[0]["options"]).splitlines() if o.strip()]
	except Exception:
		pass
	try:
		import frappe

		field = frappe.get_meta(doctype).get_field("naming_series")
		if field and field.options:
			return [o for o in str(field.options).splitlines() if o.strip()]
	except Exception:
		pass
	return []


def _series_current(patterndb, mode_series: str):
	prefix = _series_prefix(mode_series)
	if not prefix:
		return None
	try:
		row = patterndb.sql_select(_SERIES_CURRENT_SQL, {"prefix": prefix})
		return row[0].get("current") if row else None
	except Exception:
		return None
