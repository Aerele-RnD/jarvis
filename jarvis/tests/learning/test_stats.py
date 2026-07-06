"""Pure-function tests for the pattern-learning statistical gates.

Reference Wilson values were computed independently from the closed-form
Wilson score interval (z=1.96) and hardcoded here, so a regression in
stats.py cannot silently re-derive its own expectations.
"""

import datetime

from frappe.tests.utils import FrappeTestCase

from jarvis.learning.stats import (
	band,
	cluster_exceptions,
	collapse_bursts,
	leave_segment_out_base_rate,
	precision_ok,
	recency_divergence,
	rule_of_three_note,
	spread_ok,
	variance_gate,
	wilson_half_width,
	wilson_lower_bound,
)


class TestWilson(FrappeTestCase):
	def test_known_value_8_of_10(self):
		# Textbook check: p=0.8, n=10 -> lower bound 0.4902.
		self.assertAlmostEqual(wilson_lower_bound(8, 10), 0.49016, places=4)

	def test_known_value_perfect_71(self):
		# The plan's "all 71 Purchase Orders" example: k=n=71 -> 0.9487 (High).
		self.assertAlmostEqual(wilson_lower_bound(71, 71), 0.94867, places=4)

	def test_known_value_205_of_214(self):
		# The plan's "96% of 214 invoices" example -> 0.9220 (High).
		self.assertAlmostEqual(wilson_lower_bound(205, 214), 0.92202, places=4)

	def test_zero_n_and_zero_k(self):
		self.assertEqual(wilson_lower_bound(0, 0), 0.0)
		self.assertEqual(wilson_lower_bound(5, 0), 0.0)
		self.assertEqual(wilson_lower_bound(0, 50), 0.0)

	def test_small_perfect_sample_stays_below_large_one(self):
		# 5/5 must never read as strong as 205/214 - the whole point of
		# banding on the lower bound instead of raw k/n.
		self.assertLess(wilson_lower_bound(5, 5), wilson_lower_bound(205, 214))

	def test_k_clamped_to_n(self):
		self.assertEqual(wilson_lower_bound(15, 10), wilson_lower_bound(10, 10))
		self.assertEqual(wilson_lower_bound(-3, 10), wilson_lower_bound(0, 10))

	def test_half_width_known_values(self):
		self.assertAlmostEqual(wilson_half_width(9, 10), 0.19314, places=4)
		self.assertAlmostEqual(wilson_half_width(28, 30), 0.09738, places=4)
		self.assertEqual(wilson_half_width(1, 0), 1.0)


class TestBanding(FrappeTestCase):
	def test_boundaries(self):
		self.assertEqual(band(0.90), "High")
		self.assertEqual(band(0.95), "High")
		self.assertEqual(band(0.8999), "Medium")
		self.assertEqual(band(0.80), "Medium")
		self.assertEqual(band(0.7999), "Low")
		self.assertEqual(band(0.0), "Low")

	def test_perfect_30_is_medium_perfect_36_is_high(self):
		# k=n=30 -> wilson_low 0.8865 (Medium); k=n=36 -> 0.9036 (High).
		# A perfect record needs ~36 units before it may claim High.
		self.assertEqual(band(wilson_lower_bound(30, 30)), "Medium")
		self.assertEqual(band(wilson_lower_bound(36, 36)), "High")


class TestPrecisionGate(FrappeTestCase):
	def test_small_n_fails(self):
		# 9/10: half-width 0.193 > 0.15 -> data_starved.
		self.assertFalse(precision_ok(9, 10))

	def test_adequate_n_passes(self):
		# 28/30: half-width 0.097 <= 0.15.
		self.assertTrue(precision_ok(28, 30))
		# 19/20: half-width 0.114 <= 0.15.
		self.assertTrue(precision_ok(19, 20))

	def test_zero_n_fails(self):
		self.assertFalse(precision_ok(0, 0))


