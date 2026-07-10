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

Read-only over ERP data. Every rule evaluator runs raw ``frappe.db.sql``
against GL Entry / Account / Supplier - NOT the standard GL Entry query -
so Frappe's ORM-level permission filtering never applies to those rows.
Before any evaluator runs, this tool explicitly checks the calling user
has ``GL Entry`` read permission (``frappe.has_permission(..., throw=True)``)
- this is what keeps non-financial roles (Sales User, Employee, ...) out
- and, separately, that the resolved company is not excluded by a
``Company`` **User Permission** scope. The company check deliberately
does NOT require ``Company``-doctype read: ERPNext's own "Auditor" role
is granted ``GL Entry`` read but only ``select`` (not ``read``) on
``Company``, so gating on Company-doctype read would lock out a
legitimate audit-agent user entirely. A caller with no Company User
Permission is not company-restricted at all (the GL Entry check already
gates who may run this tool); a caller WITH one may only scrutinize a
company inside that scope - a user restricted to Company A cannot pass
``company="Company B"``. A caller who fails either check is denied
before a single query executes. These two checks are the entire
permission gate - they are doctype/company-level, not per-account or
per-transaction filtered the way ``frappe.get_list`` would be. Statutory rules
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
from frappe.core.doctype.user_permission.user_permission import get_user_permissions

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError

_PACK_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "rule_packs")
INSTALLATION_DT = "Jarvis Agent Installation"


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


class _NotEvaluable:
    """Sentinel an evaluator returns when a rule's data prerequisites are
    missing (e.g. no prior Fiscal Year for a YoY rule). Distinct from a
    clean zero-hit pass: the result reports it under
    ``skipped_not_evaluable`` with the reason, never as "no findings"."""

    def __init__(self, reason: str):
        self.reason = reason


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


def _k_advance_in_party(rule, scope, materiality):
    """L6/L8: party-level net balance as of ``to_date`` sitting on the
    ADVANCE side — Supplier with a net debit balance (advance paid) when
    ``side=="debit"``, Customer with a net credit balance (advance
    received) when ``side=="credit"`` — magnitude above ``min_amount``.
    Party aggregation mirrors ``_k_dormant_party_ledger`` (all GL rows for
    the party up to ``to_date``, any account)."""
    p = rule.get("params", {})
    min_amount = _resolve_threshold(p.get("min_amount", 0), materiality)
    if min_amount is None:
        return None  # materiality-bound but unconfigured -> skip
    party_type = p.get("party_type")
    side = p.get("side")  # debit -> advance paid (Supplier); credit -> advance received (Customer)
    if side not in ("debit", "credit"):
        raise InvalidArgumentError(f"advance_in_party requires params.side debit|credit, got: {side!r}")
    net_expr = "coalesce(sum(g.debit),0)-coalesce(sum(g.credit),0)" if side == "debit" \
        else "coalesce(sum(g.credit),0)-coalesce(sum(g.debit),0)"
    rows = frappe.db.sql(
        f"""select g.party, {net_expr} bal
            from `tabGL Entry` g
            where g.company=%(company)s and g.is_cancelled=0 and g.party_type=%(party_type)s
              and g.party is not null and g.posting_date <= %(to_date)s
            group by g.party having bal > %(min_amount)s
            order by g.party""",
        {**scope, "party_type": party_type, "min_amount": float(min_amount)}, as_dict=True,
    )
    label = "advance paid (net debit balance)" if side == "debit" else "advance received (net credit balance)"
    return [{"ref_doctype": party_type, "ref_name": r.party, "amount": float(r.bal),
             "note": f"{party_type} {r.party}: {label} {float(r.bal):.2f} as of {scope['to_date']}"} for r in rows]


def _prior_fiscal_year(scope):
    """The Fiscal Year immediately before the scope period: the enabled FY
    with the greatest ``year_end_date`` strictly before ``scope.from_date``.
    Returns {name, py_start, py_end} or None when no such FY exists."""
    rows = frappe.db.sql(
        """select name, year_start_date, year_end_date from `tabFiscal Year`
           where year_end_date < %(from_date)s and disabled = 0
           order by year_end_date desc limit 1""",
        scope, as_dict=True,
    )
    if not rows:
        return None
    fy = rows[0]
    return {"name": fy.name, "py_start": str(fy.year_start_date), "py_end": str(fy.year_end_date)}


