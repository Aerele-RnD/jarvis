"""Selling-domain detector SQL + postprocess (plan section 4.2, Selling).

Tier-1 selling detectors read the realized document (Sales Invoice) at unit =
distinct parent invoice. Quotation validity and TC/letterhead are S5
(master-vs-realized) and live in postprocess functions. Item-Price existence
is a row-count existence check, also a postprocess.
"""

from __future__ import annotations

from collections import defaultdict

# Hard per-detector row cap (plan §4.3 fix 7): a curated OOM backstop for the
# unit-grain header SQL shapes; the nightly row budget pauses across detectors.
HARD_ROW_LIMIT = 200000

# --- S1: customer -> selling price list (unit = distinct Sales Invoice) -------
CUSTOMER_PRICE_LIST_SQL = f"""
SELECT si.name AS unit_id,
       si.customer AS antecedent,
       si.selling_price_list AS consequent,
       si.company AS company,
       si.posting_date AS day,
       si.creation AS created
FROM `tabSales Invoice` si
WHERE si.docstatus = 1
  AND si.company = %(company)s
  AND si.posting_date >= %(window_start)s
  AND si.customer IS NOT NULL AND si.customer != ''
  AND si.selling_price_list IS NOT NULL AND si.selling_price_list != ''
LIMIT {HARD_ROW_LIMIT}
"""

# --- S1: customer group -> payment terms template (unit = distinct SI) --------
GROUP_PAYMENT_TERMS_SQL = f"""
SELECT si.name AS unit_id,
       si.customer_group AS antecedent,
       si.payment_terms_template AS consequent,
       si.company AS company,
       si.posting_date AS day,
       si.creation AS created
FROM `tabSales Invoice` si
WHERE si.docstatus = 1
  AND si.company = %(company)s
  AND si.posting_date >= %(window_start)s
  AND si.customer_group IS NOT NULL AND si.customer_group != ''
  AND si.payment_terms_template IS NOT NULL AND si.payment_terms_template != ''
LIMIT {HARD_ROW_LIMIT}
"""

# --- S5 baseline for quotation validity (unit = distinct Quotation) -----------
# consequent = realized validity gap in whole days; postprocess compares it to
# the system default (CRM Settings.default_valid_till, else the +1-month client
# default) and suppresses vanilla usage.
QUOTATION_VALIDITY_SQL = f"""
SELECT q.name AS unit_id,
       'org' AS antecedent,
       CAST(DATEDIFF(q.valid_till, q.transaction_date) AS CHAR) AS consequent,
       q.company AS company,
       q.transaction_date AS day,
       q.creation AS created
FROM `tabQuotation` q
WHERE q.docstatus = 1
  AND q.company = %(company)s
  AND q.transaction_date >= %(window_start)s
  AND q.valid_till IS NOT NULL
  AND q.valid_till >= q.transaction_date
LIMIT {HARD_ROW_LIMIT}
"""

# --- S2 existence: customer-specific selling Item Prices (org-wide) ------------
SELECTIVE_ITEM_PRICING_SQL = f"""
SELECT ip.customer AS customer,
       ip.item_code AS item_code
FROM `tabItem Price` ip
WHERE ip.selling = 1
  AND ip.customer IS NOT NULL AND ip.customer != ''
LIMIT {HARD_ROW_LIMIT}
"""

# --- S1+S5 raw rows for TC / letterhead vs company defaults --------------------
TC_LETTERHEAD_SQL = f"""
SELECT si.name AS unit_id,
       si.letter_head AS letter_head,
       si.tc_name AS tc_name,
       si.company AS company,
       si.posting_date AS day,
       si.creation AS created
FROM `tabSales Invoice` si
WHERE si.docstatus = 1
  AND si.company = %(company)s
  AND si.posting_date >= %(window_start)s
LIMIT {HARD_ROW_LIMIT}
"""

_COMPANY_DEFAULTS_SQL = """
SELECT default_letter_head AS default_letter_head,
       default_selling_terms AS default_selling_terms
FROM `tabCompany`
WHERE name = %(company)s
LIMIT 1
"""


