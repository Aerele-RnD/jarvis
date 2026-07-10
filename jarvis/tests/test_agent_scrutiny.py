"""Unit tests for the agents-marketplace deterministic audit core.

compute_materiality is pure arithmetic (no DB) so it is fully asserted
here. run_scrutiny is integration-validated against a live GL (see the
build validation); its pure helpers (threshold binding, pack loading)
are covered here.
"""
import contextlib
import os
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.tools.compute_materiality import compute_materiality
from jarvis.tools.run_scrutiny import (
    _EVALUATORS,
    _NotEvaluable,
    _load_pack,
    _resolve_threshold,
    run_scrutiny,
)
from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError

_MARKETPLACE_PACK = "/home/vignesh/jarvis/jarvis-agent-marketplace/rules/scrutiny-pack.json"
_BENCH_PACK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "agents", "rule_packs", "scrutiny-pack.json",
)


class TestComputeMateriality(unittest.TestCase):
    def test_basic_tiers(self):
        m = compute_materiality(benchmark_value=10_000_000, percentage=5,
                                engagement_risk_level="Medium", rounding_step=1000)
        self.assertEqual(m["overall"], 500000)
        self.assertEqual(m["performance"], 375000)   # 25% haircut
        self.assertEqual(m["trivial"], 20000)        # 4%
        self.assertEqual(m["specific"], 40000)       # 8%

    def test_risk_drives_performance_haircut(self):
        base = dict(benchmark_value=10_000_000, percentage=5, rounding_step=1000)
        high = compute_materiality(engagement_risk_level="High", **base)
        low = compute_materiality(engagement_risk_level="Low", **base)
        self.assertEqual(high["performance"], 250000)  # 50% haircut
        self.assertEqual(low["performance"], 450000)   # 10% haircut
        self.assertLess(high["performance"], low["performance"])  # higher risk -> lower PM

    def test_half_up_rounding_to_step(self):
        m = compute_materiality(benchmark_value=1_234_567, percentage=5, rounding_step=1000)
        self.assertEqual(m["overall"], 62000)  # 61728.35 -> 62 * 1000

    def test_explicit_legacy_binding_overrides_default(self):
        m = compute_materiality(benchmark_value=10_000_000, percentage=5, bs_balance_amount=99999)
        self.assertEqual(m["bindings"]["bs_balance"], 99999)
        self.assertEqual(m["bindings"]["pl_balance"], m["performance"])  # default

    def test_validation(self):
        with self.assertRaises(InvalidArgumentError):
            compute_materiality(benchmark_value=100, percentage=0)
        with self.assertRaises(InvalidArgumentError):
            compute_materiality(benchmark_value=100, percentage=5, engagement_risk_level="Wrong")
        with self.assertRaises(InvalidArgumentError):
            compute_materiality(benchmark_value=None, percentage=5)