def _has_gl_rows(company: str, from_date: str | None, to_date: str) -> bool:
    """True when at least one non-cancelled GL row exists for the company
    in [from_date, to_date] (from_date None -> everything up to to_date)."""
    cond = "and posting_date >= %(chk_from)s" if from_date else ""
    row = frappe.db.sql(
        f"""select count(*) n from `tabGL Entry`
            where company=%(company)s and is_cancelled=0
              and posting_date <= %(chk_to)s {cond}""",
        {"company": company, "chk_from": from_date, "chk_to": to_date}, as_dict=True,
    )[0]
    return int(row.n) > 0


def _k_sign_flip_yoy(rule, scope, materiality):
    """L14: per non-group Account, the CUMULATIVE closing balance
    (sum(debit)-sum(credit) over all non-cancelled GL rows up to the date)
    as of the prior fiscal-year end vs as of ``to_date``. Flags accounts
    where the sign flipped AND both magnitudes exceed ``min_amount``
    (strict). Not evaluable (never a silent pass) when: threshold is
    materiality-bound but unconfigured, no Fiscal Year ends before the
    scope period, or the company has no GL rows on/before that FY end."""
    p = rule.get("params", {})
    min_amount = _resolve_threshold(p.get("min_amount", 0), materiality)
    if min_amount is None:
        return None
    py = _prior_fiscal_year(scope)
    if not py:
        return _NotEvaluable("no Fiscal Year ends before the scope period; prior-year closing balances unavailable")
    if not _has_gl_rows(scope["company"], None, py["py_end"]):
        return _NotEvaluable(f"no GL rows on or before prior fiscal-year end {py['py_end']} ({py['name']})")
    rows = frappe.db.sql(
        """select a.name account,
                  coalesce(sum(case when g.posting_date <= %(py_end)s then g.debit - g.credit else 0 end),0) py_net,
                  coalesce(sum(g.debit - g.credit),0) cy_net
           from `tabAccount` a
           join `tabGL Entry` g on g.account=a.name and g.is_cancelled=0
             and g.posting_date <= %(to_date)s
           where a.company=%(company)s and a.is_group=0
           group by a.name
           having (py_net > %(min_amount)s and cy_net < (0 - %(min_amount)s))
               or (py_net < (0 - %(min_amount)s) and cy_net > %(min_amount)s)
           order by a.name""",
        {**scope, "py_end": py["py_end"], "min_amount": float(min_amount)}, as_dict=True,
    )
    hits = []
    for r in rows:
        py_net, cy_net = float(r.py_net), float(r.cy_net)
        frm = "debit" if py_net > 0 else "credit"
        to = "debit" if cy_net > 0 else "credit"
        hits.append({"ref_doctype": "Account", "ref_name": r.account, "amount": abs(cy_net),
                     "note": (f"{r.account}: closing balance flipped {frm}->{to} "
                              f"(PY {py['py_end']}: {py_net:.2f}, CY {scope['to_date']}: {cy_net:.2f})")})
    return hits


# MSME flag candidates on `tabSupplier`, best-first. On this deployment
# NONE exist (verified against jarvis.localhost: stock v16 Supplier schema,
# no india-compliance custom fields), so detection falls back to the
# Supplier Group name containing "msme" — every hit note states the basis.
_MSME_FIELD_CANDIDATES = (
    "is_msme",
    "msme_status",
    "msme_registration_number",
    "msme_registration_no",
    "udyam_registration_number",
    "udyam_no",
)


