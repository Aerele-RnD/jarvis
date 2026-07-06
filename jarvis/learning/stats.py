"""Pure statistical gates for pattern learning (plan section 4.1).

Deliberately frappe-free so the whole gate suite is unit-testable without
a site. Every count fed in here is an INDEPENDENT UNIT count (distinct
parent documents, parties, or months as declared per detector) - never
child-table rows; the executor enforces that upstream.

Formal multiple-testing control (Fisher's exact, per-family BH-FDR) is a
committed Phase 2 upgrade; Phase 1 ships these hard gates + human review.
"""

from __future__ import annotations

import datetime
import math

# Strength bands on the Wilson LOWER bound, not raw k/n (plan section 4.1).
BAND_HIGH = 0.90
BAND_MEDIUM = 0.80

# Hard n-gates on units (plan section 4.1): "usually" phrasing needs 20,
# "always/only" needs 60 with 0 exceptions (rule of three).
N_MIN_USUALLY = 20
N_MIN_ALWAYS = 60

MAX_HALF_WIDTH = 0.15
MIN_GAP = 0.15
VARIANCE_THRESHOLD = 0.95
MIN_SPREAD_DAYS = 5


def wilson_lower_bound(k: int, n: int, z: float = 1.96) -> float:
	"""95% Wilson score lower bound: unlike raw k/n it does not reward tiny
	samples, so 5/5 never reads as strong as 205/214."""
	if n <= 0:
		return 0.0
	k = min(max(k, 0), n)
	phat = k / n
	z2 = z * z
	denom = 1 + z2 / n
	center = phat + z2 / (2 * n)
	margin = z * math.sqrt(phat * (1 - phat) / n + z2 / (4 * n * n))
	return max(0.0, (center - margin) / denom)


def wilson_half_width(k: int, n: int, z: float = 1.96) -> float:
	"""Half the Wilson interval width; the precision gate rejects estimates
	too fuzzy to phrase as a habit."""
	if n <= 0:
		return 1.0
	k = min(max(k, 0), n)
	phat = k / n
	z2 = z * z
	denom = 1 + z2 / n
	margin = z * math.sqrt(phat * (1 - phat) / n + z2 / (4 * n * n))
	return margin / denom


def band(wilson_low: float) -> str:
	"""Strength band on the Wilson lower bound: High >= 0.90, Medium
	0.80-0.90, Low < 0.80 (plan: strength_band is banded on wilson_low)."""
	if wilson_low >= BAND_HIGH:
		return "High"
	if wilson_low >= BAND_MEDIUM:
		return "Medium"
	return "Low"


def precision_ok(k: int, n: int, max_half_width: float = MAX_HALF_WIDTH) -> bool:
	"""Precision gate: Wilson half-width <= 0.15, else the candidate is
	data_starved rather than proposed (plan section 4.1)."""
	return wilson_half_width(k, n) <= max_half_width


def leave_segment_out_base_rate(counts: dict, antecedent, consequent=None) -> dict:
	"""Confidence vs the base rate computed EXCLUDING the target segment; a
	naive lift ratio passes trivially on skewed marginals (plan gap gate).

	``counts`` is {antecedent_value: {consequent_value: unit_count}}. When
	``consequent`` is None the target segment's mode value is used (ties
	broken by count desc, then value string asc, deterministically).
	Returns {consequent, k, n_units, confidence, base_rate, gap}.
	``base_rate`` is 0.0 when no OTHER segment has units - sole-segment
	sites are the variance gate's job, not a free gap win.
	"""
	segment = counts.get(antecedent) or {}
	n_units = sum(segment.values())
	if not n_units:
		return {
			"consequent": consequent,
			"k": 0,
			"n_units": 0,
			"confidence": 0.0,
			"base_rate": 0.0,
			"gap": 0.0,
		}
	if consequent is None:
		consequent = sorted(segment.items(), key=lambda kv: (-kv[1], str(kv[0])))[0][0]
	k = segment.get(consequent, 0)
	confidence = k / n_units

	rest_k = 0
	rest_n = 0
	for other, dist in counts.items():
		if other == antecedent:
			continue
		rest_n += sum(dist.values())
		rest_k += dist.get(consequent, 0)
	base_rate = (rest_k / rest_n) if rest_n else 0.0

	return {
		"consequent": consequent,
		"k": k,
		"n_units": n_units,
		"confidence": confidence,
		"base_rate": base_rate,
		"gap": confidence - base_rate,
	}


