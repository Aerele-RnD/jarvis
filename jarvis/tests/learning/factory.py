"""Mini-org fixture factory for pattern-learning detector tests (plan section 11).

Fabricates a two-company org with PLANTED patterns AND planted TRAPS, then lets
the detectors run against it. Rows are written with low-level ``db_insert`` (no
ERPNext controllers / no submit validation) directly into the tab tables the
detectors read; the detectors' SQL reads those same columns, so the fixtures do
not need to be fully valid ERPNext documents. Every row is named ``_JPL-*`` so
:func:`wipe` is a single idempotent ``LIKE`` sweep (reused by the E2E harness).

Planted patterns (company _JPL-Alpha):
  * customer DealerD -> price list "Dealer Pricing" (sell-customer-price-list)
  * Customer Group "Dealer" -> "30 Days" terms 58/60 (sell-group-payment-terms)
  * supplier AcmeNonStock -> non-stock only 40/40 (buy-supplier-stockness)
  * supplier BoltSupply -> item group "Fasteners" (buy-supplier-itemgroup)
  * supplier TaxHabit -> tax template "Alpha GST 18%" 24/25 (buy-supplier-tax-template)
  * quotations valid 15 days vs +1-month default (sell-quotation-validity)
  * habitual letter head vs company default (sell-tc-letterhead)
  * customer-specific Item Prices for 12 customers (sell-selective-item-pricing)
  * Purchase Invoices booked with update_stock (buy-pi-update-stock)
  * item group -> warehouse, 2 balanced warehouses (stock-itemgroup-warehouse)
  * stock-entry purpose -> route (stock-entry-purpose-mix)
  * payment direction -> mode of payment (acct-mode-of-payment)
  * project type "External" -> timesheet-billed (proj-billing-method)

Planted traps:
  * child-row inflation: supplier InflateCo, 6 POs x 10 lines (unit counting)
  * go-live burst: company Beta PIs, all one second (spread gate)
  * sole-value: company Beta single price list / single term (variance gate)
  * vanilla-default: company Beta quotations valid +1 month (S5 system-default gate)
  * multi-plant: company Beta ships from 5 warehouses (single-plant guard)
"""

from __future__ import annotations

import frappe

ALPHA = "_JPL-Alpha Ltd"
BETA = "_JPL-Beta Ltd"
PREFIX = "_JPL-"
LETTER_HEAD = "_JPL-Alpha Header"

# Doctypes wiped by the _JPL- name sweep (children before parents is harmless
# without FKs, but we list children first anyway).
_WIPE_DOCTYPES = (
	"Sales Invoice Item",
	"Purchase Order Item",
	"Stock Entry Detail",
	"Sales Invoice",
	"Purchase Order",
	"Purchase Invoice",
	"Payment Entry",
	"Quotation",
	"Stock Entry",
	"Timesheet",
	"Project",
	"Item Price",
	"Item",
	"Company",
)

# What the tests assert. company-scoped detectors are isolated by the company
# filter; org-wide ones (naming-series, default-vs-usage) are unit-tested with a
# fake facade instead, so they are not listed here.
EXPECT = {
	"companies": {"alpha": ALPHA, "beta": BETA},
	"dealer_customer": "_JPL-DealerD",
	"dealer_price_list": "Dealer Pricing",
	"dealer_group": "Dealer",
	"dealer_terms": "30 Days",
	"acme_supplier": "_JPL-AcmeNonStock",
	"bolt_supplier": "_JPL-BoltSupply",
	"bolt_item_group": "Fasteners",
	"taxhabit_supplier": "_JPL-TaxHabit",
	"taxhabit_template": "Alpha GST 18%",
	"inflate_supplier": "_JPL-InflateCo",
	"quotation_days": 15,
	"selective_customers": 12,
}


