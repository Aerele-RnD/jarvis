"""Declarative detector registry (plan sections 4.3, 4.4).

Adding a detector = one dict here + a SQL string (or postprocess fn) in the
matching ``detectors/`` module + one skill template id. Zero plumbing.

Spec schema (plan section 4.3, plus executor-facing keys):
  id, version, domain, role_priors, doctype, unit ('parent'|'party'|'month';
  'event' for Access-Log stream detectors, justified on the spec),
  company_scoped, window_months, sql_shape (S1..S5), sql (dotted 'module.ATTR'
  or None), antecedent, consequent, gates {n_min, c_min, phrasing}, sensitivity
  (A/B/C), skill_template, field_guards [(doctype, field)...], requires_app[],
  requires_source (None/'access_log'), postprocess (None or dotted 'module.fn').

Executor-facing extras (all optional):
  antecedent_kind ('party'|'group'|'org'|'doctype') drives content escalation
  and exception clustering; consequent_field feeds the always/only enforcement
  cross-ref; unit_doctype is the human label in the evidence line; vars_map maps
  skill-template placeholders to 'antecedent'/'consequent'; org_default_consequent
  suppresses a vanilla org default; target_consequents restricts which mode
  values may propose; single_plant_max_warehouses bounds the stock guard.

Tiering (plan section 4.4): every spec carries a 'tier' key (1 or 2; specs
without the key default to 1). Tier-2 specs run through the exact same
executor/gate machinery - the tier is registry metadata for seeding,
readiness reporting and rollout, never a behavior branch.

The §4.4 header says "Tier-1 (14)"; the enumerated list is 15 (an off-by-one
in the plan). All 15 enumerated detectors ship here.
"""

from __future__ import annotations

REGISTRY_VERSION = 2  # 2: Tier-2 detector pack (plan sections 4.2, 4.4)

_SELLING_ROLES = ["Sales User", "Sales Manager", "Sales Master Manager"]
_BUYING_ROLES = ["Purchase User", "Purchase Manager", "Purchase Master Manager"]
_STOCK_ROLES = ["Stock User", "Stock Manager", "Item Manager"]
_ACCOUNTS_ROLES = ["Accounts User", "Accounts Manager"]
_PROJECTS_ROLES = ["Projects User", "Projects Manager"]
_CONFIG_ROLES = ["System Manager"]
_MFG_ROLES = ["Manufacturing User", "Manufacturing Manager"]


