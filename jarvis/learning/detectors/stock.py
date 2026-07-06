"""Stock-domain detector SQL + postprocess (plan section 4.2, Stock)."""

from __future__ import annotations

# Hard per-detector row cap (plan §4.3 fix 7): a curated OOM backstop for the
# unit-grain SQL shapes; the nightly row budget pauses across detectors.
HARD_ROW_LIMIT = 200000

# --- single-plant guard: distinct shipping warehouses used by the company -----
WAREHOUSE_COUNT_SQL = """
SELECT COUNT(DISTINCT sii.warehouse) AS wh
FROM `tabSales Invoice Item` sii
JOIN `tabSales Invoice` si ON si.name = sii.parent
WHERE si.docstatus = 1
  AND si.company = %(company)s
  AND si.posting_date >= %(window_start)s
  AND sii.warehouse IS NOT NULL AND sii.warehouse != ''
"""

# --- S5: item group -> warehouse (unit = distinct (invoice, item group)) ------
ITEMGROUP_WAREHOUSE_SQL = f"""
SELECT CONCAT(sii.parent, '::', sii.item_group) AS unit_id,
       sii.item_group AS antecedent,
       CASE WHEN COUNT(DISTINCT sii.warehouse) = 1
            THEN MAX(sii.warehouse) ELSE '__mixed__' END AS consequent,
       si.company AS company,
       MIN(si.posting_date) AS day,
       MIN(si.creation) AS created
FROM `tabSales Invoice Item` sii
JOIN `tabSales Invoice` si ON si.name = sii.parent
WHERE si.docstatus = 1
  AND si.company = %(company)s
  AND si.posting_date >= %(window_start)s
  AND sii.item_group IS NOT NULL AND sii.item_group != ''
  AND sii.warehouse IS NOT NULL AND sii.warehouse != ''
GROUP BY sii.parent, sii.item_group, si.company
LIMIT {HARD_ROW_LIMIT}
"""

# --- S1: stock-entry purpose -> dominant warehouse route (unit = distinct SE) -
STOCK_ENTRY_ROUTE_SQL = f"""
SELECT se.name AS unit_id,
       se.purpose AS antecedent,
       CASE WHEN COUNT(DISTINCT CONCAT(COALESCE(sed.s_warehouse, ''), '>', COALESCE(sed.t_warehouse, ''))) = 1
            THEN MAX(CONCAT(COALESCE(sed.s_warehouse, ''), ' to ', COALESCE(sed.t_warehouse, '')))
            ELSE '__mixed__' END AS consequent,
       MIN(se.company) AS company,
       MIN(se.posting_date) AS day,
       MIN(se.creation) AS created
FROM `tabStock Entry Detail` sed
JOIN `tabStock Entry` se ON se.name = sed.parent
WHERE se.docstatus = 1
  AND se.company = %(company)s
  AND se.posting_date >= %(window_start)s
  AND se.purpose IS NOT NULL AND se.purpose != ''
GROUP BY se.name, se.purpose
LIMIT {HARD_ROW_LIMIT}
"""


def postprocess_itemgroup_warehouse(rows, spec, company, patterndb, params):
	"""Single-plant guard (plan section 4.2): item-group -> warehouse is only
	trustworthy for a company with ONE warehouse cluster. A company shipping
	from more than ``single_plant_max_warehouses`` distinct warehouses is
	multi-plant and is skipped with a coverage note (Tier-2 dimensioned
	variant). Otherwise fall through to the generic reduce, where the variance
	gate additionally kills a volume-skewed 'everything ships from one
	warehouse' distribution."""
	from jarvis.learning.executor import DetectorSkip, reduce_units, single_value

	max_wh = int(spec.get("single_plant_max_warehouses", 3))
	n_wh = single_value(patterndb, WAREHOUSE_COUNT_SQL, params) or 0
	if int(n_wh) > max_wh:
		raise DetectorSkip(
			f"multi-plant: {int(n_wh)} shipping warehouses; needs cost-center "
			"dimensioning (Tier-2 variant)"
		)
	return reduce_units(rows, spec, patterndb)
