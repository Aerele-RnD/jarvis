"""Validation + envelope tests for the Tier-2a ERPNext computed-read
tools: get_stock_balance, get_valuation_rate, scan_barcode,
get_balance_on, get_customer_outstanding, get_party_dashboard_info,
get_exchange_rate, get_fiscal_year, get_itemised_tax_breakup.

These tools wrap ERPNext helpers that depend on fully-configured
company / chart-of-accounts / item master / fiscal year records.
Seeding all of that for unit tests is heavy and brittle (the master-
data defaults differ across ERPNext releases). The tests here pin
the boundary contract - arg validation, envelope shape, perm gating -
by patching:

  - ``frappe.db.exists`` for the existence checks (so tests don't
    care whether the bench is seeded)
  - the underlying ERPNext helper itself (so we assert the wrapper
    forwards args + reshapes the return correctly)

The ERPNext computations themselves are tested upstream.
"""
from __future__ import annotations

from datetime import date as _date
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError
from jarvis.tools.get_balance_on import get_balance_on
from jarvis.tools.get_customer_outstanding import get_customer_outstanding
from jarvis.tools.get_exchange_rate import get_exchange_rate
from jarvis.tools.get_fiscal_year import get_fiscal_year
from jarvis.tools.get_itemised_tax_breakup import get_itemised_tax_breakup
from jarvis.tools.get_party_dashboard_info import get_party_dashboard_info
from jarvis.tools.get_stock_balance import get_stock_balance
from jarvis.tools.get_valuation_rate import get_valuation_rate
from jarvis.tools.scan_barcode import scan_barcode


def _all_exist():
    """Patch ``frappe.db.exists`` to return True for every check.

    Used by happy-path tests where the test doesn't care whether the
    bench actually has the named master record - only whether the
    wrapper forwards correct args to the underlying helper.
    """
    return patch("frappe.db.exists", return_value=True)


def _no_exists():
    """Inverse of ``_all_exist`` - drives the InvalidArgumentError
    branches for "unknown <doctype>" without depending on the bench
    being unseeded."""
    return patch("frappe.db.exists", return_value=False)


def _allow_perm():
    """Patch ``frappe.has_permission`` to return True so the wrappers
    don't bail at the perm gate during happy-path envelope tests."""
    return patch("frappe.has_permission", return_value=True)


# ---------------------------------------------------------------------
# get_stock_balance
# ---------------------------------------------------------------------


class TestGetStockBalance(FrappeTestCase):
    def test_rejects_empty_item_code(self):
        with self.assertRaises(InvalidArgumentError):
            get_stock_balance("", "_T-Warehouse")

    def test_rejects_empty_warehouse(self):
        with self.assertRaises(InvalidArgumentError):
            get_stock_balance("_T-Item", "")

    def test_rejects_unknown_item(self):
        with _no_exists(), self.assertRaises(InvalidArgumentError):
            get_stock_balance("Definitely-Not-An-Item", "_T-Warehouse")

    def test_returns_qty_envelope_without_rate(self):
        with _all_exist(), patch(
            "erpnext.stock.utils.get_stock_balance", return_value=42.5,
        ):
            out = get_stock_balance("_T-Item", "_T-Warehouse")
        self.assertEqual(out, {"qty": 42.5})

    def test_returns_qty_and_rate_envelope_when_requested(self):
        with _all_exist(), patch(
            "erpnext.stock.utils.get_stock_balance", return_value=(42.5, 12.75),
        ):
            out = get_stock_balance(
                "_T-Item", "_T-Warehouse", with_valuation_rate=True,
            )
        self.assertEqual(out, {"qty": 42.5, "rate": 12.75})


# ---------------------------------------------------------------------
# get_valuation_rate
# ---------------------------------------------------------------------


class TestGetValuationRate(FrappeTestCase):
    def test_rejects_empty_item(self):
        with self.assertRaises(InvalidArgumentError):
            get_valuation_rate("", "_T-Co")

    def test_rejects_empty_company(self):
        with self.assertRaises(InvalidArgumentError):
            get_valuation_rate("_T-Item", "")

    def test_returns_rate_envelope_from_bare_number(self):
        with _all_exist(), _allow_perm(), patch(
            "erpnext.stock.get_item_details.get_valuation_rate",
            return_value=99.5,
        ):
            out = get_valuation_rate("_T-Item", "_T-Co")
        self.assertEqual(out, {"rate": 99.5})

    def test_returns_rate_envelope_from_dict(self):
        with _all_exist(), _allow_perm(), patch(
            "erpnext.stock.get_item_details.get_valuation_rate",
            return_value={"valuation_rate": 88.0},
        ):
            out = get_valuation_rate("_T-Item", "_T-Co")
        self.assertEqual(out, {"rate": 88.0})


# ---------------------------------------------------------------------
# scan_barcode
# ---------------------------------------------------------------------


class TestScanBarcode(FrappeTestCase):
    def test_rejects_empty(self):
        with self.assertRaises(InvalidArgumentError):
            scan_barcode("")

    def test_returns_dict_envelope_when_helper_returns_dict(self):
        with patch(
            "erpnext.stock.utils.scan_barcode",
            return_value={"item_code": "X", "barcode": "012"},
        ):
            out = scan_barcode("012")
        self.assertEqual(out, {"item_code": "X", "barcode": "012"})


# ---------------------------------------------------------------------
# get_balance_on
# ---------------------------------------------------------------------