def _k_msme_overdue(rule, scope, materiality):
    """COMP-MSME-OVERDUE (s.43B(h)): MSME suppliers' payable vouchers still
    outstanding more than ``params.days`` days at ``to_date``.

    Exact semantics (deterministic, GL-derived):
      * Rows: non-cancelled GL entries on non-group Payable accounts of the
        company, party_type=Supplier, posting_date <= to_date.
      * Voucher identity: ``coalesce(nullif(against_voucher,''), voucher_no)``
        (with the matching voucher_type), so payments / debit notes that
        ERPNext posts *against* an invoice net into that invoice's bucket;
        rows with no against_voucher (opening JVs, on-account payments)
        form their own bucket.
      * Outstanding: sum(credit) - sum(debit) per (party, voucher) > 0.
      * Age: the earliest credit-side posting_date in the bucket (the
        liability's origination) must be strictly before to_date - days.
      * MSME detection: the first existing column of
        ``_MSME_FIELD_CANDIDATES`` on `tabSupplier` (is_msme -> =1, other
        fields -> non-empty); if none exists in the site schema, fallback:
        supplier_group name contains 'msme'. The basis used is stated in
        every hit note (and in the pack rule's disclaimer)."""
    p = rule.get("params", {})
    days = int(p.get("days", 45))
    cutoff = str(frappe.utils.add_days(scope["to_date"], -days))
    cols = set(frappe.db.get_table_columns("Supplier"))
    field = next((f for f in _MSME_FIELD_CANDIDATES if f in cols), None)
    if field == "is_msme":
        msme_cond, basis = "s.`is_msme` = 1", "Supplier.is_msme flag"
    elif field:
        msme_cond, basis = f"coalesce(s.`{field}`, '') != ''", f"Supplier.{field} non-empty"
    else:
        msme_cond = "lower(coalesce(s.supplier_group, '')) like '%%msme%%'"
        basis = "supplier_group name contains 'msme' (no MSME field on the Supplier schema)"
    rows = frappe.db.sql(
        f"""select g.party,
                   coalesce(nullif(g.against_voucher_type,''), g.voucher_type) v_type,
                   coalesce(nullif(g.against_voucher,''), g.voucher_no) v_no,
                   coalesce(sum(g.credit),0) - coalesce(sum(g.debit),0) outstanding,
                   min(case when g.credit > 0 then g.posting_date end) originated
            from `tabGL Entry` g
            join `tabAccount` a on a.name = g.account
            join `tabSupplier` s on s.name = g.party
            where a.company=%(company)s and a.account_type='Payable' and a.is_group=0
              and g.company=%(company)s and g.is_cancelled=0
              and g.party_type='Supplier' and g.party is not null
              and g.posting_date <= %(to_date)s
              and {msme_cond}
            group by g.party, v_type, v_no
            having outstanding > 0 and originated < %(cutoff)s
            order by g.party, v_no""",
        {**scope, "cutoff": cutoff}, as_dict=True,
    )
    return [{"ref_doctype": r.v_type, "ref_name": r.v_no, "amount": float(r.outstanding),
             "note": (f"MSME supplier {r.party}: {float(r.outstanding):.2f} outstanding on {r.v_no} "
                      f"since {r.originated} (> {days} days at {scope['to_date']}; "
                      f"MSME detection basis: {basis})")} for r in rows]


def _k_expense_variance_yoy(rule, scope, materiality):
    """FPA-EXPENSE-VARIANCE-YOY (assure M11): per Expense leaf account,
    ratio-to-revenue CY vs prior fiscal year.

      revenue        = Income root_type period total (credit - debit)
      cy_ratio       = round(cy_amt / cy_revenue * 100, 2)
      py_ratio       = round(py_amt / py_revenue * 100, 2)
      variance       = (cy_ratio / py_ratio) * 100 - 100      # M11 formula
      flag           = abs(variance) >= variance_pct AND cy_amt >= min_amount

    CY window = scope period; PY window = the prior Fiscal Year (see
    ``_prior_fiscal_year``). Accounts with py_ratio == 0 have no YoY base
    and are skipped per-account. Not evaluable when: min_amount is
    materiality-bound but unconfigured, no prior FY exists, the PY window
    has no GL rows, or revenue is zero in either period (ratio undefined)
    — never fabricated."""
    p = rule.get("params", {})
    min_amount = _resolve_threshold(p.get("min_amount", 0), materiality)
    if min_amount is None:
        return None
    variance_pct = float(p.get("variance_pct", 20))
    py = _prior_fiscal_year(scope)
    if not py:
        return _NotEvaluable("no Fiscal Year ends before the scope period; prior-year comparatives unavailable")
    if not _has_gl_rows(scope["company"], py["py_start"], py["py_end"]):
        return _NotEvaluable(f"no GL rows in prior fiscal year {py['name']} ({py['py_start']}..{py['py_end']})")
    params = {**scope, **py}
    rev = frappe.db.sql(
        """select coalesce(sum(case when g.posting_date between %(from_date)s and %(to_date)s
                                    then g.credit - g.debit else 0 end),0) cy,
                  coalesce(sum(case when g.posting_date between %(py_start)s and %(py_end)s
                                    then g.credit - g.debit else 0 end),0) py
           from `tabGL Entry` g join `tabAccount` a on a.name=g.account
           where a.company=%(company)s and a.root_type='Income' and a.is_group=0
             and g.is_cancelled=0 and g.posting_date between %(py_start)s and %(to_date)s""",
        params, as_dict=True,
    )[0]
    cy_rev, py_rev = float(rev.cy), float(rev.py)
    if cy_rev == 0 or py_rev == 0:
        return _NotEvaluable(
            f"revenue is zero (CY {cy_rev:.2f}, PY {py_rev:.2f}); ratio-to-revenue undefined")
    rows = frappe.db.sql(
        """select a.name account,
                  coalesce(sum(case when g.posting_date between %(from_date)s and %(to_date)s
                                    then g.debit - g.credit else 0 end),0) cy_amt,
                  coalesce(sum(case when g.posting_date between %(py_start)s and %(py_end)s
                                    then g.debit - g.credit else 0 end),0) py_amt
           from `tabAccount` a
           join `tabGL Entry` g on g.account=a.name and g.is_cancelled=0
             and g.posting_date between %(py_start)s and %(to_date)s
           where a.company=%(company)s and a.root_type='Expense' and a.is_group=0
           group by a.name order by a.name""",
        params, as_dict=True,
    )
    hits = []
    for r in rows:
        cy_amt, py_amt = float(r.cy_amt), float(r.py_amt)
        cy_ratio = round(cy_amt / cy_rev * 100, 2)
        py_ratio = round(py_amt / py_rev * 100, 2)
        if py_ratio == 0:
            continue  # no PY base for this account (M11: needs a prior-year ratio)
        variance = (cy_ratio / py_ratio) * 100 - 100
        if abs(variance) >= variance_pct and cy_amt >= float(min_amount):
            hits.append({"ref_doctype": "Account", "ref_name": r.account, "amount": cy_amt,
                         "note": (f"{r.account}: {cy_ratio:.2f}% of revenue vs {py_ratio:.2f}% in "
                                  f"{py['name']} ({variance:+.1f}% change, threshold {variance_pct:g}%)")})
    return hits


