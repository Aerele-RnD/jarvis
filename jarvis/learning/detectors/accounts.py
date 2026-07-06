"""Accounts-domain detector SQL (plan section 4.2, Accounts).

Tier-1 accounts detector: mode of payment by payment direction. Antecedent is
the direction (Receive / Pay), an org-level A-class aggregate - no party names,
no amounts. Party-specific and rate/amount detectors (acct-party-tax-template,
acct-rounding-habit, acct-payment-terms-timing) are Tier-2 (plan section 4.4).
"""

from __future__ import annotations

# Hard per-detector row cap (plan §4.3 fix 7): a curated OOM backstop for the
# unit-grain header SQL; the nightly row budget pauses across detectors.
HARD_ROW_LIMIT = 200000

# --- S1: payment direction -> mode of payment (unit = distinct Payment Entry) -
MODE_OF_PAYMENT_SQL = f"""
SELECT pe.name AS unit_id,
       pe.payment_type AS antecedent,
       pe.mode_of_payment AS consequent,
       pe.company AS company,
       pe.posting_date AS day,
       pe.creation AS created
FROM `tabPayment Entry` pe
WHERE pe.docstatus = 1
  AND pe.company = %(company)s
  AND pe.posting_date >= %(window_start)s
  AND pe.mode_of_payment IS NOT NULL AND pe.mode_of_payment != ''
  AND pe.payment_type IS NOT NULL AND pe.payment_type != ''
LIMIT {HARD_ROW_LIMIT}
"""