class TestGetBalanceOn(FrappeTestCase):
    def test_rejects_when_no_account_or_party(self):
        with self.assertRaises(InvalidArgumentError):
            get_balance_on()

    def test_returns_envelope_for_account_only(self):
        with _all_exist(), patch(
            "erpnext.accounts.utils.get_balance_on", return_value=1500.0,
        ):
            out = get_balance_on(account="_T-Acct", date="2026-06-18")
        self.assertEqual(out["balance"], 1500.0)
        self.assertEqual(out["account"], "_T-Acct")
        self.assertEqual(out["date"], "2026-06-18")


# ---------------------------------------------------------------------
# get_customer_outstanding
# ---------------------------------------------------------------------


class TestGetCustomerOutstanding(FrappeTestCase):
    def test_rejects_empty_customer(self):
        with self.assertRaises(InvalidArgumentError):
            get_customer_outstanding("", "Any-Co")

    def test_returns_envelope(self):
        with _all_exist(), _allow_perm(), patch(
            "erpnext.selling.doctype.customer.customer.get_customer_outstanding",
            return_value=2500.0,
        ):
            out = get_customer_outstanding("_T-Customer", "_T-Co")
        self.assertEqual(out["outstanding"], 2500.0)
        self.assertEqual(out["customer"], "_T-Customer")
        self.assertEqual(out["company"], "_T-Co")


# ---------------------------------------------------------------------
# get_party_dashboard_info
# ---------------------------------------------------------------------


class TestGetPartyDashboardInfo(FrappeTestCase):
    def test_rejects_invalid_party_type(self):
        with self.assertRaises(InvalidArgumentError):
            get_party_dashboard_info("Employee", "any")

    def test_rejects_empty_party(self):
        with self.assertRaises(InvalidArgumentError):
            get_party_dashboard_info("Customer", "")

    def test_returns_envelope(self):
        with _all_exist(), _allow_perm(), patch(
            "erpnext.accounts.party.get_dashboard_info",
            return_value=[{"company": "X", "total_unpaid": 100}],
        ):
            out = get_party_dashboard_info("Customer", "_T-Customer")
        self.assertEqual(out["party_type"], "Customer")
        self.assertEqual(out["party"], "_T-Customer")
        self.assertEqual(out["dashboard"], [{"company": "X", "total_unpaid": 100}])


# ---------------------------------------------------------------------
# get_exchange_rate
# ---------------------------------------------------------------------


class TestGetExchangeRate(FrappeTestCase):
    def test_rejects_empty(self):
        with self.assertRaises(InvalidArgumentError):
            get_exchange_rate("", "INR")

    def test_returns_envelope(self):
        with _all_exist(), patch(
            "erpnext.setup.utils.get_exchange_rate", return_value=83.25,
        ):
            out = get_exchange_rate("USD", "INR", "2026-06-18")
        self.assertEqual(out["rate"], 83.25)
        self.assertEqual(out["from_currency"], "USD")
        self.assertEqual(out["to_currency"], "INR")
        self.assertEqual(out["transaction_date"], "2026-06-18")


# ---------------------------------------------------------------------
# get_fiscal_year
# ---------------------------------------------------------------------


class TestGetFiscalYear(FrappeTestCase):
    def test_rejects_when_neither_date_nor_fiscal_year(self):
        with self.assertRaises(InvalidArgumentError):
            get_fiscal_year()

    def test_returns_envelope(self):
        with _all_exist(), patch(
            "erpnext.accounts.utils.get_fiscal_year",
            return_value=("FY26", _date(2025, 4, 1), _date(2026, 3, 31)),
        ):
            out = get_fiscal_year(date="2025-12-15")
        self.assertEqual(out["fiscal_year"], "FY26")
        self.assertEqual(out["year_start_date"], "2025-04-01")
        self.assertEqual(out["year_end_date"], "2026-03-31")


# ---------------------------------------------------------------------
# get_itemised_tax_breakup
# ---------------------------------------------------------------------


class TestGetItemisedTaxBreakup(FrappeTestCase):
    def test_rejects_unsupported_doctype(self):
        with self.assertRaises(InvalidArgumentError):
            get_itemised_tax_breakup("Address", "x")

    def test_rejects_empty_name(self):
        with self.assertRaises(InvalidArgumentError):
            get_itemised_tax_breakup("Sales Invoice", "")

    def test_rejects_unknown_doc(self):
        with _no_exists(), self.assertRaises(InvalidArgumentError):
            get_itemised_tax_breakup("Sales Invoice", "SINV-not-a-real-doc")

    def test_returns_envelope(self):
        # The wrapper calls frappe.get_doc to load the source; rather
        # than seed a Sales Invoice (heavy + brittle across releases)
        # we patch get_doc to return a sentinel and assert
        # get_itemised_tax was called with it.
        sentinel_doc = object()
        with _all_exist(), _allow_perm(), patch(
            "frappe.get_doc", return_value=sentinel_doc,
        ), patch(
            "erpnext.controllers.taxes_and_totals.get_itemised_tax",
            return_value={"_T-Item": {"VAT - X": 18.0}},
        ) as git:
            out = get_itemised_tax_breakup("Sales Invoice", "SINV-001")
        git.assert_called_once()
        self.assertIs(git.call_args.args[0], sentinel_doc)
        self.assertEqual(out["doctype"], "Sales Invoice")
        self.assertEqual(out["name"], "SINV-001")
        self.assertEqual(out["itemised_tax"], {"_T-Item": {"VAT - X": 18.0}})