# Ordered party-personalization first, then other party-specific, then A-class
# aggregates, then config cleanup (plan section 6.4 surfacing priority; the
# engine's remaining-units list inherits this order).
DETECTORS: list[dict] = [
	# --- party-specific personalization (B) ---------------------------------
	{
		"id": "sell-customer-price-list",
		"version": 1,
		"domain": "selling",
		"role_priors": _SELLING_ROLES,
		"doctype": "Sales Invoice",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S1",
		"sql": "selling.CUSTOMER_PRICE_LIST_SQL",
		"antecedent": "customer",
		"consequent": "selling_price_list",
		"gates": {"n_min": 20, "c_min": 0.95, "phrasing": "usually"},
		"sensitivity": "B",
		"skill_template": "customer-price-list",
		"field_guards": [
			("Sales Invoice", "selling_price_list"),
			("Sales Invoice", "customer"),
			("Sales Invoice", "posting_date"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": None,
		"antecedent_kind": "party",
		"unit_doctype": "Sales Invoices",
		"vars_map": {"customer": "antecedent", "price_list": "consequent"},
	},
	{
		"id": "buy-supplier-itemgroup",
		"version": 1,
		"domain": "buying",
		"role_priors": _BUYING_ROLES,
		"doctype": "Purchase Order",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S1",
		"sql": "buying.SUPPLIER_ITEMGROUP_SQL",
		"antecedent": "supplier",
		"consequent": "item_group",
		"gates": {"n_min": 30, "c_min": 0.90, "phrasing": "usually"},
		"sensitivity": "B",
		"skill_template": "supplier-itemgroup",
		"field_guards": [
			("Purchase Order Item", "item_group"),
			("Purchase Order", "supplier"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": None,
		"antecedent_kind": "party",
		"unit_doctype": "Purchase Orders",
		"vars_map": {"supplier": "antecedent", "item_group": "consequent"},
	},
	{
		"id": "buy-supplier-stockness",
		"version": 1,
		"domain": "buying",
		"role_priors": _BUYING_ROLES,
		"doctype": "Purchase Order",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S2",
		"sql": "buying.SUPPLIER_STOCKNESS_SQL",
		"antecedent": "supplier",
		"consequent": "is_stock_item==0",
		# Tier-1 ships the TENDENCY gate (plan §4.2: "20/0.90 tendency"). The
		# strict "only" claim (60 units, 0 exceptions) is a High-band refinement
		# the compiler reads off the evidence, not a separate spec.
		"gates": {"n_min": 20, "c_min": 0.90, "phrasing": "usually"},
		"sensitivity": "B",
		"skill_template": "supplier-stockness",
		"field_guards": [
			("Purchase Order Item", "item_code"),
			("Item", "is_stock_item"),
			("Purchase Order", "supplier"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": None,
		"antecedent_kind": "party",
		"consequent_field": "is_stock_item",
		"unit_doctype": "Purchase Orders",
		"target_consequents": ["non_stock"],
		"vars_map": {"supplier": "antecedent"},
	},
	{
		"id": "buy-supplier-tax-template",
		"version": 1,
		"domain": "buying",
		"role_priors": _BUYING_ROLES,
		"doctype": "Purchase Order",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S1",
		"sql": "buying.SUPPLIER_TAX_TEMPLATE_SQL",
		"antecedent": "supplier",
		"consequent": "taxes_and_charges",
		"gates": {"n_min": 20, "c_min": 0.95, "phrasing": "usually"},
		"sensitivity": "B",
		"skill_template": "supplier-tax-template",
		"field_guards": [
			("Purchase Order", "taxes_and_charges"),
			("Purchase Order", "supplier"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": None,
		"antecedent_kind": "party",
		"unit_doctype": "Purchase Orders",
		"vars_map": {"supplier": "antecedent", "tax_template": "consequent"},
	},
	# --- other party/process-control (B) ------------------------------------
	{
		"id": "sell-selective-item-pricing",
		"version": 1,
		"domain": "selling",
		"role_priors": _SELLING_ROLES,
		"doctype": "Item Price",
		"unit": "party",
		"company_scoped": False,
		"window_months": 18,
		"sql_shape": "S2",
		"sql": "selling.SELECTIVE_ITEM_PRICING_SQL",
		"antecedent": "org",
		"consequent": "item_price.customer",
		"gates": {"n_min": 10, "c_min": 1.0, "phrasing": "usually"},
		"sensitivity": "B",
		"skill_template": "selective-item-pricing",
		"field_guards": [("Item Price", "customer"), ("Item Price", "selling")],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "selling.postprocess_selective_item_pricing",
		"antecedent_kind": "org",
		"unit_doctype": "customers",
	},
	{
		"id": "buy-pi-update-stock",
		"version": 1,
		"domain": "buying",
		"role_priors": _BUYING_ROLES,
		"doctype": "Purchase Invoice",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S2",
		"sql": "buying.PI_UPDATE_STOCK_SQL",
		"antecedent": "org",
		"consequent": "update_stock==1",
		"gates": {"n_min": 30, "c_min": 0.90, "phrasing": "usually"},
		"sensitivity": "B",
		"skill_template": "pi-update-stock",
		"field_guards": [("Purchase Invoice", "update_stock")],
		"requires_app": [],
		"requires_source": None,
		"postprocess": None,
		"antecedent_kind": "org",
		"consequent_field": "update_stock",
		"unit_doctype": "Purchase Invoices",
		"org_default_consequent": "0",
		"vars_map": {},
	},
	# --- A-class aggregates --------------------------------------------------
	{
		"id": "sell-group-payment-terms",
		"version": 1,
		"domain": "selling",
		"role_priors": _SELLING_ROLES,
		"doctype": "Sales Invoice",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S1",
		"sql": "selling.GROUP_PAYMENT_TERMS_SQL",
		"antecedent": "customer_group",
		"consequent": "payment_terms_template",
		"gates": {"n_min": 30, "c_min": 0.90, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "group-payment-terms",
		"field_guards": [
			("Sales Invoice", "payment_terms_template"),
			("Sales Invoice", "customer_group"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": None,
		"antecedent_kind": "group",
		"consequent_field": "payment_terms_template",
		"unit_doctype": "Sales Invoices",
		"vars_map": {"group": "antecedent", "terms": "consequent"},
	},
	{
		"id": "sell-quotation-validity",
		"version": 1,
		"domain": "selling",
		"role_priors": _SELLING_ROLES,
		"doctype": "Quotation",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S5",
		"sql": "selling.QUOTATION_VALIDITY_SQL",
		"antecedent": "org",
		"consequent": "valid_till_gap_days",
		"gates": {"n_min": 30, "c_min": 0.80, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "quotation-validity",
		"field_guards": [
			("Quotation", "valid_till"),
			("Quotation", "transaction_date"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "selling.postprocess_quotation_validity",
		"antecedent_kind": "org",
		"unit_doctype": "Quotations",
	},
	{
		"id": "sell-tc-letterhead",
		"version": 1,
		"domain": "selling",
		"role_priors": _SELLING_ROLES,
		"doctype": "Sales Invoice",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S5",
		"sql": "selling.TC_LETTERHEAD_SQL",
		"antecedent": "org",
		"consequent": "letter_head/tc_name",
		"gates": {"n_min": 30, "c_min": 0.90, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "tc-letterhead",
		"field_guards": [
			("Sales Invoice", "letter_head"),
			("Sales Invoice", "tc_name"),
			("Company", "default_letter_head"),
			("Company", "default_selling_terms"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "selling.postprocess_tc_letterhead",
		"antecedent_kind": "org",
		"unit_doctype": "Sales Invoices",
	},
	{
		"id": "stock-itemgroup-warehouse",
		"version": 1,
		"domain": "stock",
		"role_priors": _STOCK_ROLES,
		"doctype": "Sales Invoice",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S5",
		"sql": "stock.ITEMGROUP_WAREHOUSE_SQL",
		"antecedent": "item_group",
		"consequent": "warehouse",
		"gates": {"n_min": 30, "c_min": 0.90, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "itemgroup-warehouse",
		"field_guards": [
			("Sales Invoice Item", "item_group"),
			("Sales Invoice Item", "warehouse"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "stock.postprocess_itemgroup_warehouse",
		"antecedent_kind": "group",
		"unit_doctype": "Sales Invoices",
		"single_plant_max_warehouses": 3,
		"vars_map": {"item_group": "antecedent", "warehouse": "consequent"},
	},
	{
		"id": "stock-entry-purpose-mix",
		"version": 1,
		"domain": "stock",
		"role_priors": _STOCK_ROLES,
		"doctype": "Stock Entry",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S1",
		"sql": "stock.STOCK_ENTRY_ROUTE_SQL",
		"antecedent": "purpose",
		"consequent": "warehouse_route",
		"gates": {"n_min": 30, "c_min": 0.80, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "stock-entry-route",
		"field_guards": [
			("Stock Entry", "purpose"),
			("Stock Entry Detail", "s_warehouse"),
			("Stock Entry Detail", "t_warehouse"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": None,
		"antecedent_kind": "group",
		"unit_doctype": "Stock Entries",
		"vars_map": {"purpose": "antecedent", "route": "consequent"},
	},
	{
		"id": "acct-mode-of-payment",
		"version": 1,
		"domain": "accounts",
		"role_priors": _ACCOUNTS_ROLES,
		"doctype": "Payment Entry",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S1",
		"sql": "accounts.MODE_OF_PAYMENT_SQL",
		"antecedent": "payment_type",
		"consequent": "mode_of_payment",
		"gates": {"n_min": 30, "c_min": 0.85, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "mode-of-payment",
		"field_guards": [
			("Payment Entry", "mode_of_payment"),
			("Payment Entry", "payment_type"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": None,
		"antecedent_kind": "group",
		"unit_doctype": "Payment Entries",
		"vars_map": {"payment_type": "antecedent", "mode": "consequent"},
	},
	{
		"id": "proj-billing-method",
		"version": 1,
		"domain": "projects",
		"role_priors": _PROJECTS_ROLES,
		"doctype": "Project",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 24,
		"sql_shape": "S1",
		"sql": "projects.BILLING_METHOD_SQL",
		"antecedent": "project_type",
		"consequent": "billing_method",
		"gates": {"n_min": 20, "c_min": 0.90, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "billing-method",
		"field_guards": [
			("Project", "project_type"),
			("Timesheet", "parent_project"),
		],
		"requires_app": ["erpnext"],
		"requires_source": None,
		"postprocess": None,
		"antecedent_kind": "group",
		"unit_doctype": "Projects",
		"vars_map": {"project_type": "antecedent", "billing_method": "consequent"},
	},
	# --- config cleanup (A) --------------------------------------------------
	{
		"id": "cfg-naming-series",
		"version": 1,
		"domain": "org",
		"role_priors": _CONFIG_ROLES,
		"doctype": "DocType",
		"unit": "parent",
		"company_scoped": False,
		"window_months": 12,
		"sql_shape": "S1",
		"sql": None,
		"antecedent": "doctype",
		"consequent": "naming_series",
		"gates": {"n_min": 20, "c_min": 0.80, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "naming-series",
		"field_guards": [],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "config.postprocess_naming_series",
		"antecedent_kind": "doctype",
		"unit_doctype": "documents",
	},
	{
		"id": "cfg-default-vs-usage",
		"version": 1,
		"domain": "org",
		"role_priors": _CONFIG_ROLES,
		"doctype": "Sales Invoice",
		"unit": "parent",
		"company_scoped": False,
		"window_months": 12,
		"sql_shape": "S5",
		"sql": None,
		"antecedent": "selling_price_list_default",
		"consequent": "realized_price_list",
		"gates": {"n_min": 30, "c_min": 0.90, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "default-vs-usage",
		"field_guards": [("Sales Invoice", "selling_price_list")],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "config.postprocess_default_vs_usage",
		"antecedent_kind": "org",
		"unit_doctype": "Sales Invoices",
	},
	# --- Phase 2: Access-Log stream detectors (S4, Tier-2) -------------------
	{
		# unit='event': print events are the natural unit of a printing habit
		# (there is no parent grain - the same invoice printed on ten days is
		# ten observations); import/reprint bursts are collapsed with the
		# existing stats.collapse_bursts over creation timestamps before any
		# gate sees a count, so raw log rows never inflate n.
		"id": "sell-customer-print-format",
		"version": 1,
		"domain": "selling",
		"role_priors": _SELLING_ROLES,
		"doctype": "Access Log",
		"unit": "event",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S4",
		"sql": None,  # watermark-chunked stream + snapshot merge live in postprocess
		"antecedent": "customer",
		"consequent": "print_format",
		# tendency_below: >=10 effective events proposes, but below 30 the
		# wording drops to the tendency template (plan section 4.2 phrasing).
		"gates": {"n_min": 10, "c_min": 0.90, "phrasing": "usually", "tendency_below": 30},
		"sensitivity": "B",
		"skill_template": "customer-print-format",
		"field_guards": [
			("Access Log", "method"),
			("Access Log", "page"),
			("Access Log", "reference_document"),
		],
		"requires_app": [],
		# Written ONLY by frappe printview; custom print engines are invisible,
		# so the preflight marks this detector not_applicable on zero Print
		# signal (plan section 3) and the executor treats the source as gated.
		"requires_source": "access_log",
		"postprocess": "selling.postprocess_customer_print_format",
		"antecedent_kind": "party",
		"unit_doctype": "print events",
		"vars_map": {"customer": "antecedent", "print_format": "consequent"},
		"tier": 2,
	},
	# =========================================================================
	# Tier-2 pack (plan sections 4.2 marked rows, 4.4): party-specific B specs
	# first, then A-class aggregates, then org/config - same surfacing-priority
	# order the Tier-1 sections use.
	# =========================================================================
	{
		# The Phase-2 headliner. Antecedents are party SEGMENTS discovered at
		# run time from `tabCustom Field` on Customer/Supplier (Select/Link/Data
		# fieldtypes; e.g. india_compliance's gst_category - never hardcoded),
		# cross-referenced against active Tax Rules (propose only what no rule
		# encodes) and guarded against the geography confound (party state from
		# Address/Dynamic Link; state predicting the template as well as the
		# segment demotes the band). The compiled text always carries the
		# geography warning; sensitivity B keeps it out of batch approve.
		"id": "acct-party-tax-template",
		"version": 1,
		"domain": "accounts",
		"role_priors": _ACCOUNTS_ROLES,
		"doctype": "Sales Invoice",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S1",
		"sql": None,  # custom-field pre-pass builds the per-segment SQL
		"antecedent": "party_segment",
		"consequent": "taxes_and_charges",
		"gates": {"n_min": 30, "c_min": 0.95, "phrasing": "usually"},
		"sensitivity": "B",
		"skill_template": "party-tax-template",
		"field_guards": [
			("Sales Invoice", "taxes_and_charges"),
			("Purchase Invoice", "taxes_and_charges"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "accounts.postprocess_party_tax_template",
		"antecedent_kind": "group",
		"unit_doctype": "invoices",
		"tier": 2,
	},
	{
		"id": "sell-customer-payment-terms",
		"version": 1,
		"domain": "selling",
		"role_priors": _SELLING_ROLES,
		"doctype": "Sales Invoice",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S5",
		"sql": "selling.CUSTOMER_PAYMENT_TERMS_SQL",
		"antecedent": "customer",
		"consequent": "payment_terms_template",
		"gates": {"n_min": 20, "c_min": 0.95, "phrasing": "usually"},
		"sensitivity": "B",
		"skill_template": "customer-payment-terms",
		"field_guards": [
			("Sales Invoice", "payment_terms_template"),
			("Sales Invoice", "customer"),
			("Customer", "payment_terms"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "selling.postprocess_customer_payment_terms",
		"antecedent_kind": "party",
		"consequent_field": "payment_terms_template",
		"unit_doctype": "Sales Invoices",
		"tier": 2,
	},
	{
		"id": "buy-supplier-payment-terms-realized",
		"version": 1,
		"domain": "buying",
		"role_priors": _BUYING_ROLES,
		"doctype": "Purchase Invoice",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S5",
		"sql": "buying.SUPPLIER_PAYMENT_TERMS_SQL",
		"antecedent": "supplier",
		"consequent": "payment_terms_template",
		"gates": {"n_min": 20, "c_min": 0.95, "phrasing": "usually"},
		"sensitivity": "B",
		"skill_template": "supplier-payment-terms",
		"field_guards": [
			("Purchase Invoice", "payment_terms_template"),
			("Purchase Invoice", "supplier"),
			("Supplier", "payment_terms"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "buying.postprocess_supplier_payment_terms",
		"antecedent_kind": "party",
		"consequent_field": "payment_terms_template",
		"unit_doctype": "Purchase Invoices",
		"tier": 2,
	},
	# --- Tier-2 A-class aggregates -------------------------------------------
	{
		# Multi-plant variant of stock-itemgroup-warehouse: runs ONLY for
		# companies with more than single_plant_max_warehouses shipping
		# warehouses (the mirror-inverse of the Tier-1 single-plant guard, so
		# iter_work_units never double-runs both variants for one company).
		"id": "stock-itemgroup-warehouse-dimensioned",
		"version": 1,
		"domain": "stock",
		"role_priors": _STOCK_ROLES,
		"doctype": "Sales Invoice",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S1",
		"sql": "stock.ITEMGROUP_WAREHOUSE_DIMENSIONED_SQL",
		"antecedent": "item_group :: cost_center",
		"consequent": "warehouse",
		"gates": {"n_min": 30, "c_min": 0.90, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "itemgroup-warehouse-dimensioned",
		"field_guards": [
			("Sales Invoice Item", "item_group"),
			("Sales Invoice Item", "warehouse"),
			("Sales Invoice Item", "cost_center"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "stock.postprocess_itemgroup_warehouse_dimensioned",
		"antecedent_kind": "group",
		"unit_doctype": "Sales Invoices",
		"single_plant_max_warehouses": 3,
		"tier": 2,
	},
	{
		"id": "stock-uom-conversion",
		"version": 1,
		"domain": "stock",
		"role_priors": _STOCK_ROLES,
		"doctype": "Sales Invoice",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S2",
		"sql": "stock.UOM_CONVERSION_SQL",
		"antecedent": "item_group",
		"consequent": "uom",
		"gates": {"n_min": 30, "c_min": 0.85, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "uom-conversion",
		"field_guards": [
			("Sales Invoice Item", "uom"),
			("Sales Invoice Item", "item_group"),
			("Item", "stock_uom"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": None,
		"antecedent_kind": "group",
		"unit_doctype": "Sales Invoices",
		# a group transacting in its stock UOM is the vanilla default
		"org_default_consequent": "__stock_uom__",
		"vars_map": {"item_group": "antecedent", "uom": "consequent"},
		"tier": 2,
	},
	{
		# Item is an org-wide master (no company column), so this spec is
		# org-scoped; realized batch/serial fill rates from the stock ledger
		# ride along as evidence in the postprocess.
		"id": "stock-batch-serial-usage",
		"version": 1,
		"domain": "stock",
		"role_priors": _STOCK_ROLES,
		"doctype": "Item",
		"unit": "parent",
		"company_scoped": False,
		"window_months": 18,
		"sql_shape": "S2",
		"sql": "stock.BATCH_SERIAL_USAGE_SQL",
		"antecedent": "item_group",
		"consequent": "tracking",
		"gates": {"n_min": 20, "c_min": 0.90, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "batch-serial-usage",
		"field_guards": [
			("Item", "has_batch_no"),
			("Item", "has_serial_no"),
			("Item", "item_group"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "stock.postprocess_batch_serial_usage",
		"antecedent_kind": "group",
		"unit_doctype": "items",
		"target_consequents": [
			"batch-tracked",
			"serial-tracked",
			"batch-and-serial-tracked",
		],
		"tier": 2,
	},
	{
		"id": "acct-cost-center-dimension",
		"version": 1,
		"domain": "accounts",
		"role_priors": _ACCOUNTS_ROLES,
		"doctype": "Sales Invoice",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S1",
		"sql": "accounts.COST_CENTER_DIMENSION_SQL",
		"antecedent": "warehouse",
		"consequent": "cost_center",
		"gates": {"n_min": 30, "c_min": 0.90, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "cost-center-dimension",
		"field_guards": [
			("Sales Invoice Item", "cost_center"),
			("Sales Invoice Item", "warehouse"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": None,
		"antecedent_kind": "group",
		"consequent_field": "cost_center",
		"unit_doctype": "Sales Invoices",
		"vars_map": {"warehouse": "antecedent", "cost_center": "consequent"},
		"tier": 2,
	},
	{
		# Two candidate kinds from one scan (plan section 4.2 "JE voucher-type/
		# template habits"): the generic reduce yields per-voucher-type template
		# habits (org_default __manual__ keeps template-free types silent); the
		# postprocess adds the org-level voucher-type habit.
		"id": "acct-je-usage",
		"version": 1,
		"domain": "accounts",
		"role_priors": _ACCOUNTS_ROLES,
		"doctype": "Journal Entry",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S1",
		"sql": "accounts.JE_USAGE_SQL",
		"antecedent": "voucher_type",
		"consequent": "from_template",
		"gates": {"n_min": 30, "c_min": 0.80, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "je-from-template",
		"field_guards": [
			("Journal Entry", "voucher_type"),
			("Journal Entry", "from_template"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "accounts.postprocess_je_usage",
		"antecedent_kind": "group",
		"unit_doctype": "Journal Entries",
		"org_default_consequent": "__manual__",
		"vars_map": {"voucher_type": "antecedent", "je_template": "consequent"},
		"tier": 2,
	},
	{
		"id": "acct-deferred-usage",
		"version": 1,
		"domain": "accounts",
		"role_priors": _ACCOUNTS_ROLES,
		"doctype": "Sales Invoice",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S2",
		"sql": None,  # revenue (SI) and expense (PI) passes run in postprocess
		"antecedent": "item_group :: kind",
		"consequent": "deferred",
		"gates": {"n_min": 20, "c_min": 0.90, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "deferred-usage",
		"field_guards": [
			("Sales Invoice Item", "enable_deferred_revenue"),
			("Purchase Invoice Item", "enable_deferred_expense"),
			("Sales Invoice Item", "item_group"),
		],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "accounts.postprocess_deferred_usage",
		"antecedent_kind": "group",
		"unit_doctype": "invoices",
		"target_consequents": ["deferred"],
		"tier": 2,
	},
	{
		"id": "mfg-default-bom-usage",
		"version": 1,
		# compiles into learned-stock: manufacturing has no dedicated domain
		# skill in the <=6-row consolidation (plan section 6.2)
		"domain": "stock",
		"role_priors": _MFG_ROLES,
		"doctype": "Work Order",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 12,
		"sql_shape": "S5",
		"sql": "stock.DEFAULT_BOM_USAGE_SQL",
		"antecedent": "production_item",
		"consequent": "bom_no",
		"gates": {"n_min": 20, "c_min": 0.90, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "default-bom-usage",
		"field_guards": [
			("Work Order", "bom_no"),
			("Work Order", "production_item"),
			("BOM", "is_default"),
			("BOM", "item"),
		],
		"requires_app": ["erpnext"],
		"requires_source": None,
		"postprocess": "stock.postprocess_default_bom_usage",
		"antecedent_kind": "group",
		"consequent_field": "bom_no",
		"unit_doctype": "Work Orders",
		"tier": 2,
	},
	{
		"id": "proj-timesheet-rate-defaults",
		"version": 1,
		"domain": "projects",
		"role_priors": _PROJECTS_ROLES,
		"doctype": "Timesheet",
		"unit": "parent",
		"company_scoped": True,
		"window_months": 18,
		"sql_shape": "S1",
		"sql": "projects.TIMESHEET_RATE_SQL",
		"antecedent": "activity_type",
		"consequent": "billing_rate",
		"gates": {"n_min": 30, "c_min": 0.85, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "timesheet-rate-defaults",
		"field_guards": [
			("Timesheet Detail", "activity_type"),
			("Timesheet Detail", "billing_rate"),
			("Timesheet Detail", "is_billable"),
		],
		"requires_app": ["erpnext"],
		"requires_source": None,
		"postprocess": "projects.postprocess_timesheet_rate_defaults",
		"antecedent_kind": "group",
		"unit_doctype": "Timesheets",
		"tier": 2,
	},
	# --- Tier-2 org/config ----------------------------------------------------
	{
		# Discovered fieldnames are regex + meta validated before any SQL
		# interpolation (static-SQL guarantee; see config._validated_identifiers).
		"id": "cfg-custom-field-always-filled",
		"version": 1,
		"domain": "org",
		"role_priors": _CONFIG_ROLES,
		"doctype": "Custom Field",
		"unit": "parent",
		"company_scoped": False,
		"window_months": 12,
		"sql_shape": "S2",
		"sql": None,
		"antecedent": "custom_field",
		"consequent": "filled",
		"gates": {"n_min": 60, "c_min": 0.98, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "custom-field-always-filled",
		"field_guards": [("Custom Field", "fieldname")],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "config.postprocess_custom_field_always_filled",
		"antecedent_kind": "org",
		"unit_doctype": "submitted documents",
		"tier": 2,
	},
	{
		# Org/role level ONLY: owner JOIN `tabHas Role` with fractional
		# multi-role weights; user names never reach the candidate.
		"id": "role-doctype-routing",
		"version": 1,
		"domain": "org",
		"role_priors": _CONFIG_ROLES,
		"doctype": "DocType",
		"unit": "parent",
		"company_scoped": False,
		"window_months": 12,
		"sql_shape": "S1",
		"sql": None,
		"antecedent": "doctype",
		"consequent": "role",
		"gates": {"n_min": 30, "c_min": 0.80, "phrasing": "usually"},
		"sensitivity": "A",
		"skill_template": "role-doctype-routing",
		"field_guards": [("Has Role", "role")],
		"requires_app": [],
		"requires_source": None,
		"postprocess": "config.postprocess_role_doctype_routing",
		"antecedent_kind": "doctype",
		"unit_doctype": "documents",
		"tier": 2,
	},
]

# Tier views (plan section 4.4). ALL_DETECTORS is the canonical "everything
# registered" list new consumers should read.
ALL_DETECTORS: list[dict] = list(DETECTORS)
TIER2_DETECTORS: list[dict] = [s for s in DETECTORS if int(s.get("tier", 1)) == 2]

# Historical name; engine rehydration and bootstrap seeding read this as "all
# registered detectors" (it predates tiering), so it stays an alias of
# ALL_DETECTORS - Tier-2 specs are seeded and rehydrated with zero bootstrap /
# engine changes. Cleanup one-liner for a later wave: point bootstrap.py
# (_tier1_specs) and engine.py (_rehydrate_units) at ALL_DETECTORS, then this
# alias can become the true tier==1 subset.
TIER1_DETECTORS: list[dict] = ALL_DETECTORS

_BY_ID = {spec["id"]: spec for spec in DETECTORS}


def get_detector(detector_id: str) -> dict | None:
	return _BY_ID.get(detector_id)


def all_detector_ids() -> list[str]:
	return [spec["id"] for spec in DETECTORS]


def is_detector_enabled(detector_id: str) -> bool:
	"""A detector runs unless its Jarvis Pattern Detector State row says
	otherwise. A missing row (never seeded) reads as enabled - the engine
	seeds best-effort and must not go dark on a seeding miss."""
	import frappe

	try:
		val = frappe.db.get_value("Jarvis Pattern Detector State", detector_id, "enabled")
	except Exception:
		return True
	if val is None:
		return True
	return bool(val)


def enabled_specs() -> list[dict]:
	return [spec for spec in DETECTORS if is_detector_enabled(spec["id"])]


def iter_work_units(companies, specs: list[dict] | None = None):
	"""Ordered [(company, spec), ...] work units for a run (plan section 5.3).

	Detector-major (registry priority order), companies inner: a company-scoped
	detector expands to one unit per company; an org-wide detector
	(company_scoped=False - config/masters and org existence detectors) yields a
	single (None, spec) unit. The engine skips dormant companies upstream.
	"""
	specs = enabled_specs() if specs is None else specs
	companies = list(companies or [])
	for spec in specs:
		if spec.get("company_scoped"):
			for company in companies:
				yield (company, spec)
		else:
			yield (None, spec)
