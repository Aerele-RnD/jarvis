"""Unit tests for the agents-marketplace deterministic audit core.

compute_materiality is pure arithmetic (no DB) so it is fully asserted
here. run_scrutiny is integration-validated against a live GL (see the
build validation); its pure helpers (threshold binding, pack loading)
are covered here.
"""
import unittest

from jarvis.tools.compute_materiality import compute_materiality
from jarvis.tools.run_scrutiny import _load_pack, _resolve_threshold
from jarvis.exceptions import InvalidArgumentError


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
        self.assertTrue(any(r["status"] == "needs_legal_review" for r in pack["rules"]))

    def test_pack_unknown_raises(self):
        with self.assertRaises(InvalidArgumentError):
            _load_pack("no-such-pack")

    def test_pack_inline_dict(self):
        self.assertEqual(_load_pack({"pack_id": "x", "rules": []})["pack_id"], "x")