def _k_pl_yoy_swing(rule, scope, materiality):
    """FPA-PL-YOY-SWING: per P&L leaf account (root_type Income/Expense),
    natural-side period activity CY (scope period) vs PY (prior Fiscal
    Year): Income = credit - debit, Expense = debit - credit.

      flag = |CY - PY| / max(|PY|, 1) >= swing_pct/100
             AND |CY - PY| >= min_amount

    Not evaluable when: min_amount is materiality-bound but unconfigured,
    no prior FY exists, or the PY window has no GL rows. (Revenue does not
    enter this formula, so zero revenue does not block evaluation.)"""
    p = rule.get("params", {})
    min_amount = _resolve_threshold(p.get("min_amount", 0), materiality)
    if min_amount is None:
        return None
    swing_pct = float(p.get("swing_pct", 25))
    py = _prior_fiscal_year(scope)
    if not py:
        return _NotEvaluable("no Fiscal Year ends before the scope period; prior-year comparatives unavailable")
    if not _has_gl_rows(scope["company"], py["py_start"], py["py_end"]):
        return _NotEvaluable(f"no GL rows in prior fiscal year {py['name']} ({py['py_start']}..{py['py_end']})")
    rows = frappe.db.sql(
        """select a.name account, a.root_type,
                  coalesce(sum(case when g.posting_date between %(from_date)s and %(to_date)s
                                    then g.debit - g.credit else 0 end),0) cy_raw,
                  coalesce(sum(case when g.posting_date between %(py_start)s and %(py_end)s
                                    then g.debit - g.credit else 0 end),0) py_raw
           from `tabAccount` a
           join `tabGL Entry` g on g.account=a.name and g.is_cancelled=0
             and g.posting_date between %(py_start)s and %(to_date)s
           where a.company=%(company)s and a.root_type in ('Income','Expense') and a.is_group=0
           group by a.name, a.root_type order by a.name""",
        {**scope, **py}, as_dict=True,
    )
    hits = []
    for r in rows:
        sign = -1.0 if r.root_type == "Income" else 1.0
        cy, py_amt = sign * float(r.cy_raw), sign * float(r.py_raw)
        delta = cy - py_amt
        base = max(abs(py_amt), 1.0)
        if abs(delta) >= float(min_amount) and abs(delta) / base >= swing_pct / 100.0:
            hits.append({"ref_doctype": "Account", "ref_name": r.account, "amount": abs(delta),
                         "note": (f"{r.account}: CY {cy:.2f} vs PY {py_amt:.2f} in {py['name']} "
                                  f"(delta {delta:+.2f}, {abs(delta) / base * 100:.0f}% of PY base, "
                                  f"threshold {swing_pct:g}%)")})
    return hits