# ---------------------------------------------------------------------------
# low-level insert
# ---------------------------------------------------------------------------
def _insert(doctype, name, fields, docstatus=1, creation=None, children=None):
	doc = frappe.new_doc(doctype)
	doc.update(fields)
	doc.name = name
	doc.flags.name_set = True
	doc.docstatus = docstatus
	doc.db_insert()
	ts = creation or (str(fields.get("posting_date") or fields.get("transaction_date") or "2025-09-01") + " 10:00:00")
	frappe.db.set_value(doctype, name, {"creation": ts, "modified": ts}, update_modified=False)
	for childfield, (child_dt, rows) in (children or {}).items():
		for i, row in enumerate(rows):
			cname = f"{name}-{childfield}-{i + 1}"
			cd = frappe.new_doc(child_dt)
			cd.update(row)
			cd.parent = name
			cd.parenttype = doctype
			cd.parentfield = childfield
			cd.idx = i + 1
			cd.name = cname
			cd.flags.name_set = True
			cd.docstatus = docstatus
			cd.db_insert()
			frappe.db.set_value(child_dt, cname, {"creation": ts, "modified": ts}, update_modified=False)
	return name


def _day(base_ordinal: int) -> str:
	"""A distinct calendar day per index, inside the 18-month window (today is
	well after 2025-09). Distinct days => spread gate passes and consecutive
	rows never collapse as a creation burst."""
	return frappe.utils.add_days("2025-09-01", base_ordinal)


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def build(commit: bool = False) -> None:
	"""Idempotent: wipe any prior fixtures, then seed the mini-org. Detectors
	can then run in the same transaction (tests, no commit) or the caller can
	commit for the E2E harness."""
	wipe(commit=False)
	_masters()
	_selling_alpha()
	_buying_alpha()
	_accounts_alpha()
	_stock_alpha()
	_projects_alpha()
	_selective_pricing()
	_beta_traps()
	if commit:
		frappe.db.commit()


def wipe(commit: bool = False) -> None:
	for dt in _WIPE_DOCTYPES:
		try:
			frappe.db.delete(dt, {"name": ("like", f"{PREFIX}%")})
		except Exception:
			pass
	if commit:
		frappe.db.commit()


# ---------------------------------------------------------------------------
# masters
# ---------------------------------------------------------------------------
def _masters() -> None:
	for name, cur, lh in ((ALPHA, "INR", ""), (BETA, "INR", "")):
		_insert(
			"Company",
			name,
			{
				"company_name": name,
				"abbr": name.replace("_JPL-", "").replace(" ", "")[:8],
				"default_currency": cur,
				"country": "India",
				"default_letter_head": lh,
				"default_selling_terms": "",
			},
			docstatus=0,
		)
	items = (
		("_JPL-ItemNonStock", "Services", 0),
		("_JPL-ItemStock", "Fasteners", 1),
		("_JPL-ItemWidget", "Widgets", 1),
		("_JPL-ItemElec", "Electronics", 1),
		("_JPL-ItemFurn", "Furniture", 1),
	)
	for code, group, is_stock in items:
		_insert(
			"Item",
			code,
			{
				"item_code": code,
				"item_name": code,
				"item_group": group,
				"is_stock_item": is_stock,
				"stock_uom": "Nos",
			},
			docstatus=0,
		)


# ---------------------------------------------------------------------------
# selling (Sales Invoices): price list, payment terms, tc/letterhead, warehouse
# ---------------------------------------------------------------------------
def _selling_alpha() -> None:
	# (customer, group, price_list, terms, count)
	blocks = [
		("_JPL-DealerD", "Dealer", "Dealer Pricing", ["30 Days"] * 25),
		("_JPL-DealerE", "Dealer", "Dealer Pricing", ["30 Days"] * 20),
		("_JPL-DealerF", "Dealer", "Standard Selling", ["30 Days"] * 13 + ["15 Days"] * 2),
		("_JPL-RetailR", "Retail", "Standard Selling", ["15 Days"] * 22),
	]
	ordinal = 0
	for customer, group, price_list, terms_list in blocks:
		for terms in terms_list:
			# first 40 SIs -> Electronics/Main, rest -> Furniture/Bulk (balanced,
			# single-plant: exactly two warehouses).
			if ordinal < 40:
				item_group, warehouse = "Electronics", "WH-Alpha-Main"
			else:
				item_group, warehouse = "Furniture", "WH-Alpha-Bulk"
			name = f"{PREFIX}SI-A-{ordinal:04d}"
			_insert(
				"Sales Invoice",
				name,
				{
					"customer": customer,
					"customer_group": group,
					"selling_price_list": price_list,
					"payment_terms_template": terms,
					"letter_head": LETTER_HEAD,
					"tc_name": "",
					"company": ALPHA,
					"posting_date": _day(ordinal),
				},
				children={
					"items": (
						"Sales Invoice Item",
						[{"item_code": "_JPL-ItemElec", "item_name": "_JPL-ItemElec",
						  "item_group": item_group, "warehouse": warehouse, "qty": 1, "rate": 100}],
					)
				},
			)
			ordinal += 1