class TestScrutinyHelpers(unittest.TestCase):
    def test_threshold_literal(self):
        self.assertEqual(_resolve_threshold(10000, None), 10000)

    def test_threshold_materiality_binding(self):
        mat = {"bindings": {"bs_balance": 37500}}
        self.assertEqual(_resolve_threshold("$materiality:bs_balance", mat), 37500)

    def test_threshold_unconfigured_returns_none(self):
        # materiality-bound but no materiality computed -> None (caller skips the rule)
        self.assertIsNone(_resolve_threshold("$materiality:bs_balance", None))

    def test_pack_loads_bundled(self):
        pack = _load_pack("scrutiny-pack")
        self.assertEqual(pack["pack_id"], "scrutiny-pack")
        self.assertEqual(pack["version"], "1.2.0")
        # v1.1.0 activated all 4 statutory rules on founder approval; every
        # statutory rule must carry section + effective_date + disclaimer.
        statutory = [r for r in pack["rules"] if r.get("section")]
        self.assertEqual(len(statutory), 4)
        for r in statutory:
            self.assertTrue(r.get("effective_date") and r.get("disclaimer"), r["rule_id"])

    def test_pack_every_kind_has_an_evaluator(self):
        # v1.2.0: no declared-but-unimplemented kinds may remain.
        pack = _load_pack("scrutiny-pack")
        for r in pack["rules"]:
            self.assertIn(r["kind"], _EVALUATORS, f"{r['rule_id']}: kind {r['kind']} unsupported")

    def test_pack_new_analytical_rules_frozen_contract(self):
        pack = _load_pack("scrutiny-pack")
        by_id = {r["rule_id"]: r for r in pack["rules"]}
        ev = by_id["FPA-EXPENSE-VARIANCE-YOY"]
        self.assertEqual((ev["domain"], ev["status"], ev["kind"], ev["severity"]),
                         ("analytical-review", "active", "expense_variance_yoy", "warning"))
        self.assertEqual(ev["params"]["variance_pct"], 20)
        self.assertEqual(ev["params"]["min_amount"], "$materiality:pl_balance")
        sw = by_id["FPA-PL-YOY-SWING"]
        self.assertEqual((sw["domain"], sw["status"], sw["kind"], sw["severity"]),
                         ("analytical-review", "active", "pl_yoy_swing", "note"))
        self.assertEqual(sw["params"]["swing_pct"], 25)
        self.assertEqual(sw["params"]["min_amount"], "$materiality:pl_balance")
        # rules made supported in this build are still present, unrenamed
        for rid in ("LS-ADVANCE-FROM-CUSTOMER-MAT", "LS-ADVANCE-TO-SUPPLIER-MAT",
                    "LS-SIGN-FLIP-YOY", "COMP-MSME-OVERDUE"):
            self.assertIn(rid, by_id)

    def test_pack_copies_byte_identical(self):
        if not os.path.isfile(_MARKETPLACE_PACK):
            self.skipTest("marketplace repo not present on this machine")
        with open(_BENCH_PACK, "rb") as a, open(_MARKETPLACE_PACK, "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_pack_unknown_raises(self):
        with self.assertRaises(InvalidArgumentError):
            _load_pack("no-such-pack")

    def test_pack_inline_dict(self):
        self.assertEqual(_load_pack({"pack_id": "x", "rules": []})["pack_id"], "x")

    def test_not_evaluable_sentinel_carries_reason(self):
        self.assertEqual(_NotEvaluable("no prior FY").reason, "no prior FY")


def _rule(rule_id, kind, params, severity="note", domain="audit", **extra):
    return {"rule_id": rule_id, "kind": kind, "params": params,
            "severity": severity, "domain": domain, "status": "active",
            "statement": rule_id, **extra}


def _inline_pack(*rules):
    return {"pack_id": "inline-test", "rules": list(rules)}


class TestRunScrutinyLive(unittest.TestCase):
    """Live-ish assertions against the real site GL (read-only). These
    avoid pinning exact hit counts (site data evolves); they assert the
    engine's classification, threshold binding and reproducibility."""

    ENGAGEMENT = {"benchmark_value": 10_000_000, "percentage": 5,
                  "engagement_risk_level": "Medium", "rounding_step": 1000}

    # run_scrutiny infers company as: user default -> db default -> the single
    # Company row. Sites can carry several companies (or, on bare CI sites,
    # none — and creating an ERPNext Company there trips missing fixtures like
    # Warehouse Type "Transit"). Pin a db default from an EXISTING company for
    # the class and restore the prior state; with no Company there is no GL to
    # assert against, so the live class is honestly skipped.
    _prev_default = None

    @classmethod
    def setUpClass(cls):
        import frappe
        cls._prev_default = frappe.db.get_default("company")
        company = cls._prev_default
        if not company or not frappe.db.exists("Company", company):
            names = frappe.get_all("Company", pluck="name", limit=1)
            company = names[0] if names else None
        if not company:
            raise unittest.SkipTest(
                "no Company on this site — live GL assertions need one")
        frappe.db.set_default("company", company)

    @classmethod
    def tearDownClass(cls):
        import frappe
        if cls._prev_default:
            frappe.db.set_default("company", cls._prev_default)
        else:
            frappe.db.set_default("company", None)

    def test_new_kinds_not_unsupported(self):
        res = run_scrutiny(rule_pack=_inline_pack(
            _rule("T-ADV", "advance_in_party",
                  {"party_type": "Supplier", "side": "debit", "min_amount": 0}),
            _rule("T-FLIP", "sign_flip_yoy", {"min_amount": 0}),
            _rule("T-MSME", "msme_overdue", {"days": 45}, domain="compliance"),
            _rule("T-EXPVAR", "expense_variance_yoy", {"variance_pct": 20, "min_amount": 0},
                  domain="analytical-review"),
            _rule("T-SWING", "pl_yoy_swing", {"swing_pct": 25, "min_amount": 0},
                  domain="analytical-review"),
        ))
        self.assertEqual(res["skipped_unsupported"], [])

    def test_materiality_bound_without_config_is_not_evaluable(self):
        res = run_scrutiny(rule_pack=_inline_pack(
            _rule("T-ADV-MAT", "advance_in_party",
                  {"party_type": "Supplier", "side": "debit",
                   "min_amount": "$materiality:bs_balance"}),
        ))
        ids = [s["rule_id"] for s in res["skipped_not_evaluable"]]
        self.assertEqual(ids, ["T-ADV-MAT"])
        row = res["skipped_not_evaluable"][0]
        self.assertIn("reason", row)
        self.assertIn("materiality", row["reason"])
        # alias key for SKILL prose / SPA backward compat: same rows
        self.assertEqual(res["skipped_unconfigured"], res["skipped_not_evaluable"])

    def test_materiality_binding_enables_rule(self):
        res = run_scrutiny(
            rule_pack=_inline_pack(
                _rule("T-ADV-MAT", "advance_in_party",
                      {"party_type": "Supplier", "side": "debit",
                       "min_amount": "$materiality:bs_balance"})),
            engagement_config=self.ENGAGEMENT,
        )
        self.assertEqual(res["skipped_not_evaluable"], [])
        self.assertIsNotNone(res["materiality_used"])
        self.assertEqual(res["materiality_used"]["bs_balance"], 375000)  # performance default

    def test_yoy_kinds_report_reason_when_no_prior_fy(self):
        """On a site whose earliest Fiscal Year covers the scope, YoY rules
        must land in skipped_not_evaluable with a reason — never a silent
        zero-findings pass. If a prior FY exists they must evaluate."""
        import frappe
        res = run_scrutiny(rule_pack=_inline_pack(
            _rule("T-FLIP", "sign_flip_yoy", {"min_amount": 0}),
            _rule("T-EXPVAR", "expense_variance_yoy", {"variance_pct": 20, "min_amount": 0}),
            _rule("T-SWING", "pl_yoy_swing", {"swing_pct": 25, "min_amount": 0}),
        ))
        prior_fy = frappe.db.sql(
            """select name from `tabFiscal Year`
               where year_end_date < %s and disabled = 0 limit 1""",
            (res["scope"]["from_date"],),
        )
        skipped = {s["rule_id"]: s["reason"] for s in res["skipped_not_evaluable"]}
        if not prior_fy:
            self.assertEqual(set(skipped), {"T-FLIP", "T-EXPVAR", "T-SWING"})
            for reason in skipped.values():
                self.assertTrue(reason, "reason must be non-empty")
        else:
            self.assertNotIn("T-FLIP", skipped)  # prior FY exists -> must evaluate

    def test_msme_overdue_evaluates_and_states_basis(self):
        res = run_scrutiny(rule_pack=_inline_pack(
            _rule("T-MSME", "msme_overdue", {"days": 45}, domain="compliance",
                  severity="warning")))
        self.assertEqual(res["skipped_unsupported"], [])
        self.assertEqual(res["skipped_not_evaluable"], [])
        for f in res["findings"]:
            self.assertIn("MSME detection basis:", f["detail"])

    def test_reproducible_hit_sets(self):
        pack = _inline_pack(
            _rule("T-ADV", "advance_in_party",
                  {"party_type": "Supplier", "side": "debit", "min_amount": 0}),
            _rule("T-ADV-C", "advance_in_party",
                  {"party_type": "Customer", "side": "credit", "min_amount": 0}),
            _rule("T-MSME", "msme_overdue", {"days": 45}),
        )
        a = run_scrutiny(rule_pack=pack)
        b = run_scrutiny(rule_pack=pack)
        self.assertEqual(a["findings"], b["findings"])
        self.assertEqual(a["counts"], b["counts"])

    def test_bundled_pack_compliance_domain_covers_msme(self):
        res = run_scrutiny(domain="compliance")
        self.assertEqual(res["skipped_unsupported"], [])
        self.assertEqual(res["skipped_needs_legal_review"], [])  # all activated in v1.1.0
        msme = [f for f in res["findings"] if f["rule_id"] == "COMP-MSME-OVERDUE"]
        for f in msme:
            self.assertEqual(f["section"], "Income-Tax Act s.43B(h)")
            self.assertIn("MSME detection basis:", f["detail"])

    def test_bundled_pack_audit_domain_with_engagement(self):
        res = run_scrutiny(domain="audit", engagement_config=self.ENGAGEMENT)
        self.assertEqual(res["skipped_unsupported"], [])
        not_evaluable = {s["rule_id"] for s in res["skipped_not_evaluable"]}
        # advance rules are materiality-bound: with a config they must NOT
        # be skipped for configuration reasons
        for rid in ("LS-ADVANCE-FROM-CUSTOMER-MAT", "LS-ADVANCE-TO-SUPPLIER-MAT"):
            self.assertNotIn(rid, not_evaluable)
        # sign-flip: with a config it may only be not-evaluable for a DATA
        # reason (no prior FY / no PY GL), never a materiality one
        if "LS-SIGN-FLIP-YOY" in not_evaluable:
            row = next(s for s in res["skipped_not_evaluable"]
                       if s["rule_id"] == "LS-SIGN-FLIP-YOY")
            self.assertNotIn("materiality", row["reason"])

    def test_bundled_pack_analytical_review_domain(self):
        res = run_scrutiny(domain="analytical-review", engagement_config=self.ENGAGEMENT)
        self.assertEqual(res["skipped_unsupported"], [])
        touched = {f["rule_id"] for f in res["findings"]} \
            | {s["rule_id"] for s in res["skipped_not_evaluable"]}
        evaluated_clean = {r["rule_id"] for r in _load_pack("scrutiny-pack")["rules"]
                           if r["domain"] == "analytical-review"} - touched
        # every analytical rule is accounted for: a finding, a not-evaluable
        # row, or a clean zero-hit evaluation
        self.assertEqual(
            touched | evaluated_clean,
            {"FPA-EXPENSE-VARIANCE-YOY", "FPA-PL-YOY-SWING"},
        )


# ---------------------------------------------------------------------------
# F5 (see .superpowers/sdd/audit-findings.md): run_scrutiny ran every
# evaluator via raw frappe.db.sql with NO frappe.has_permission check
# anywhere in the file, so any role could pull full GL/Account/Supplier data
# for any company. These tests exercise the real permission decision (not a
# mocked one) against real users/roles/company records, unlike the classes
# above which pin the pure/live-GL behavior.
# ---------------------------------------------------------------------------

SCRUTINY_COMPANY_A = "_JPL Scrutiny Company A"
SCRUTINY_COMPANY_B = "_JPL Scrutiny Company B"
ROLE_NO_GRANTS = "JPL Scrutiny No Grants Role"
USER_NO_GRANTS = "jpl-scrutiny-no-grants@example.com"
# Accounts User grants role-level GL Entry + Company read, but this user is
# additionally scoped by a Company User Permission to SCRUTINY_COMPANY_A -
# the "restricted via a Company User Permission" case the audit findings
# call out (a company-restricted user asking for a DIFFERENT company).
USER_COMPANY_SCOPED = "jpl-scrutiny-company-scoped@example.com"
# ERPNext's stock "Auditor" role: granted GL Entry read (via role
# permission), but only Company "select" (not "read") - no Company User
# Permission at all. This is exactly the over-block Fix 1 addresses: an
# audit-agent user in this role must be able to run_scrutiny.
USER_AUDITOR = "jpl-scrutiny-auditor@example.com"
# A role with read on plenty of ERP doctypes but NOT GL Entry - must still
# be denied by the GL Entry read gate, unaffected by the company-scope fix.
USER_NON_GL = "jpl-scrutiny-sales@example.com"


def _ensure_role(name: str) -> None:
    if not frappe.db.exists("Role", name):
        frappe.get_doc({
            "doctype": "Role", "role_name": name, "desk_access": 1, "is_custom": 1,
        }).insert(ignore_permissions=True)


def _ensure_user(email: str, roles: tuple) -> None:
    if not frappe.db.exists("User", email):
        frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": email.split("@")[0],
            "send_welcome_email": 0,
            "enabled": 1,
            "user_type": "System User",
        }).insert(ignore_permissions=True)
    user = frappe.get_doc("User", email)
    if "System Manager" in frappe.get_roles(email):
        user.remove_roles("System Manager")
    missing = [r for r in roles if r not in frappe.get_roles(email)]
    if missing:
        user.add_roles(*missing)


