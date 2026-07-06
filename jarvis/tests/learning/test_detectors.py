"""Tier-1 detector tests (plan section 11): each detector finds its planted
pattern at the right band and is SILENT on its trap.

Company-scoped detectors run against the seeded mini-org (isolated by the
company filter, so production data under other companies never leaks in).
Org-wide detectors (cfg-naming-series, cfg-default-vs-usage) are exercised with
a fake facade so their divergence logic is asserted deterministically without
depending on whatever else lives on the site.

Detectors run WITHOUT the READ ONLY fence here (a plain PatternDB in the test's
own transaction). The fence itself is covered by test_readonly_db and by the
engine's table-diff integration test (Wave B engine).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.learning import registry
from jarvis.learning.detectors import config as config_detectors
from jarvis.learning.executor import (
	_enforcement_conflict,
	_finalize,
	_state_predicts_template,
	reduce_units,
	run_detector,
)
from jarvis.learning.readonly_db import PatternDB
from jarvis.tests.learning import factory


def _po_rows(supplier, consequent, start_date, count, step_days=1, created_day=None):
	"""Synthetic unit-grain rows for reduce_units: one row per unit, distinct
	posting days; ``created_day`` (a single date) forces a one-session import
	burst, else creation days track posting days (organic)."""
	rows = []
	for i in range(count):
		day = frappe.utils.add_days(start_date, i * step_days)
		if created_day is not None:
			# multi-minute import cluster on one creation day (30s apart)
			created = f"{created_day} 03:{(i * 30) // 60:02d}:{(i * 30) % 60:02d}"
		else:
			created = f"{day} 10:00:00"
		rows.append({
			"unit_id": f"{supplier}-{consequent}-{i}",
			"antecedent": supplier,
			"consequent": consequent,
			"company": factory.ALPHA,
			"day": day,
			"created": created,
		})
	return rows


def _find(candidates, **kv):
	for c in candidates:
		if all(c.get(k) == v for k, v in kv.items()):
			return c
	return None


class TestTier1Detectors(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		factory.build(commit=True)

	@classmethod
	def tearDownClass(cls):
		factory.wipe(commit=True)
		super().tearDownClass()

	def _run(self, detector_id, company):
		return run_detector(registry.get_detector(detector_id), company, PatternDB())

	# --- selling ------------------------------------------------------------
	def test_customer_price_list_finds_dealer_and_silent_on_sole_value(self):
		res = self._run("sell-customer-price-list", factory.ALPHA)
		self.assertIsNone(res.skipped_reason)
		cand = _find(res.candidates, antecedent_value="_JPL-DealerD")
		self.assertIsNotNone(cand, "DealerD price-list pattern not found")
		self.assertEqual(cand["consequent_value"], "Dealer Pricing")
		self.assertIn(cand["strength_band"], ("High", "Medium"))
		self.assertEqual(cand["effective_sensitivity"], "B")  # party -> escalated
		self.assertGreaterEqual(cand["support_n"], 20)

		# sole-value trap: company Beta uses one price list -> variance suppressed
		beta = self._run("sell-customer-price-list", factory.BETA)
		self.assertIsNone(beta.skipped_reason)
		self.assertEqual(beta.candidates, [])

	def test_group_payment_terms_finds_dealer_with_exceptions(self):
		res = self._run("sell-group-payment-terms", factory.ALPHA)
		cand = _find(res.candidates, antecedent_value="Dealer")
		self.assertIsNotNone(cand)
		self.assertEqual(cand["consequent_value"], "30 Days")
		self.assertEqual(cand["exception_n"], 2)
		self.assertEqual(cand["sensitivity"], "A")
		# single-term company Beta -> variance suppressed
		self.assertEqual(self._run("sell-group-payment-terms", factory.BETA).candidates, [])

	def test_quotation_validity_diverges_and_silent_on_vanilla(self):
		res = self._run("sell-quotation-validity", factory.ALPHA)
		cand = _find(res.candidates, antecedent_value="org")
		self.assertIsNotNone(cand)
		self.assertIn("15", cand["pattern_statement"])
		# vanilla +1-month default in Beta -> suppressed
		self.assertEqual(self._run("sell-quotation-validity", factory.BETA).candidates, [])

	def test_tc_letterhead_diverges_from_company_default(self):
		res = self._run("sell-tc-letterhead", factory.ALPHA)
		cand = _find(res.candidates, consequent_value=factory.LETTER_HEAD)
		self.assertIsNotNone(cand)
		self.assertEqual(cand["sensitivity"], "A")

	def test_selective_item_pricing_existence(self):
		res = self._run("sell-selective-item-pricing", None)
		cand = _find(res.candidates, antecedent_value="org")
		self.assertIsNotNone(cand)
		self.assertGreaterEqual(cand["support_n"], factory.EXPECT["selective_customers"])
		self.assertEqual(cand["effective_sensitivity"], "B")

	# --- buying -------------------------------------------------------------
	def test_supplier_stockness_finds_acme(self):
		res = self._run("buy-supplier-stockness", factory.ALPHA)
		cand = _find(res.candidates, antecedent_value="_JPL-AcmeNonStock")
		self.assertIsNotNone(cand)
		self.assertEqual(cand["consequent_value"], "non_stock")
		self.assertEqual(cand["support_n"], 40)
		self.assertEqual(cand["strength_band"], "High")
		# a stock supplier is not proposed (target_consequents restricts to non_stock)
		self.assertIsNone(_find(res.candidates, antecedent_value="_JPL-BoltSupply"))
		# wording matches the gate: 40u tendency band must NOT over-claim "only"
		# (fix 3), and the "usually" gate never fires the enforcement cross-ref.
		self.assertIn("usually", cand["pattern_statement"])
		self.assertNotIn("only", cand["pattern_statement"])
		self.assertIsNone(cand["enforcement_conflict"])

	def test_supplier_itemgroup_finds_bolt_and_gates_child_row_inflation(self):
		res = self._run("buy-supplier-itemgroup", factory.ALPHA)
		bolt = _find(res.candidates, antecedent_value="_JPL-BoltSupply")
		self.assertIsNotNone(bolt)
		self.assertEqual(bolt["consequent_value"], "Fasteners")
		# child-row inflation trap: 6 POs x 10 lines -> 6 units < n_min -> silent
		self.assertIsNone(_find(res.candidates, antecedent_value="_JPL-InflateCo"))

	def test_supplier_tax_template_finds_taxhabit_with_one_exception(self):
		res = self._run("buy-supplier-tax-template", factory.ALPHA)
		cand = _find(res.candidates, antecedent_value="_JPL-TaxHabit")
		self.assertIsNotNone(cand)
		self.assertEqual(cand["consequent_value"], "Alpha GST 18%")
		self.assertEqual(cand["exception_n"], 1)
		# geography-confound caveat is always attached (fix 5): a tax template by
		# supplier can encode state-driven GST, not a per-supplier habit.
		self.assertIn("geography_caveat", cand["evidence"])
		self.assertIn("geography", cand["pattern_statement"].lower())

	def test_pi_update_stock_finds_habit_and_silent_on_burst(self):
		res = self._run("buy-pi-update-stock", factory.ALPHA)
		cand = _find(res.candidates, antecedent_value="org")
		self.assertIsNotNone(cand)
		self.assertEqual(cand["consequent_value"], "1")
		self.assertEqual(cand["sensitivity"], "B")  # process control
		# go-live burst trap in Beta (one day, one second) -> spread gate silent
		self.assertEqual(self._run("buy-pi-update-stock", factory.BETA).candidates, [])

	# --- stock --------------------------------------------------------------
	def test_itemgroup_warehouse_single_plant_and_multiplant_skip(self):
		res = self._run("stock-itemgroup-warehouse", factory.ALPHA)
		self.assertIsNone(res.skipped_reason)
		self.assertIsNotNone(_find(res.candidates, antecedent_value="Electronics"))
		self.assertIsNotNone(_find(res.candidates, antecedent_value="Furniture"))
		# multi-plant trap in Beta (5 warehouses) -> skipped with coverage note
		beta = self._run("stock-itemgroup-warehouse", factory.BETA)
		self.assertIsNotNone(beta.skipped_reason)
		self.assertIn("multi-plant", beta.skipped_reason)

	def test_stock_entry_purpose_mix(self):
		res = self._run("stock-entry-purpose-mix", factory.ALPHA)
		self.assertIsNotNone(_find(res.candidates, antecedent_value="Material Transfer"))
		self.assertIsNotNone(_find(res.candidates, antecedent_value="Material Receipt"))

	# --- accounts -----------------------------------------------------------
	def test_mode_of_payment(self):
		res = self._run("acct-mode-of-payment", factory.ALPHA)
		recv = _find(res.candidates, antecedent_value="Receive")
		pay = _find(res.candidates, antecedent_value="Pay")
		self.assertIsNotNone(recv)
		self.assertEqual(recv["consequent_value"], "Bank Draft")
		self.assertIsNotNone(pay)
		self.assertEqual(pay["consequent_value"], "Cash")

	# --- projects -----------------------------------------------------------
	def test_billing_method(self):
		res = self._run("proj-billing-method", factory.ALPHA)
		cand = _find(res.candidates, antecedent_value="External")
		self.assertIsNotNone(cand)
		self.assertIn("timesheet", cand["consequent_value"])

	# --- candidate contract sanity -----------------------------------------
	def test_candidate_contract_shape(self):
		res = self._run("sell-group-payment-terms", factory.ALPHA)
		cand = _find(res.candidates, antecedent_value="Dealer")
		required = {
			"detector_id", "detector_version", "registry_version", "domain",
			"company", "pattern_key", "roles", "pattern_statement", "skill_draft",
			"support_n", "n_rows", "exception_n", "confidence_pct", "wilson_low",
			"gap", "strength_band", "temporal_spread", "evidence", "exceptions",
			"exceptions_cluster", "sensitivity", "effective_sensitivity",
			"not_applicable",
		}
		self.assertTrue(required.issubset(set(cand)), required - set(cand))
		self.assertEqual(len(cand["pattern_key"]), 40)
		self.assertEqual(cand["detector_id"], "sell-group-payment-terms")
		self.assertIsInstance(cand["roles"], list)
		self.assertIsInstance(cand["evidence"], dict)
		self.assertTrue(cand["skill_draft"].startswith("- "))
		self.assertIn("Evidence:", cand["skill_draft"])


# ---------------------------------------------------------------------------
# org-wide config detectors: deterministic fake-facade tests
# ---------------------------------------------------------------------------
class _FakePatternDB:
	"""Maps a SQL substring to a canned result list; everything else is []."""

	def __init__(self, mapping):
		self._mapping = mapping

	def _rows(self, query):
		for needle, rows in self._mapping:
			if needle in query:
				return rows
		return []

	def timed_select(self, query, params=None, **kwargs):
		return self._rows(query)

	def sql_select(self, query, params=None, **kwargs):
		return self._rows(query)


def _usage_rows(consequent, n, start=0):
	import frappe

	rows = []
	for i in range(n):
		day = frappe.utils.add_days("2025-09-01", start + i)  # distinct calendar days
		rows.append({
			"unit_id": f"row-{start + i}",
			"consequent": consequent,
			"day": day,
			"created": f"{day} 10:00:00",
		})
	return rows


class TestConfigDetectorsFake(FrappeTestCase):
	def test_default_vs_usage_proposes_on_divergence(self):
		spec = registry.get_detector("cfg-default-vs-usage")
		# configured default = Standard Selling; realized usage = Custom PL
		db = _FakePatternDB([
			("tabSingles", [{"value": "Standard Selling"}]),
			("tabSales Invoice", _usage_rows("Custom PL", 40)),
		])
		out = config_detectors.postprocess_default_vs_usage(None, spec, None, db, {"window_start": "2025-01-01"})
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["consequent_value"], "Custom PL")
		self.assertEqual(out[0]["evidence"]["configured_default"], "Standard Selling")

	def test_default_vs_usage_silent_when_usage_matches_default(self):
		spec = registry.get_detector("cfg-default-vs-usage")
		db = _FakePatternDB([
			("tabSingles", [{"value": "Standard Selling"}]),
			("tabSales Invoice", _usage_rows("Standard Selling", 40)),
		])
		out = config_detectors.postprocess_default_vs_usage(None, spec, None, db, {"window_start": "2025-01-01"})
		self.assertEqual(out, [])

	def test_naming_series_merges_and_proposes(self):
		spec = registry.get_detector("cfg-naming-series")
		db = _FakePatternDB([
			("naming_series` AS consequent", _usage_rows("SINV-.####", 30)),
			("tabProperty Setter", []),
			("tabSeries", [{"series": "SINV-", "current": 42}]),
		])
		out = config_detectors.postprocess_naming_series(None, spec, None, db, {"window_start": "2025-01-01"})
		self.assertGreaterEqual(len(out), 1)
		first = out[0]
		self.assertEqual(first["consequent_value"], "SINV-.####")
		self.assertEqual(first["evidence"]["sql_shape"], "S1")


class TestEnforcementCrossRef(FrappeTestCase):
	def test_no_conflict_returns_none(self):
		self.assertIsNone(_enforcement_conflict("Purchase Invoice", "update_stock", PatternDB()))

	def test_active_server_script_badges(self):
		name = "_JPL-ES-updatestock"
		try:
			import frappe

			frappe.db.delete("Server Script", {"name": name})
			doc = frappe.new_doc("Server Script")
			doc.update({
				"script_type": "DocType Event",
				"reference_doctype": "Purchase Invoice",
				"doctype_event": "Before Save",
				"disabled": 0,
				"script": "if doc.update_stock: pass",
			})
			doc.name = name
			doc.flags.name_set = True
			doc.db_insert()
		except Exception as exc:  # environment without Server Script table shape
			self.skipTest(f"could not seed Server Script: {exc}")
		try:
			badge = _enforcement_conflict("Purchase Invoice", "update_stock", PatternDB())
			self.assertIsNotNone(badge)
			self.assertIn("Server Script", badge)
		finally:
			frappe.db.delete("Server Script", {"name": name})


# ---------------------------------------------------------------------------
# fix 1: recency guard (reduce_units, no fixtures needed)
# ---------------------------------------------------------------------------
class TestRecencyGuard(FrappeTestCase):
	"""A segment whose modal value flipped inside the last-90-day window must
	propose the RECENT behaviour (annotated) or withhold - never the stale
	full-window average."""

	def _reduce(self, rows):
		spec = registry.get_detector("buy-supplier-tax-template")
		return reduce_units(rows, spec, PatternDB())

	def test_flip_retargets_to_recent_and_annotates(self):
		rows = []
		# SupFlip: OldGST for 40 old POs, then NewGST for 25 recent POs -> flip.
		rows += _po_rows("SupFlip", "OldGST", "2025-01-01", 40, step_days=3)
		rows += _po_rows("SupFlip", "NewGST", "2025-09-01", 25)
		# SupFlip2: same flip but only 10 recent POs -> cannot stand alone.
		rows += _po_rows("SupFlip2", "OldGST", "2025-01-02", 40, step_days=3)
		rows += _po_rows("SupFlip2", "NewGST", "2025-08-20", 10)
		# SupSame: consistent, recent-only -> normal candidate, no recency note.
		rows += _po_rows("SupSame", "SameGST", "2025-07-01", 40)
		# SupB: variance ballast + a recent base rate.
		rows += _po_rows("SupB", "ConstGST", "2025-06-27", 40)
		cands = self._reduce(rows)

		flip = _find(cands, antecedent_value="SupFlip")
		self.assertIsNotNone(flip, "flipped supplier must still propose the RECENT habit")
		self.assertEqual(flip["consequent_value"], "NewGST")
		self.assertEqual(flip["n_units"], 25)  # recent subset only, not 65
		self.assertIn("recency", flip["evidence"])
		self.assertIn("behavior changed around", flip["evidence"]["recency"])

		# flip with too little recent evidence -> withheld entirely (not stale Old)
		self.assertIsNone(_find(cands, antecedent_value="SupFlip2"))

		same = _find(cands, antecedent_value="SupSame")
		self.assertIsNotNone(same)
		self.assertNotIn("recency", same["evidence"])


# ---------------------------------------------------------------------------
# fix 4: burst gate strengthened (multi-minute imports collapse)
# ---------------------------------------------------------------------------
class TestBurstGate(FrappeTestCase):
	def test_multi_minute_import_burst_is_collapsed(self):
		spec = registry.get_detector("buy-supplier-tax-template")
		rows = []
		# Organic: 25 POs, distinct posting AND creation days.
		rows += _po_rows("OrganicSup", "T-Org", "2025-09-01", 25)
		# Control: 30 organic POs -> proves the gate does not reject volume alone.
		rows += _po_rows("ControlSup", "T-Ctrl", "2025-07-01", 30)
		# Import: 30 POs across 30 distinct POSTING days but ONE creation session
		# (30s apart) -> must collapse, satisfying neither n_min nor creation-day
		# spread even though posting spread passes.
		rows += _po_rows("ImportSup", "T-Imp", "2025-08-01", 30, created_day="2025-10-01")
		cands = reduce_units(rows, spec, PatternDB())

		self.assertIsNotNone(_find(cands, antecedent_value="OrganicSup"))
		self.assertIsNotNone(_find(cands, antecedent_value="ControlSup"))
		self.assertIsNone(
			_find(cands, antecedent_value="ImportSup"),
			"a one-session import backfilling many posting dates must be collapsed",
		)


# ---------------------------------------------------------------------------
# fix 2: enforcement cross-ref fires for an "only"-band candidate
# ---------------------------------------------------------------------------
class TestEnforcementFires(FrappeTestCase):
	SCRIPT = "_JPL-ES-po-stockness"

	def setUp(self):
		frappe.db.delete("Server Script", {"name": self.SCRIPT})
		try:
			doc = frappe.new_doc("Server Script")
			doc.update({
				"script_type": "DocType Event",
				"reference_doctype": "Purchase Order",
				"doctype_event": "Before Save",
				"disabled": 0,
				"script": "if doc.get('items'): pass  # touches is_stock_item",
			})
			doc.name = self.SCRIPT
			doc.flags.name_set = True
			doc.db_insert()
		except Exception as exc:
			self.skipTest(f"could not seed Server Script: {exc}")

	def tearDown(self):
		frappe.db.delete("Server Script", {"name": self.SCRIPT})

	def test_only_band_fires_cross_ref_but_tendency_does_not(self):
		spec = registry.get_detector("buy-supplier-stockness")

		# 65 non-stock POs, 0 exceptions -> "only" (rule-of-three) band -> fires.
		rows = _po_rows("SupOnly", "non_stock", "2025-05-01", 65)
		rows += _po_rows("SupStock", "has_stock", "2025-05-01", 10)  # variance ballast
		cands = reduce_units(rows, spec, PatternDB())
		only = _find(cands, antecedent_value="SupOnly")
		self.assertIsNotNone(only)
		self.assertEqual(only["n_units"], 65)
		self.assertIsNotNone(only["enforcement_conflict"], "60u/0-exc claim must cross-ref")
		self.assertIn("Server Script", only["enforcement_conflict"])
		self.assertIn("enforcement_conflict", only["evidence"])

		# 40 non-stock POs -> tendency band (<60) -> cross-ref must NOT fire even
		# with the same active Server Script present.
		rows2 = _po_rows("Sup40", "non_stock", "2025-05-01", 40)
		rows2 += _po_rows("SupStockBig", "has_stock", "2025-05-01", 30)
		cands2 = reduce_units(rows2, spec, PatternDB())
		tend = _find(cands2, antecedent_value="Sup40")
		self.assertIsNotNone(tend)
		self.assertIsNone(tend["enforcement_conflict"])


# ---------------------------------------------------------------------------
# fix 3: strict "only" wording only when the evidence earns it
# ---------------------------------------------------------------------------
class TestStocknessStrictWording(FrappeTestCase):
	def test_strict_only_wording_at_rule_of_three_band(self):
		spec = registry.get_detector("buy-supplier-stockness")
		rows = _po_rows("SupOnly", "non_stock", "2025-05-01", 65)
		rows += _po_rows("SupStock", "has_stock", "2025-05-01", 10)
		raws = reduce_units(rows, spec, PatternDB())
		raw = _find(raws, antecedent_value="SupOnly")
		self.assertIsNotNone(raw)
		cand = _finalize(spec, factory.ALPHA, raw)
		self.assertIn("supplies only non-stock", cand["pattern_statement"])
		self.assertIn("only non-stock", cand["skill_draft"])


# ---------------------------------------------------------------------------
# fix 5: geography-confound helper
# ---------------------------------------------------------------------------
class TestGeographyConfound(FrappeTestCase):
	def test_state_predicts_template_true(self):
		states = {"p1": "MH", "p2": "MH", "p3": "KA", "p4": "KA"}
		templates = {"p1": "GST18", "p2": "GST18", "p3": "GST12", "p4": "GST12"}
		self.assertTrue(_state_predicts_template(states, templates))

	def test_state_does_not_predict_template(self):
		states = {"p1": "MH", "p2": "MH", "p3": "KA", "p4": "KA"}
		templates = {"p1": "GST18", "p2": "GST12", "p3": "GST18", "p4": "GST12"}
		self.assertFalse(_state_predicts_template(states, templates))

	def test_single_state_is_not_a_confound(self):
		self.assertFalse(_state_predicts_template({"p1": "MH", "p2": "MH"}, {"p1": "G", "p2": "G"}))

	def test_empty_is_not_a_confound(self):
		self.assertFalse(_state_predicts_template({}, {}))


# ---------------------------------------------------------------------------
# fix 6: run_detector reports an approximate scanned-row count
# ---------------------------------------------------------------------------
class _RowsDB:
	"""Facade stub: timed_select returns a fixed row list; sql_select empty."""

	def __init__(self, rows):
		self._rows = rows

	def timed_select(self, query, params=None, **kwargs):
		return list(self._rows)

	def sql_select(self, query, params=None, **kwargs):
		return []


class TestScannedRows(FrappeTestCase):
	def test_run_detector_charges_materialized_rows(self):
		spec = registry.get_detector("acct-mode-of-payment")
		rows = [
			{"unit_id": f"pe{i}", "antecedent": "Receive", "consequent": "Cash",
			 "day": frappe.utils.add_days("2025-09-01", i), "created": "2025-09-01 10:00:00"}
			for i in range(7)
		]
		res = run_detector(spec, factory.ALPHA, _RowsDB(rows))
		self.assertEqual(res.rows_scanned, 7)