# ---------------------------------------------------------------------------
# buying (Purchase Orders + Purchase Invoices)
# ---------------------------------------------------------------------------
def _buying_alpha() -> None:
	def po(idx, supplier, item_code, item_group, taxes, lines=1):
		name = f"{PREFIX}PO-A-{idx:04d}"
		rows = [
			{"item_code": item_code, "item_group": item_group, "qty": 1, "rate": 10,
			 "schedule_date": _day(idx)}
			for _ in range(lines)
		]
		_insert(
			"Purchase Order",
			name,
			{"supplier": supplier, "company": ALPHA, "transaction_date": _day(idx),
			 "taxes_and_charges": taxes},
			children={"items": ("Purchase Order Item", rows)},
		)

	idx = 0
	for _ in range(40):  # Acme: non-stock only
		po(idx, "_JPL-AcmeNonStock", "_JPL-ItemNonStock", "Services", "Alpha GST 5%")
		idx += 1
	for _ in range(35):  # Bolt: Fasteners, stock
		po(idx, "_JPL-BoltSupply", "_JPL-ItemStock", "Fasteners", "Alpha GST 12%")
		idx += 1
	for j in range(25):  # TaxHabit: 24x 18% + 1x 5%
		taxes = "Alpha GST 5%" if j == 0 else "Alpha GST 18%"
		po(idx, "_JPL-TaxHabit", "_JPL-ItemStock", "Fasteners", taxes)
		idx += 1
	for _ in range(6):  # InflateCo child-row trap: 6 POs x 10 lines
		po(idx, "_JPL-InflateCo", "_JPL-ItemWidget", "Widgets", "Alpha GST 12%", lines=10)
		idx += 1

	# Purchase Invoices with update_stock=1, spread across days (legit habit).
	for k in range(34):
		name = f"{PREFIX}PI-A-{k:04d}"
		_insert(
			"Purchase Invoice",
			name,
			{"supplier": "_JPL-BoltSupply", "company": ALPHA,
			 "posting_date": _day(k), "update_stock": 1},
		)


# ---------------------------------------------------------------------------
# accounts (Payment Entries)
# ---------------------------------------------------------------------------
def _accounts_alpha() -> None:
	# Receive: 30 Bank Draft + 3 Cash ; Pay: 30 Cash + 2 Bank Draft
	plan = (
		["Bank Draft"] * 30 + ["Cash"] * 3,  # Receive
		["Cash"] * 30 + ["Bank Draft"] * 2,  # Pay
	)
	idx = 0
	for ptype, modes in zip(("Receive", "Pay"), plan):
		for mode in modes:
			name = f"{PREFIX}PE-A-{idx:04d}"
			_insert(
				"Payment Entry",
				name,
				{"payment_type": ptype, "mode_of_payment": mode, "company": ALPHA,
				 "posting_date": _day(idx), "party_type": "Customer",
				 "party": "_JPL-DealerD", "paid_amount": 100, "received_amount": 100},
			)
			idx += 1

	# Quotations valid 15 days (diverges from the +1-month default).
	for q in range(32):
		td = _day(q)
		name = f"{PREFIX}QTN-A-{q:04d}"
		_insert(
			"Quotation",
			name,
			{"company": ALPHA, "transaction_date": td,
			 "valid_till": frappe.utils.add_days(td, 15),
			 "quotation_to": "Customer", "party_name": "_JPL-DealerD"},
		)