def _ensure_company(name: str, abbr: str) -> None:
    if frappe.db.exists("Company", name):
        return
    # Skip default chart-of-accounts / warehouse / tax-template creation -
    # this fixture only needs a Company row for permission checks, not a
    # functioning ledger, and CI sites may be missing the fixtures those
    # hooks depend on (e.g. Warehouse Type "Transit").
    frappe.local.flags.ignore_chart_of_accounts = True
    try:
        frappe.get_doc({
            "doctype": "Company",
            "company_name": name,
            "abbr": abbr,
            "default_currency": "INR",
            "country": "India",
        }).insert(ignore_permissions=True)
    finally:
        frappe.local.flags.ignore_chart_of_accounts = False


def _ensure_user_permission(user: str, allow: str, for_value: str) -> None:
    if frappe.db.exists("User Permission", {"user": user, "allow": allow, "for_value": for_value}):
        return
    frappe.get_doc({
        "doctype": "User Permission", "user": user, "allow": allow, "for_value": for_value,
    }).insert(ignore_permissions=True)


@contextlib.contextmanager
def _as(user: str):
    orig = frappe.session.user
    frappe.set_user(user)
    try:
        yield
    finally:
        frappe.set_user(orig)


def _trivial_pack():
    # tb_balance_check just sums debit/credit over the (empty) GL for the
    # company - no seeded ledger data needed to exercise the permission
    # gate, which fires before any SQL runs.
    return {"pack_id": "inline-perm-test", "rules": [
        {"rule_id": "T-TB", "kind": "tb_balance_check", "params": {}, "severity": "note",
         "domain": "audit", "status": "active", "statement": "trial balance check"},
    ]}