class TestLeaveSegmentOut(FrappeTestCase):
	# Hand-computed example: segment A shows X in 90/100 units; the REST of
	# the site (B+C) shows X in (20+30)/(100+100) = 50/200.
	COUNTS = {
		"A": {"X": 90, "Y": 10},
		"B": {"X": 20, "Y": 80},
		"C": {"X": 30, "Y": 70},
	}

	def test_hand_computed_example(self):
		r = leave_segment_out_base_rate(self.COUNTS, "A")
		self.assertEqual(r["consequent"], "X")
		self.assertEqual(r["k"], 90)
		self.assertEqual(r["n_units"], 100)
		self.assertAlmostEqual(r["confidence"], 0.90)
		self.assertAlmostEqual(r["base_rate"], 0.25)
		self.assertAlmostEqual(r["gap"], 0.65)

	def test_explicit_consequent(self):
		r = leave_segment_out_base_rate(self.COUNTS, "B", consequent="Y")
		self.assertAlmostEqual(r["confidence"], 0.80)
		# Y elsewhere: (10 + 70) / (100 + 100) = 0.40.
		self.assertAlmostEqual(r["base_rate"], 0.40)
		self.assertAlmostEqual(r["gap"], 0.40)

	def test_skewed_marginal_yields_small_gap(self):
		# The scenario naive lift passes trivially: X dominates everywhere,
		# so segment A's 96% is NOT a habit of A - gap must be small.
		counts = {
			"A": {"X": 96, "Y": 4},
			"B": {"X": 94, "Y": 6},
			"C": {"X": 95, "Y": 5},
		}
		r = leave_segment_out_base_rate(counts, "A")
		self.assertLess(r["gap"], 0.02)

	def test_sole_segment_base_rate_zero(self):
		# Only one segment has units: base_rate 0.0, gap == confidence.
		# The variance gate owns this case; this function must not crash.
		r = leave_segment_out_base_rate({"A": {"X": 40}}, "A")
		self.assertEqual(r["base_rate"], 0.0)
		self.assertAlmostEqual(r["gap"], 1.0)

	def test_unknown_segment_is_empty(self):
		r = leave_segment_out_base_rate(self.COUNTS, "nope")
		self.assertEqual(r["n_units"], 0)
		self.assertEqual(r["gap"], 0.0)

	def test_mode_tie_break_is_deterministic(self):
		r = leave_segment_out_base_rate({"A": {"Z": 5, "M": 5}}, "A")
		self.assertEqual(r["consequent"], "M")


class TestVarianceGate(FrappeTestCase):
	def test_near_constant_suppressed(self):
		self.assertTrue(variance_gate({"Standard Selling": 96, "Export": 4}))

	def test_exactly_at_threshold_suppressed(self):
		self.assertTrue(variance_gate({"X": 95, "Y": 5}))

	def test_varied_site_passes(self):
		self.assertFalse(variance_gate({"X": 90, "Y": 10}))

	def test_empty_counts_suppressed(self):
		self.assertTrue(variance_gate({}))

	def test_single_value_site_suppressed(self):
		# The sole-price-list trap: one value, 100% share.
		self.assertTrue(variance_gate({"Standard Selling": 314}))


class TestBurstCollapse(FrappeTestCase):
	def test_import_burst_is_one_unit(self):
		# 30 rows created in consecutive seconds (go-live backfill).
		base = datetime.datetime(2026, 1, 5, 2, 0, 0)
		burst = [base + datetime.timedelta(seconds=i) for i in range(30)]
		self.assertEqual(collapse_bursts(burst), 1)

	def test_organic_creation_counts_each(self):
		base = datetime.datetime(2026, 1, 5, 9, 0, 0)
		organic = [base + datetime.timedelta(hours=3 * i) for i in range(12)]
		self.assertEqual(collapse_bursts(organic), 12)

	def test_mixed_burst_plus_organic(self):
		base = datetime.datetime(2026, 1, 5, 2, 0, 0)
		burst = [base + datetime.timedelta(seconds=i) for i in range(10)]
		organic = [base + datetime.timedelta(days=1 + i) for i in range(3)]
		self.assertEqual(collapse_bursts(burst + organic), 4)

	def test_accepts_iso_strings_and_unsorted_input(self):
		ts = ["2026-01-05 02:00:01", "2026-01-05 02:00:00", "2026-01-07 09:30:00"]
		self.assertEqual(collapse_bursts(ts), 2)

	def test_empty(self):
		self.assertEqual(collapse_bursts([]), 0)