# ---------------------------------------------------------------------------
# stock (Stock Entries)
# ---------------------------------------------------------------------------
def _stock_alpha() -> None:
	# 32 Material Transfer (Main -> Bulk) + 30 Material Receipt (-> Main)
	idx = 0
	for _ in range(32):
		name = f"{PREFIX}SE-A-{idx:04d}"
		_insert(
			"Stock Entry",
			name,
			{"company": ALPHA, "posting_date": _day(idx),
			 "purpose": "Material Transfer", "stock_entry_type": "Material Transfer"},
			children={"items": ("Stock Entry Detail", [
				{"s_warehouse": "WH-Alpha-Main", "t_warehouse": "WH-Alpha-Bulk",
				 "item_code": "_JPL-ItemStock", "qty": 1}])},
		)
		idx += 1
	for _ in range(30):
		name = f"{PREFIX}SE-A-{idx:04d}"
		_insert(
			"Stock Entry",
			name,
			{"company": ALPHA, "posting_date": _day(idx),
			 "purpose": "Material Receipt", "stock_entry_type": "Material Receipt"},
			children={"items": ("Stock Entry Detail", [
				{"s_warehouse": "", "t_warehouse": "WH-Alpha-Main",
				 "item_code": "_JPL-ItemStock", "qty": 1}])},
		)
		idx += 1


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------
def _projects_alpha() -> None:
	# 22 External (20 timesheet-billed) + 10 Internal (fixed)
	idx = 0
	for j in range(22):
		name = f"{PREFIX}PRJ-A-{idx:04d}"
		_insert(
			"Project",
			name,
			{"project_name": name, "project_type": "External", "company": ALPHA},
			docstatus=0,
			creation=f"{_day(idx)} 10:00:00",
		)
		if j < 20:
			ts_name = f"{PREFIX}TS-A-{idx:04d}"
			_insert(
				"Timesheet",
				ts_name,
				{"company": ALPHA, "parent_project": name},
				creation=f"{_day(idx)} 11:00:00",
			)
		idx += 1
	for _ in range(10):
		name = f"{PREFIX}PRJ-A-{idx:04d}"
		_insert(
			"Project",
			name,
			{"project_name": name, "project_type": "Internal", "company": ALPHA},
			docstatus=0,
			creation=f"{_day(idx)} 10:00:00",
		)
		idx += 1


# ---------------------------------------------------------------------------
# selective item pricing (org-wide existence)
# ---------------------------------------------------------------------------
def _selective_pricing() -> None:
	for j in range(EXPECT["selective_customers"]):
		name = f"{PREFIX}IP-{j:04d}"
		_insert(
			"Item Price",
			name,
			{"customer": f"{PREFIX}IPCust{j}", "price_list": "Dealer Pricing",
			 "item_code": "_JPL-ItemStock", "selling": 1, "price_list_rate": 100 + j},
			docstatus=0,
		)


# ---------------------------------------------------------------------------
# company Beta: all traps
# ---------------------------------------------------------------------------
def _beta_traps() -> None:
	# sole-value (single price list + single term) + multi-plant (5 warehouses)
	for i in range(30):
		name = f"{PREFIX}SI-B-{i:04d}"
		warehouse = f"WH-Beta-{(i % 5) + 1}"
		_insert(
			"Sales Invoice",
			name,
			{"customer": f"{PREFIX}BetaCust{i % 6}", "customer_group": "Wholesale",
			 "selling_price_list": "Standard Selling", "payment_terms_template": "Net 30",
			 "letter_head": "", "tc_name": "", "company": BETA, "posting_date": _day(i)},
			children={"items": ("Sales Invoice Item", [
				{"item_code": "_JPL-ItemElec", "item_name": "_JPL-ItemElec",
				 "item_group": "Electronics", "warehouse": warehouse, "qty": 1, "rate": 100}])},
		)
	# vanilla-default quotations (valid +1 month, spread over days so only the
	# system-default gate suppresses them, not the spread gate).
	for i in range(30):
		td = _day(i)
		name = f"{PREFIX}QTN-B-{i:04d}"
		_insert(
			"Quotation",
			name,
			{"company": BETA, "transaction_date": td,
			 "valid_till": frappe.utils.add_days(td, 30),
			 "quotation_to": "Customer", "party_name": f"{PREFIX}BetaCust{i % 6}"},
		)
	# go-live burst: 35 PIs, all one day and one creation second -> spread gate.
	burst_ts = "2025-10-01 03:00:00"
	for i in range(35):
		name = f"{PREFIX}PI-B-{i:04d}"
		_insert(
			"Purchase Invoice",
			name,
			{"supplier": f"{PREFIX}BetaSup", "company": BETA,
			 "posting_date": "2025-10-01", "update_stock": 1},
			creation=burst_ts,
		)
