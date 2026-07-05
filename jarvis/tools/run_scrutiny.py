"""Deterministic ledger-scrutiny engine (rules-as-data).

Clean-room reimplementation of the Assure Ledger-Scrutiny engine, mapped
to the ERPNext GL model. Each rule in a pack (``rules/scrutiny-pack.json``
in the jarvis-agent-marketplace repo, synced into
``jarvis/agents/rule_packs/``) is a FROZEN, server-evaluated predicate -
never model-emitted SQL. This is why the marketplace auditor agents call
this tool instead of eyeballing ``get_list`` output: audit findings must
be REPRODUCIBLE (same data -> same hits, re-runnable by a peer reviewer)
and a real ledger is far larger than one chat turn can read, so the
filtering happens set-based in the DB.

Read-only over ERP data. Runs under the calling user's Frappe identity,
so it can only see accounts the user is permitted to (company-level
perms + the standard GL Entry query). Statutory rules
(``status == "needs_legal_review"``) are SKIPPED unless
``include_unreviewed`` is set, and every statutory finding carries its
section + effective_date + disclaimer.

Persistence of ``Jarvis Agent Run`` / ``Jarvis Agent Finding`` rows is a
separate, deterministic step wired by the agents layer (B3); this tool
returns the findings so that step and the agent narration share one
source of truth.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal

import frappe

from jarvis.exceptions import InvalidArgumentError

_PACK_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "rule_packs")


# ---------------------------------------------------------------------------
# pack loading + materiality binding
# ---------------------------------------------------------------------------
def _load_pack(rule_pack) -> dict:
    if isinstance(rule_pack, dict):
        return rule_pack
    if not isinstance(rule_pack, str) or not rule_pack:
        raise InvalidArgumentError("rule_pack must be a pack id string or an inline pack dict")
    # A pack id: read the bundled, reviewed pack. Never fetched at runtime
    # from anywhere external (security: packs are reviewed deploy artifacts).
    safe = os.path.basename(rule_pack)
    if not safe.endswith(".json"):
        safe += ".json"
    path = os.path.join(_PACK_DIR, safe)
    if not os.path.isfile(path):
        raise InvalidArgumentError(f"unknown rule_pack: {rule_pack}")
    with open(path) as fh:
        return json.load(fh)


def _resolve_threshold(value, materiality: dict | None):
    """A rule threshold is a literal number or a ``$materiality:<key>``
    binding resolved from compute_materiality output."""
    if isinstance(value, str) and value.startswith("$materiality:"):
        if not materiality:
            return None  # unconfigured -> caller skips the rule
        key = value.split(":", 1)[1]
        return materiality.get("bindings", {}).get(key)
    return value


# ---------------------------------------------------------------------------
# period / company resolution
# ---------------------------------------------------------------------------
def _resolve_scope(company: str | None, fiscal_year: str | None,
                   from_date: str | None, to_date: str | None) -> dict:
    if not company:
        company = frappe.defaults.get_user_default("Company") or frappe.db.get_default("company")
    if not company:
        companies = frappe.get_all("Company", pluck="name", limit=2)
        if len(companies) == 1:
            company = companies[0]
    if not company:
        raise InvalidArgumentError("company is required (could not infer a single default Company)")
    if not frappe.db.exists("Company", company):
        raise InvalidArgumentError(f"unknown Company: {company}")

    if fiscal_year:
        fy = frappe.db.get_value("Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"], as_dict=True)
        if not fy:
            raise InvalidArgumentError(f"unknown Fiscal Year: {fiscal_year}")
        from_date, to_date = str(fy.year_start_date), str(fy.year_end_date)
    if not (from_date and to_date):
        # default to the current fiscal year for the company
        from erpnext.accounts.utils import get_fiscal_year as _gfy
        try:
            fy = _gfy(frappe.utils.today(), company=company, as_dict=True)
            from_date, to_date = str(fy.year_start_date), str(fy.year_end_date)
            fiscal_year = fy.name
        except Exception:
            raise InvalidArgumentError("from_date and to_date (or fiscal_year) are required")
    return {"company": company, "fiscal_year": fiscal_year, "from_date": from_date, "to_date": to_date}


# ---------------------------------------------------------------------------
# rule-kind evaluators — each returns a list of hit dicts
# each hit: {ref_doctype, ref_name, amount, note}
# ---------------------------------------------------------------------------
def _account_filter_sql(af: dict, company: str):
    """Build a parameterized WHERE fragment over `tabAccount` for an
    account_filter spec {root_type, account_type_in, name_like[]}."""
    conds = ["a.company = %(company)s", "a.is_group = 0"]
    params = {"company": company}
    if af.get("root_type"):
        conds.append("a.root_type = %(root_type)s")
        params["root_type"] = af["root_type"]
    if af.get("account_type_in"):
        conds.append("a.account_type in %(acct_types)s")
        params["acct_types"] = tuple(af["account_type_in"])
    likes = af.get("name_like") or []
    if likes:
        ors = []
        for i, kw in enumerate(likes):
            key = f"name_like_{i}"
            ors.append(f"lower(a.account_name) like %({key})s")
            params[key] = f"%{str(kw).lower()}%"
        conds.append("(" + " or ".join(ors) + ")")
    return " and ".join(conds), params


def _k_tb_balance_check(rule, scope, materiality):
    tol_dp = int(rule.get("params", {}).get("tolerance_dp", 1))
    row = frappe.db.sql(
        """select coalesce(sum(debit),0) dr, coalesce(sum(credit),0) cr
           from `tabGL Entry`
           where company=%(company)s and is_cancelled=0
             and posting_date between %(from_date)s and %(to_date)s""",
        scope, as_dict=True,
    )[0]
    dr = Decimal(str(row.dr)).quantize(Decimal(10) ** -tol_dp)
    cr = Decimal(str(row.cr)).quantize(Decimal(10) ** -tol_dp)
    if dr != cr:
        diff = float(dr - cr)
        return [{"ref_doctype": "Company", "ref_name": scope["company"], "amount": diff,
                 "note": f"Trial balance out by {diff:.2f}: debits {float(dr):.2f} vs credits {float(cr):.2f}"}]
    return []


def _k_wrong_side_balance(rule, scope, materiality):
    p = rule.get("params", {})
    min_amount = _resolve_threshold(p.get("min_amount", 0), materiality)
    if min_amount is None:
        return None  # materiality-bound but unconfigured -> skip
    wrong_side = p.get("wrong_side")
    where, params = _account_filter_sql(p.get("account_filter", {}), scope["company"])
    params.update({"from_date": scope["from_date"], "to_date": scope["to_date"]})
    rows = frappe.db.sql(
        f"""select a.name account, coalesce(sum(g.debit),0)-coalesce(sum(g.credit),0) net
            from `tabAccount` a
            join `tabGL Entry` g on g.account=a.name and g.is_cancelled=0
              and g.posting_date between %(from_date)s and %(to_date)s
            where {where}
            group by a.name having abs(net) > %(min_amount)s""",
        {**params, "min_amount": float(min_amount)}, as_dict=True,
    )
    hits = []
    for r in rows:
        net = float(r.net)
        is_debit_side = net > 0
        flagged = (wrong_side == "debit" and is_debit_side) or (wrong_side == "credit" and not is_debit_side)
        if flagged:
            hits.append({"ref_doctype": "Account", "ref_name": r.account, "amount": abs(net),
                         "note": f"{('Debit' if is_debit_side else 'Credit')} balance {abs(net):.2f} on {r.account}"})
    return hits


def _k_voucher_pct_of_ledger(rule, scope, materiality):
    p = rule.get("params", {})
    min_amount = _resolve_threshold(p.get("min_amount", 0), materiality)
    if min_amount is None:
        return None
    roots = tuple(p.get("root_type_in") or ["Income", "Expense"])
    pct_min = float(p.get("pct_min", p.get("pct", 0.5)))
    pct_max = p.get("pct_max")
    # per (account, voucher) amount vs per-account period turnover
    rows = frappe.db.sql(
        """select g.account, g.voucher_type, g.voucher_no,
                  sum(g.debit+g.credit) v_amt
           from `tabGL Entry` g join `tabAccount` a on a.name=g.account
           where a.company=%(company)s and a.root_type in %(roots)s and g.is_cancelled=0
             and g.posting_date between %(from_date)s and %(to_date)s
           group by g.account, g.voucher_type, g.voucher_no""",
        {**scope, "roots": roots}, as_dict=True,
    )
    turnover = {}
    for r in rows:
        turnover[r.account] = turnover.get(r.account, 0.0) + float(r.v_amt)
    hits = []
    for r in rows:
        t = turnover.get(r.account, 0.0)
        if t <= 0 or float(r.v_amt) < float(min_amount):
            continue
        frac = float(r.v_amt) / t
        in_band = frac >= pct_min if pct_max is None else (pct_min <= frac < float(pct_max))
        if in_band:
            hits.append({"ref_doctype": r.voucher_type, "ref_name": r.voucher_no, "amount": float(r.v_amt),
                         "note": f"Voucher {r.voucher_no} is {frac*100:.0f}% of ledger {r.account} (turnover {t:.2f})"})
    return hits


def _k_cash_txn_over_threshold(rule, scope, materiality):
    p = rule.get("params", {})
    threshold = _resolve_threshold(p.get("threshold", 0), materiality)
    if threshold is None:
        return None
    direction = p.get("direction")  # payment | receipt
    where, params = _account_filter_sql(p.get("account_filter", {}), scope["company"])
    params.update(scope)
    # the filtered account's leg, in vouchers that ALSO touch a Cash/Bank account
    side_col = "g.debit" if direction == "payment" else "g.credit"
    rows = frappe.db.sql(
        f"""select g.voucher_type, g.voucher_no, g.account, {side_col} amt
            from `tabGL Entry` g join `tabAccount` a on a.name=g.account
            where {where} and g.is_cancelled=0
              and g.posting_date between %(from_date)s and %(to_date)s
              and {side_col} > %(threshold)s
              and exists (
                select 1 from `tabGL Entry` c join `tabAccount` ca on ca.name=c.account
                where c.voucher_no=g.voucher_no and c.voucher_type=g.voucher_type
                  and c.is_cancelled=0 and ca.account_type in ('Cash','Bank'))""",
        {**params, "threshold": float(threshold)}, as_dict=True,
    )
    return [{"ref_doctype": r.voucher_type, "ref_name": r.voucher_no, "amount": float(r.amt),
             "note": f"Cash {direction} {float(r.amt):.2f} via {r.account} (> {float(threshold):.0f})"} for r in rows]


def _k_dormant_party_ledger(rule, scope, materiality):
    p = rule.get("params", {})
    min_amount = _resolve_threshold(p.get("min_amount", 0), materiality)
    if min_amount is None:
        return None
    party_type = p.get("party_type")
    balance_side = p.get("balance_side")  # credit for Supplier, debit for Customer
    window = p.get("window", "full")
    net_expr = "coalesce(sum(g.credit),0)-coalesce(sum(g.debit),0)" if balance_side == "credit" \
        else "coalesce(sum(g.debit),0)-coalesce(sum(g.credit),0)"
    # closing balance by party up to to_date; activity within the window
    mid = frappe.utils.add_days(scope["from_date"],
                                int((frappe.utils.date_diff(scope["to_date"], scope["from_date"])) / 2))
    if window == "last_half":
        act_from = mid
        act_col = "g.debit+g.credit"
    elif window == "no_payment":
        act_from = scope["from_date"]
        act_col = ("g.debit" if balance_side == "credit" else "g.credit")  # payment reduces the balance
    else:  # full
        act_from = scope["from_date"]
        act_col = "g.debit+g.credit"
    rows = frappe.db.sql(
        f"""select g.party, {net_expr} bal,
                   coalesce(sum(case when g.posting_date between %(act_from)s and %(to_date)s
                                     then {act_col} else 0 end),0) activity
            from `tabGL Entry` g
            where g.company=%(company)s and g.is_cancelled=0 and g.party_type=%(party_type)s
              and g.party is not null and g.posting_date <= %(to_date)s
            group by g.party
            having bal > %(min_amount)s and activity = 0""",
        {**scope, "party_type": party_type, "act_from": act_from, "min_amount": float(min_amount)},
        as_dict=True,
    )
    label = {"full": "no transactions during the year", "last_half": "no transactions in the last six months",
             "no_payment": "no payment during the year"}.get(window, window)
    return [{"ref_doctype": party_type, "ref_name": r.party, "amount": float(r.bal),
             "note": f"{party_type} {r.party}: balance {float(r.bal):.2f}, {label}"} for r in rows]


_EVALUATORS = {
    "tb_balance_check": _k_tb_balance_check,
    "wrong_side_balance": _k_wrong_side_balance,
    "voucher_pct_of_ledger": _k_voucher_pct_of_ledger,
    "cash_txn_over_threshold": _k_cash_txn_over_threshold,
    "dormant_party_ledger": _k_dormant_party_ledger,
    # not yet implemented (reported as skipped_unsupported): advance_in_party,
    # sign_flip_yoy, msme_overdue
}


def run_scrutiny(
    rule_pack: str | dict = "scrutiny-pack",
    domain: str | None = None,
    engagement_config: dict | None = None,
    company: str | None = None,
    fiscal_year: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    include_unreviewed: bool = False,
    max_findings_per_rule: int = 200,
) -> dict:
    """Evaluate a scrutiny rule pack deterministically against the GL and
    return a severity-tagged findings summary. Read-only.
    """
    pack = _load_pack(rule_pack)
    scope = _resolve_scope(company, fiscal_year, from_date, to_date)

    materiality = None
    if engagement_config:
        from jarvis.tools.compute_materiality import compute_materiality
        materiality = compute_materiality(**engagement_config)

    findings, skipped_legal, skipped_unsupported, skipped_unconfigured = [], [], [], []
    counts = {"blocker": 0, "warning": 0, "note": 0}

    for rule in pack.get("rules", []):
        if domain and rule.get("domain") != domain:
            continue
        rid = rule.get("rule_id")
        if rule.get("status") == "needs_legal_review" and not include_unreviewed:
            skipped_legal.append({"rule_id": rid, "statement": rule.get("statement"),
                                  "section": rule.get("section"), "effective_date": rule.get("effective_date"),
                                  "disclaimer": rule.get("disclaimer")})
            continue
        kind = rule.get("kind")
        evaluator = _EVALUATORS.get(kind)
        if not evaluator:
            skipped_unsupported.append({"rule_id": rid, "kind": kind})
            continue
        hits = evaluator(rule, scope, materiality)
        if hits is None:  # materiality-bound rule but no engagement config
            skipped_unconfigured.append({"rule_id": rid, "statement": rule.get("statement")})
            continue
        sev = rule.get("severity", "note")
        for h in hits[:max_findings_per_rule]:
            findings.append({
                "rule_id": rid, "assure_rule": rule.get("assure_rule"), "severity": sev,
                "domain": rule.get("domain"), "statement": rule.get("statement"),
                "section": rule.get("section"), "effective_date": rule.get("effective_date"),
                "disclaimer": rule.get("disclaimer"),
                "ref_doctype": h.get("ref_doctype"), "ref_name": h.get("ref_name"),
                "amount": h.get("amount"), "detail": h.get("note"),
            })
            counts[sev] = counts.get(sev, 0) + 1

    return {
        "pack_id": pack.get("pack_id"),
        "domain": domain,
        "scope": scope,
        "counts": counts,
        "total_findings": len(findings),
        "findings": findings,
        "skipped_needs_legal_review": skipped_legal,
        "skipped_unsupported": skipped_unsupported,
        "skipped_unconfigured": skipped_unconfigured,
        "materiality_used": (materiality.get("bindings") if materiality else None),
    }
