"""Projects-domain detector SQL (plan section 4.2, Projects).

Services-org parity. proj-billing-method classifies each project as
timesheet-billed vs fixed by whether it has submitted Timesheets, then keys
that habit by project type. Project is not submittable, so the unit day is the
project's creation date (the spread gate still applies).
"""

from __future__ import annotations

# Hard per-detector row cap (plan §4.3 fix 7): a curated OOM backstop for the
# unit-grain header SQL; the nightly row budget pauses across detectors.
HARD_ROW_LIMIT = 200000

# --- S1: project type -> billing method (unit = distinct Project) -------------
BILLING_METHOD_SQL = f"""
SELECT p.name AS unit_id,
       p.project_type AS antecedent,
       CASE WHEN EXISTS (
              SELECT 1 FROM `tabTimesheet` ts
              WHERE ts.parent_project = p.name AND ts.docstatus = 1
            ) THEN 'time-and-materials (timesheet-billed)' ELSE 'fixed price' END AS consequent,
       p.company AS company,
       p.creation AS day,
       p.creation AS created
FROM `tabProject` p
WHERE p.company = %(company)s
  AND p.project_type IS NOT NULL AND p.project_type != ''
LIMIT {HARD_ROW_LIMIT}
"""

# --- S1 (Tier-2): activity type -> billing rate habit (unit = (Timesheet, --
# activity type)). The rate is canonicalized to 2 decimals in SQL; mixed-rate
# timesheets resolve to the '__mixed__' sentinel and never become a mode.
TIMESHEET_RATE_SQL = f"""
SELECT CONCAT(tsd.parent, '::', tsd.activity_type) AS unit_id,
       tsd.activity_type AS antecedent,
       CASE WHEN COUNT(DISTINCT ROUND(tsd.billing_rate, 2)) = 1
            THEN CAST(MAX(ROUND(tsd.billing_rate, 2)) AS CHAR)
            ELSE '__mixed__' END AS consequent,
       MIN(ts.company) AS company,
       MIN(DATE(ts.creation)) AS day,
       MIN(ts.creation) AS created
FROM `tabTimesheet Detail` tsd
JOIN `tabTimesheet` ts ON ts.name = tsd.parent
WHERE ts.docstatus = 1
  AND ts.company = %(company)s
  AND ts.creation >= %(window_start)s
  AND tsd.is_billable = 1
  AND tsd.billing_rate > 0
  AND tsd.activity_type IS NOT NULL AND tsd.activity_type != ''
GROUP BY tsd.parent, tsd.activity_type
LIMIT {HARD_ROW_LIMIT}
"""

# Configured baselines: the Activity Type master default and any Activity Cost
# rows (per-employee overrides). A realized mode matching either is config
# working as intended and stays silent (S5 semantics on the master side).
ACTIVITY_TYPE_RATE_SQL = (
	"SELECT at.name AS activity_type, at.billing_rate AS billing_rate "
	"FROM `tabActivity Type` at WHERE at.name IN %(names)s"
)

ACTIVITY_COST_RATE_SQL = (
	"SELECT ac.activity_type AS activity_type, ac.billing_rate AS billing_rate "
	"FROM `tabActivity Cost` ac WHERE ac.docstatus < 2 AND ac.activity_type IN %(names)s"
)


def postprocess_timesheet_rate_defaults(rows, spec, company, patterndb, params):
	"""proj-timesheet-rate-defaults (plan section 4.2): the realized billing
	rate habit per activity type, proposed only when neither the Activity Type
	master nor an Activity Cost row already encodes that rate."""
	from jarvis.learning.executor import reduce_units

	raws = reduce_units(rows, spec, patterndb)
	if not raws:
		return []

	names = sorted({r.get("antecedent_value") for r in raws if r.get("antecedent_value")})
	configured: dict = {}
	if names:
		for sql in (ACTIVITY_TYPE_RATE_SQL, ACTIVITY_COST_RATE_SQL):
			try:
				master_rows = patterndb.sql_select(sql, {"names": names}) or []
			except Exception:
				continue
			for m in master_rows:
				rate = m.get("billing_rate")
				try:
					rate = round(float(rate), 2)
				except (TypeError, ValueError):
					continue
				if rate > 0:
					configured.setdefault(m.get("activity_type"), set()).add(rate)

	out = []
	for raw in raws:
		try:
			mode_rate = round(float(raw.get("consequent_value")), 2)
		except (TypeError, ValueError):
			continue
		known = configured.get(raw.get("antecedent_value")) or set()
		if any(abs(mode_rate - c) < 0.005 for c in known):
			continue  # master / Activity Cost already encodes this rate
		clause = (
			f"the configured default is {sorted(known)[0]:g}"
			if known
			else "no default billing rate is configured"
		)
		raw["skill_bullet_vars"] = {
			"activity_type": raw.get("antecedent_value"),
			"rate": f"{mode_rate:g}",
			"master_clause": clause,
		}
		evidence = raw.get("evidence")
		if isinstance(evidence, dict):
			evidence["configured_rates"] = sorted(known)
		out.append(raw)
	return out
