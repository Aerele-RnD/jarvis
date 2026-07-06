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