_EVALUATORS = {
    "tb_balance_check": _k_tb_balance_check,
    "wrong_side_balance": _k_wrong_side_balance,
    "voucher_pct_of_ledger": _k_voucher_pct_of_ledger,
    "cash_txn_over_threshold": _k_cash_txn_over_threshold,
    "dormant_party_ledger": _k_dormant_party_ledger,
    "advance_in_party": _k_advance_in_party,
    "sign_flip_yoy": _k_sign_flip_yoy,
    "msme_overdue": _k_msme_overdue,
    "expense_variance_yoy": _k_expense_variance_yoy,
    "pl_yoy_swing": _k_pl_yoy_swing,
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
    installation: str | None = None,
) -> dict:
    """Evaluate a scrutiny rule pack deterministically against the GL and
    return a severity-tagged findings summary. Read-only over ERP data.

    ``installation``: when an auditor agent runs inside a marketplace audit
    turn it passes its ``Jarvis Agent Installation`` name; the findings are
    then DETERMINISTICALLY persisted (``Jarvis Agent Run`` + ``Jarvis Agent
    Finding`` rows, deduped) into the run the scheduler/manual-trigger opened
    for it, and ``run_id`` is returned. Persistence is server-side, not
    model-mediated — the agent only narrates. Only the installation OWNER can
    persist (this runs under the caller's identity)."""
    pack = _load_pack(rule_pack)
    scope = _resolve_scope(company, fiscal_year, from_date, to_date)

    # Every evaluator below runs raw SQL over GL Entry/Account/Supplier -
    # Frappe's ORM permission layer never sees these queries, so the gate
    # has to be explicit. GL Entry read (doctype-level) keeps non-financial
    # roles out entirely. Cross-company scoping is enforced via Company
    # User Permissions, NOT Company-doctype read: ERPNext's "Auditor" role
    # has GL Entry read but only "select" (not "read") on Company, so
    # gating on Company read would deny a legitimate audit user outright.
    # No Company User Permission -> not company-restricted -> allowed
    # (already gated by the GL Entry check above). A Company User
    # Permission for a DIFFERENT company than the one requested -> denied.
    frappe.has_permission("GL Entry", "read", throw=True)
    company_scope = get_user_permissions(frappe.session.user).get("Company")
    if company_scope:
        allowed_companies = {up.get("doc") for up in company_scope}
        if scope["company"] not in allowed_companies:
            raise PermissionDeniedError(
                f"no access to company {scope['company']!r} (restricted by Company User Permission)"
            )

    materiality = None
    if engagement_config:
        from jarvis.tools.compute_materiality import compute_materiality
        materiality = compute_materiality(**engagement_config)

    findings, skipped_legal, skipped_unsupported, skipped_not_evaluable = [], [], [], []
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
        if hits is None or isinstance(hits, _NotEvaluable):
            # None: materiality-bound threshold but no engagement config.
            # _NotEvaluable: data prerequisite missing (e.g. no prior FY).
            # Either way the rule was NOT evaluated — reported, never a
            # silent zero-findings pass.
            reason = hits.reason if isinstance(hits, _NotEvaluable) \
                else "materiality-bound threshold unresolved (no engagement_config)"
            skipped_not_evaluable.append({"rule_id": rid, "reason": reason,
                                          "statement": rule.get("statement")})
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

    result = {
        "pack_id": pack.get("pack_id"),
        "domain": domain,
        "scope": scope,
        "counts": counts,
        "total_findings": len(findings),
        "findings": findings,
        "skipped_needs_legal_review": skipped_legal,
        "skipped_unsupported": skipped_unsupported,
        "skipped_not_evaluable": skipped_not_evaluable,
        # Backward-compat alias (SKILL prose + SPA read this key): the same
        # rows as skipped_not_evaluable, which generalises it.
        "skipped_unconfigured": skipped_not_evaluable,
        "materiality_used": (materiality.get("bindings") if materiality else None),
    }

    # Audit context: persist deterministically into the open run for this
    # installation (created by the scheduler / run_agent_now). The OWNER-scoped
    # `if_owner` rows only land for the caller's own installation.
    if installation:
        try:
            inst = frappe.get_doc(INSTALLATION_DT, installation)
            if inst.owner != frappe.session.user:
                result["persist_skipped"] = "not the installation owner"
            else:
                from jarvis.chat.agent_runs import record_scrutiny_run
                open_run = frappe.db.get_value(
                    "Jarvis Agent Run",
                    {"installation": installation, "status": "running"},
                    "name", order_by="creation desc",
                )
                run_doc = record_scrutiny_run(inst, "manual", None, result, run=open_run)
                result["run_id"] = run_doc.name
                result["persisted"] = True
        except Exception as e:
            result["persist_error"] = f"{type(e).__name__}: {e}"
    return result
