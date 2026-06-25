"""Compute summary statistics over a tabular dataset the agent already has.

The agent gathers rows (via query() / get_list / run_report), then passes them
here to get per-column descriptive stats in one shot - count, nulls, distinct,
a numeric summary (min/max/mean/median/stdev/sum) for number columns, and the
top value frequencies for categorical columns - instead of eyeballing rows or
making the model do arithmetic it gets wrong.

Pure-Python (``statistics`` stdlib); no pandas, no subprocess. It only
summarizes data passed in (no DB access of its own), so it inherits whatever
permission scoping produced that data.
"""
import statistics
from collections import Counter

from jarvis.exceptions import InvalidArgumentError

_MAX_ROWS = 100_000
_DEFAULT_TOP_N = 5


def summarize_dataset(rows: list, columns: list | None = None, top_n: int = 5) -> dict:
	"""Summarize ``rows`` (a list of dicts, or a list of lists with ``columns``).

	Returns ``{"row_count": N, "columns": {col: {...}}}``. Each column reports
	``count`` (non-null), ``null_count``, ``distinct`` and ``type``; numeric
	columns add ``min``/``max``/``sum``/``mean``/``median``/``stdev``;
	categorical/mixed columns add ``top`` (the ``top_n`` most common values).
	"""
	if not isinstance(rows, list) or not rows:
		raise InvalidArgumentError("rows must be a non-empty list")
	if len(rows) > _MAX_ROWS:
		raise InvalidArgumentError(f"too many rows ({len(rows)}); cap is {_MAX_ROWS}")
	top_n = max(1, min(int(top_n or _DEFAULT_TOP_N), 50))

	first = rows[0]
	if isinstance(first, dict):
		cols = list(columns) if columns else list(first.keys())
		records = [r for r in rows if isinstance(r, dict)]

		def get(r, c):
			return r.get(c)
	elif isinstance(first, (list, tuple)):
		if not columns:
			raise InvalidArgumentError("list-of-lists rows require a 'columns' list")
		cols = list(columns)
		records = [r for r in rows if isinstance(r, (list, tuple))]
		idx = {c: i for i, c in enumerate(cols)}

		def get(r, c):
			i = idx[c]
			return r[i] if i < len(r) else None
	else:
		raise InvalidArgumentError("rows must be a list of dicts or a list of lists")

	out = {}
	for c in cols:
		vals = [get(r, c) for r in records]
		non_null = [v for v in vals if v is not None and v != ""]
		nums = [n for n in (_num(v) for v in non_null) if n is not None]
		col = {
			"count": len(non_null),
			"null_count": len(vals) - len(non_null),
			"distinct": len({_hashable(v) for v in non_null}),
		}
		if non_null and len(nums) == len(non_null):
			col["type"] = "numeric"
			col["min"] = min(nums)
			col["max"] = max(nums)
			col["sum"] = sum(nums)
			col["mean"] = statistics.fmean(nums)
			col["median"] = statistics.median(nums)
			col["stdev"] = statistics.pstdev(nums) if len(nums) > 1 else 0.0
		else:
			col["type"] = "mixed" if nums else "categorical"
			counts = Counter(_hashable(v) for v in non_null)
			col["top"] = [{"value": v, "count": n} for v, n in counts.most_common(top_n)]
		out[c] = col
	return {"row_count": len(records), "columns": out}


def _num(v):
	"""Coerce a value to a number, or None. Booleans are NOT numbers here."""
	if isinstance(v, bool):
		return None
	if isinstance(v, (int, float)):
		return v
	if isinstance(v, str):
		try:
			return float(v)
		except ValueError:
			return None
	return None


def _hashable(v):
	return v if isinstance(v, (str, int, float, bool)) else str(v)