def postprocess_quotation_validity(rows, spec, company, patterndb, params):
	"""S5: propose a validity habit ONLY when it diverges from the system
	default (never restate the vanilla +1-month / configured default)."""
	from jarvis.learning.executor import evaluate_segment, month_key, singles_value

	units = {}
	for r in rows or []:
		try:
			gap = int(r.get("consequent"))
		except (TypeError, ValueError):
			continue
		units[r.get("unit_id")] = (str(gap), r.get("day"), r.get("created"))
	if not units:
		return []

	default_raw = singles_value(patterndb, "CRM Settings", "default_valid_till")
	try:
		default_days = int(default_raw) if default_raw not in (None, "", "0", 0) else None
	except (TypeError, ValueError):
		default_days = None

	counts: dict = defaultdict(int)
	for gap, _d, _c in units.values():
		counts[gap] += 1
	mode = max(counts.items(), key=lambda kv: (kv[1], -abs(int(kv[0]))))[0]
	mode_days = int(mode)

	if default_days:
		if abs(mode_days - default_days) <= 2:
			return []
		default_label = f"{default_days} days"
	else:
		if mode_days in (28, 29, 30, 31):  # untouched +1-month client default
			return []
		default_label = "1 month"

	days = [d for _g, d, _c in units.values()]
	created = [c for _g, _d, c in units.values()]
	exceptions = [
		{"unit": uid, "value": g, "month": month_key(d)}
		for uid, (g, d, _c) in units.items()
		if g != mode
	][:20]
	raw = evaluate_segment(
		spec,
		antecedent_value="org",
		consequent_value=mode,
		k=counts[mode],
		n_units=len(units),
		base_rate=0.0,
		days=days,
		created=created,
		exceptions=exceptions,
		single_antecedent=True,
		names_party=False,
		template="quotation-validity",
		vars={"days": mode_days, "default_days": default_label},
		extra_evidence={"system_default_days": default_days, "system_default_label": default_label},
		patterndb=patterndb,
	)
	return [raw] if raw else []


def postprocess_selective_item_pricing(rows, spec, company, patterndb, params):
	"""S2 existence: customer-specific negotiated prices exist. Names customers
	in the evidence -> content-escalated to B."""
	rows = rows or []
	customers = sorted({r.get("customer") for r in rows if r.get("customer")})
	n_rows = len(rows)
	n_customers = len(customers)
	min_rows = int((spec.get("gates") or {}).get("n_min", 10))
	if n_rows < min_rows or n_customers < 1:
		return []
	band = "High" if n_customers >= 3 else "Medium"
	draft = (
		f"- This org maintains customer-specific negotiated prices for {n_customers} "
		"customers; honour a customer's own price list before the group or org default."
	)
	return [
		{
			"antecedent_value": "org",
			"consequent_value": "customer-specific-pricing",
			"k": n_customers,
			"n_units": n_customers,
			"n_rows": n_rows,
			"exception_n": 0,
			"confidence": 1.0,
			"wilson_low": 1.0,
			"gap": 1.0,
			"band": band,
			"temporal_spread": {},
			"evidence": {
				"n_customers": n_customers,
				"n_item_prices": n_rows,
				"customers": customers[:10],
				"sql_shape": "S2",
			},
			"exceptions": [],
			"exceptions_cluster": None,
			"names_party": True,
			"skill_template": "selective-item-pricing",
			"skill_bullet_vars": {"n_customers": n_customers},
			"statement": f"Customer-specific negotiated prices exist for {n_customers} customers.",
			"rule": None,
			"skill_draft": draft,
			"since_date": "",
			"unit_doctype": "customers",
		}
	]


def postprocess_tc_letterhead(rows, spec, company, patterndb, params):
	"""S1+S5: habitual letter head / TC that diverges from the Company default."""
	from jarvis.learning.executor import evaluate_segment, month_key

	row = patterndb.timed_select(_COMPANY_DEFAULTS_SQL, {"company": company})
	comp = row[0] if row else {}

	out = []
	for field_name, comp_default, label in (
		("letter_head", (comp or {}).get("default_letter_head"), "letter head"),
		("tc_name", (comp or {}).get("default_selling_terms"), "terms and conditions"),
	):
		units = {}
		for r in rows or []:
			value = r.get(field_name)
			if not value:
				continue
			units[r.get("unit_id")] = (value, r.get("day"), r.get("created"))
		if not units:
			continue
		counts: dict = defaultdict(int)
		for value, _d, _c in units.values():
			counts[value] += 1
		mode = max(counts.items(), key=lambda kv: (kv[1], str(kv[0])))[0]
		if comp_default and str(mode) == str(comp_default):
			continue  # matches the company default -> nothing to learn
		days = [d for _v, d, _c in units.values()]
		created = [c for _v, _d, c in units.values()]
		exceptions = [
			{"unit": uid, "value": v, "month": month_key(d)}
			for uid, (v, d, _c) in units.items()
			if v != mode
		][:20]
		raw = evaluate_segment(
			spec,
			antecedent_value=f"org:{field_name}",
			consequent_value=mode,
			k=counts[mode],
			n_units=len(units),
			base_rate=0.0,
			days=days,
			created=created,
			exceptions=exceptions,
			single_antecedent=True,
			names_party=False,
			template="tc-letterhead",
			vars={"field_label": label, "value": mode},
			extra_evidence={"company_default": comp_default, "field": field_name},
			patterndb=patterndb,
		)
		if raw:
			out.append(raw)
	return out