class TestSpreadGate(FrappeTestCase):
	def test_five_distinct_days_pass(self):
		days = [datetime.date(2026, 1, d) for d in range(5, 10)]
		self.assertTrue(spread_ok(days))

	def test_four_days_fail(self):
		days = [datetime.date(2026, 1, d) for d in range(5, 9)]
		self.assertFalse(spread_ok(days))

	def test_many_rows_one_day_fail(self):
		base = datetime.datetime(2026, 1, 5, 2, 0, 0)
		ts = [base + datetime.timedelta(minutes=i) for i in range(100)]
		self.assertFalse(spread_ok(ts))

	def test_day_count_mapping_ignores_zero_counts(self):
		counts = {f"2026-01-0{d}": 3 for d in range(1, 6)}
		self.assertTrue(spread_ok(counts))
		counts["2026-01-05"] = 0
		self.assertFalse(spread_ok(counts))


class TestRecencyGuard(FrappeTestCase):
	def test_material_share_divergence(self):
		self.assertEqual(recency_divergence(0.95, 0.55), "recent_differs")

	def test_consistent_behavior(self):
		self.assertIsNone(recency_divergence(0.95, 0.90))

	def test_no_recent_signal(self):
		self.assertIsNone(recency_divergence(0.95, None))

	def test_changed_mode_value_always_diverges(self):
		# Shares alone look consistent, but the modal VALUE changed
		# (policy change): propose the recent behavior, never the average.
		self.assertEqual(
			recency_divergence(0.9, 0.9, full_mode="30 Days", recent_mode="45 Days"),
			"recent_differs",
		)

	def test_same_mode_value_consistent(self):
		self.assertIsNone(recency_divergence(0.9, 0.85, full_mode="30 Days", recent_mode="30 Days"))


class TestClusterExceptions(FrappeTestCase):
	def test_dominant_customer_cluster(self):
		rows = [{"customer": "Acme", "user": f"u{i}@x.com"} for i in range(7)]
		rows += [{"customer": f"C{i}", "user": "z@x.com"} for i in range(3)]
		cluster = cluster_exceptions(rows)
		self.assertIsNotNone(cluster)
		self.assertEqual(cluster["axis"], "customer")
		self.assertEqual(cluster["value"], "Acme")
		self.assertEqual(cluster["count"], 7)
		self.assertEqual(cluster["total"], 10)
		self.assertAlmostEqual(cluster["share"], 0.7)
		self.assertIn("sub-rule candidate", cluster["note"])

	def test_exact_dominance_share_is_not_a_cluster(self):
		# Plan says >60%, strictly: 3 of 5 == 0.6 does not qualify.
		rows = [{"customer": "Acme"}] * 3 + [{"customer": f"C{i}"} for i in range(2)]
		self.assertIsNone(cluster_exceptions(rows))

	def test_below_min_count_never_clusters(self):
		rows = [{"customer": "Acme"}] * 4
		self.assertIsNone(cluster_exceptions(rows))

	def test_strongest_axis_wins(self):
		# month clusters at 100%, customer only at 70%.
		rows = [{"customer": "Acme", "month": "2025-12"}] * 7
		rows += [{"customer": f"C{i}", "month": "2025-12"} for i in range(3)]
		cluster = cluster_exceptions(rows)
		self.assertEqual(cluster["axis"], "month")
		self.assertAlmostEqual(cluster["share"], 1.0)

	def test_missing_axis_values_ignored(self):
		rows = [{"customer": None, "warehouse": "Main - AC"}] * 7
		rows += [{"warehouse": f"W{i}"} for i in range(3)]
		cluster = cluster_exceptions(rows)
		self.assertEqual(cluster["axis"], "warehouse")
		self.assertEqual(cluster["value"], "Main - AC")

	def test_scattered_exceptions_no_cluster(self):
		rows = [{"customer": f"C{i}", "user": f"u{i}@x.com"} for i in range(10)]
		self.assertIsNone(cluster_exceptions(rows))


class TestRuleOfThree(FrappeTestCase):
	def test_note_at_n_60(self):
		note = rule_of_three_note(60)
		self.assertIn("below 5.0%", note)
		self.assertIn("60 units", note)
		self.assertIn("rule of three", note)

	def test_note_at_n_71(self):
		# The plan's supplier-stockness example: 3/71 = 4.2%.
		self.assertIn("below 4.2%", rule_of_three_note(71))

	def test_no_note_without_units(self):
		self.assertIsNone(rule_of_three_note(0))
		self.assertIsNone(rule_of_three_note(None))
		self.assertIsNone(rule_of_three_note(-5))