class TestRunScrutinyPermissionGate(FrappeTestCase):
    """F5: run_scrutiny must gate on GL Entry read + Company read before
    running any raw SQL."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        # Roles/users are cheap, harmless to leave committed (reused
        # idempotently across runs, mirrors test_permlevel_leak.py).
        _ensure_role(ROLE_NO_GRANTS)
        _ensure_user(USER_NO_GRANTS, roles=(ROLE_NO_GRANTS,))
        _ensure_user(USER_COMPANY_SCOPED, roles=("Accounts User",))
        _ensure_user(USER_AUDITOR, roles=("Auditor",))
        _ensure_user(USER_NON_GL, roles=("Sales User",))
        frappe.db.commit()
        # Company/User Permission are NOT committed - a leftover Company
        # row changes production inference elsewhere (this very file's
        # TestRunScrutinyLive picks "the single Company on the site" as a
        # default), so these must vanish via FrappeTestCase's automatic
        # per-class rollback rather than persist across test modules.
        # They're still visible within this class's own transaction (same
        # DB connection), which is all these tests need.
        _ensure_company(SCRUTINY_COMPANY_A, "JPLSA")
        _ensure_company(SCRUTINY_COMPANY_B, "JPLSB")
        _ensure_user_permission(USER_COMPANY_SCOPED, "Company", SCRUTINY_COMPANY_A)

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_restricted_user_denied_before_any_query(self):
        with _as(USER_NO_GRANTS), self.assertRaises(frappe.PermissionError):
            run_scrutiny(
                rule_pack=_trivial_pack(), company=SCRUTINY_COMPANY_A,
                from_date="2026-01-01", to_date="2026-12-31",
            )

    def test_company_scoped_user_denied_for_other_company(self):
        # Company scoping is enforced via the Company User Permission, not
        # a Company-doctype read check (Fix 1) - the denial is now a
        # jarvis PermissionDeniedError, not frappe.PermissionError.
        with _as(USER_COMPANY_SCOPED), self.assertRaises(PermissionDeniedError):
            run_scrutiny(
                rule_pack=_trivial_pack(), company=SCRUTINY_COMPANY_B,
                from_date="2026-01-01", to_date="2026-12-31",
            )

    def test_company_scoped_user_still_succeeds_for_own_company(self):
        with _as(USER_COMPANY_SCOPED):
            res = run_scrutiny(
                rule_pack=_trivial_pack(), company=SCRUTINY_COMPANY_A,
                from_date="2026-01-01", to_date="2026-12-31",
            )
        self.assertEqual(res["scope"]["company"], SCRUTINY_COMPANY_A)
        self.assertEqual(res["skipped_unsupported"], [])

    def test_auditor_role_can_run_without_company_user_permission(self):
        # Auditor has GL Entry read but only Company "select" (not "read")
        # and no Company User Permission scoping it - under the old
        # Company-doctype-read gate this was denied entirely (the bug Fix 1
        # addresses); under the fix it must succeed, unrestricted.
        with _as(USER_AUDITOR):
            res = run_scrutiny(
                rule_pack=_trivial_pack(), company=SCRUTINY_COMPANY_A,
                from_date="2026-01-01", to_date="2026-12-31",
            )
        self.assertEqual(res["scope"]["company"], SCRUTINY_COMPANY_A)
        self.assertEqual(res["skipped_unsupported"], [])

    def test_non_gl_role_still_denied(self):
        # A role with no GL Entry read at all (e.g. Sales User) must still
        # be denied - the company-scope rework must not loosen this gate.
        with _as(USER_NON_GL), self.assertRaises(frappe.PermissionError):
            run_scrutiny(
                rule_pack=_trivial_pack(), company=SCRUTINY_COMPANY_A,
                from_date="2026-01-01", to_date="2026-12-31",
            )
