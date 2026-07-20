"""SA 320 planning materiality — deterministic computation.

Clean-room reimplementation of the materiality arithmetic the Assure
auditor product encodes (catalog rules M1-M8, M10). This is the
"connective tissue" the marketplace audit agents need: almost half the
ledger-scrutiny rules bind their thresholds to engagement materiality
(the ``$materiality:*`` placeholders in ``rules/scrutiny-pack.json``),
so ``run_scrutiny`` resolves them from this tool's output.

Why a tool and not model reasoning: materiality drives money-sensitive,
audit-defensible findings; the arithmetic (benchmark x %, half-up
rounding to a step, a risk-driven performance haircut) must be exact and
reproducible, which free-form model math is not.

No ERP reads, no writes - pure arithmetic over the engagement config the
agent stores on ``Jarvis Agent Installation.config``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from jarvis.exceptions import InvalidArgumentError

# M3: performance-materiality haircut % by engagement risk (assure defaults).
# Higher risk -> larger haircut -> lower performance materiality.
_DEFAULT_HAIRCUT_BY_RISK = {"High": 50.0, "Medium": 25.0, "Low": 10.0}
_DEFAULT_TRIVIAL_PCT = 4.0  # M4 (risk-independent, 3-5%)
_DEFAULT_SPECIFIC_PCT = 8.0  # M5 (risk-independent, 5-10%)


def _round_to_step(value: float, step: float) -> float:
	"""M2: ROUND(value / step) * step, half-up. step<=0 -> no rounding."""
	if not step or step <= 0:
		return float(value)
	d_val = Decimal(str(value))
	d_step = Decimal(str(step))
	units = (d_val / d_step).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
	return float(units * d_step)


def compute_materiality(
	benchmark: str | None = None,
	benchmark_value: float | None = None,
	percentage: float | None = None,
	engagement_risk_level: str = "Medium",
	rounding_step: float = 1.0,
	performance_haircut_pct: float | None = None,
	trivial_pct: float | None = None,
	specific_pct: float | None = None,
	bs_balance_amount: float | None = None,
	bs_voucher_amount: float | None = None,
	pl_balance_amount: float | None = None,
	pl_voucher_amount: float | None = None,
) -> dict:
	"""Return SA 320 materiality tiers plus the ``$materiality:*`` bindings
	``run_scrutiny`` consumes.

	Required: ``benchmark_value`` (the chosen FS figure) and ``percentage``
	(the overall-materiality % of it). ``benchmark`` is a label only.

	Tiers (catalog M1-M5):
	  overall      = round_to_step(benchmark_value * percentage/100)
	  performance  = round_to_step(overall * (1 - haircut%/100))   # M3
	  trivial      = round_to_step(overall * trivial%/100)         # M4
	  specific     = round_to_step(overall * specific%/100)        # M5

	Bindings (catalog M10/M12): the scrutiny rules reference
	``$materiality:bs_balance|bs_voucher|pl_balance|pl_voucher|overall|
	performance``. If explicit legacy amounts are supplied they are used
	verbatim; otherwise every balance/voucher binding defaults to
	performance materiality (the conservative single-number default).
	"""
	if benchmark_value is None or percentage is None:
		raise InvalidArgumentError(
			"benchmark_value and percentage are required to compute materiality",
		)
	try:
		benchmark_value = float(benchmark_value)
		percentage = float(percentage)
		rounding_step = float(rounding_step or 1.0)
	except (TypeError, ValueError):
		raise InvalidArgumentError("benchmark_value, percentage, rounding_step must be numeric")
	if benchmark_value < 0:
		raise InvalidArgumentError("benchmark_value must be non-negative")
	if not (0 < percentage <= 100):
		raise InvalidArgumentError("percentage must be in (0, 100]")

	risk = (engagement_risk_level or "Medium").title()
	if risk not in _DEFAULT_HAIRCUT_BY_RISK:
		raise InvalidArgumentError("engagement_risk_level must be High, Medium or Low")

	haircut = performance_haircut_pct
	if haircut is None:
		haircut = _DEFAULT_HAIRCUT_BY_RISK[risk]
	trivial_p = _DEFAULT_TRIVIAL_PCT if trivial_pct is None else float(trivial_pct)
	specific_p = _DEFAULT_SPECIFIC_PCT if specific_pct is None else float(specific_pct)
	haircut = float(haircut)
	if not (0 <= haircut < 100):
		raise InvalidArgumentError("performance_haircut_pct must be in [0, 100)")

	overall = _round_to_step(benchmark_value * percentage / 100.0, rounding_step)
	performance = _round_to_step(overall * (1 - haircut / 100.0), rounding_step)
	trivial = _round_to_step(overall * trivial_p / 100.0, rounding_step)
	specific = _round_to_step(overall * specific_p / 100.0, rounding_step)

	# Legacy scrutiny thresholds (M10): explicit if given, else performance.
	def _binding(explicit):
		return float(explicit) if explicit is not None else performance

	bindings = {
		"overall": overall,
		"performance": performance,
		"bs_balance": _binding(bs_balance_amount),
		"bs_voucher": _binding(bs_voucher_amount),
		"pl_balance": _binding(pl_balance_amount),
		"pl_voucher": _binding(pl_voucher_amount),
	}

	return {
		"overall": overall,
		"performance": performance,
		"trivial": trivial,
		"specific": specific,
		"bindings": bindings,
		"inputs": {
			"benchmark": benchmark,
			"benchmark_value": benchmark_value,
			"percentage": percentage,
			"engagement_risk_level": risk,
			"rounding_step": rounding_step,
			"performance_haircut_pct": haircut,
			"trivial_pct": trivial_p,
			"specific_pct": specific_p,
		},
		"configured": True,
	}