def variance_gate(site_wide_counts: dict, threshold: float = VARIANCE_THRESHOLD) -> bool:
	"""True = suppress: the consequent is near-constant site-wide (one value
	holds >= threshold of all units), so per-antecedent proposals would just
	restate the org default (kills sole-price-list / all-non-stock /
	vanilla-default restatements; emit at most ONE org-level card instead).
	No data also suppresses."""
	total = sum(site_wide_counts.values())
	if not total:
		return True
	return max(site_wide_counts.values()) / total >= threshold


def collapse_bursts(timestamps, max_gap_s: int = 1) -> int:
	"""Effective unit count with creation-burst runs collapsed to one unit:
	rows created in consecutive-second runs (imports, go-live backfills) are
	one event, so a migration batch cannot satisfy n_min (plan spread gate).
	"""
	ts = sorted(_to_datetime(t) for t in timestamps)
	if not ts:
		return 0
	units = 1
	for prev, cur in zip(ts, ts[1:]):
		if (cur - prev).total_seconds() > max_gap_s:
			units += 1
	return units


def spread_ok(days_or_timestamps, min_days: int = MIN_SPREAD_DAYS) -> bool:
	"""Spread gate: evidence must span >= min_days distinct calendar days;
	one busy afternoon (or one import batch) is not an organizational habit.

	Accepts either {day: count} (SQL-aggregated) or an iterable of
	timestamps/dates.
	"""
	if isinstance(days_or_timestamps, dict):
		days = {d for d, c in days_or_timestamps.items() if c}
	else:
		days = {_to_date(t) for t in days_or_timestamps}
	return len(days) >= min_days


def recency_divergence(
	full_window_mode_share: float,
	last90_mode_share: float | None,
	threshold: float = 0.2,
	full_mode=None,
	recent_mode=None,
) -> str | None:
	"""Recency guard: 'recent_differs' when last-90-day behavior materially
	diverges from the full window - propose the RECENT habit or withhold,
	never average over a policy change (plan section 4.1).

	A changed mode VALUE (pass full_mode/recent_mode) always diverges; else
	the mode shares must differ by >= threshold. None when consistent or
	when the recent window has no signal (last90_mode_share is None).
	"""
	if full_mode is not None and recent_mode is not None and full_mode != recent_mode:
		return "recent_differs"
	if last90_mode_share is None:
		return None
	if abs(full_window_mode_share - last90_mode_share) >= threshold:
		return "recent_differs"
	return None


def cluster_exceptions(
	exception_rows,
	keys=("customer", "user", "month", "cost_center", "warehouse"),
	min_count: int = 5,
	dominance: float = 0.6,
) -> dict | None:
	"""Exceptions concentrating in one entity are a sub-rule candidate, not
	noise: > dominance share on any axis, over >= min_count total exceptions
	(plan: exception_cluster, >60% in one entity => sub-rule candidate).

	``exception_rows`` is a list of dicts keyed by the cluster axes; missing
	or empty axis values are ignored per axis. Returns the strongest cluster
	as {axis, value, count, total, share, note}, or None.
	"""
	rows = [r for r in exception_rows if r]
	if len(rows) < min_count:
		return None
	best = None
	for axis in keys:
		tally: dict = {}
		for row in rows:
			value = row.get(axis)
			if value in (None, ""):
				continue
			tally[value] = tally.get(value, 0) + 1
		if not tally:
			continue
		value, count = max(tally.items(), key=lambda kv: (kv[1], str(kv[0])))
		share = count / len(rows)
		if share > dominance and (best is None or share > best["share"]):
			best = {
				"axis": axis,
				"value": value,
				"count": count,
				"total": len(rows),
				"share": share,
				"note": (
					f"{count} of {len(rows)} exceptions concentrate in "
					f"{axis} {value} - sub-rule candidate"
				),
			}
	return best


def rule_of_three_note(n_units: int) -> str | None:
	"""Rule of three on units: with 0 exceptions in n units the 95% upper
	bound on the true exception rate is 3/n - the basis for requiring
	n >= 60 before 'always/only' phrasing. Drill-down only: the plan bans
	this parenthetical from compiled skill text."""
	if not n_units or n_units <= 0:
		return None
	pct = 100.0 * 3.0 / n_units
	return (
		f"0 exceptions in {n_units} units: true exception rate below "
		f"{pct:.1f}% at 95% confidence (rule of three)"
	)


def _to_datetime(value) -> datetime.datetime:
	if isinstance(value, datetime.datetime):
		return value
	if isinstance(value, datetime.date):
		return datetime.datetime(value.year, value.month, value.day)
	return datetime.datetime.fromisoformat(str(value))


def _to_date(value) -> datetime.date:
	if isinstance(value, datetime.datetime):
		return value.date()
	if isinstance(value, datetime.date):
		return value
	return datetime.datetime.fromisoformat(str(value)).date()
