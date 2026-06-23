"""Expression DSL for the qb-based ``query`` tool.

A tree-shaped, whitelist-driven mini-language for computed columns and
SQL functions inside structured query specs. Closes the
"no expressions in spec" gap for the high-frequency reporting patterns
(per-period bucketing, NULL fallback, arithmetic in SELECT,
conditional aggregation) without breaching the safety boundary that
makes the structured spec resistant to SQL injection.

Three node kinds compose:

- ``{"fn": "<name>", "args": [<arg>, ...]}`` — function call
- ``{"field": "alias.col"}`` — column reference
- ``{"literal": 42}`` — literal value (string / number / bool / None)

Each ``arg`` is itself one of the three. The validator walks the tree
once, checks every entry against the whitelist registry, then the
translator emits pypika expressions. No string evaluation; no
arbitrary SQL.

Permission model: expressions compose fields the caller already has
read access to via the spec's ``alias_map``. Literals are inert.
Functions are inert wrappers. The 5-layer perm weave applies to the
rows returned, regardless of what computation the SELECT projection
runs on each row's columns.

Dialect handling: most functions are uniform across MariaDB /
Postgres / SQLite (pypika exposes a shared constructor). Date
functions need dispatch (``EXTRACT(MONTH FROM x)`` on
MariaDB/Postgres, ``strftime('%m', x)`` on SQLite). Dispatch is by
``frappe.local.conf.db_type``.

The registry is intentionally laid out as a flat dict so each phase
of the DSL rollout adds entries without restructuring. Phase 1
populates the date family; Phases 2-4 add NULL/arithmetic,
conditional, and string families.
"""
from __future__ import annotations

from typing import Any, Callable

import frappe
from pypika import functions as fn
from pypika.terms import Field, Term

from jarvis.exceptions import InvalidArgumentError


# Maximum nesting depth for expression trees. Caps runaway agent
# payloads. 4 is enough for the realistic compositions:
# round(mul(coalesce(qty, 0), rate), 2) — depth 4.
MAX_EXPR_DEPTH = 4


# ---- Registry --------------------------------------------------------


# Each registry entry is a dict with:
#   - ``arity``: ``(min, max)`` tuple; ``max=None`` means variadic
#   - ``args``: list of arg-kind constants describing each positional
#     arg. ``"expr"`` accepts any expression node. ``"literal"`` only
#     accepts a literal node. ``"field"`` only accepts a field node.
#     ``"any"`` accepts any node kind.
#   - ``args_uniform``: when set instead of ``args``, all args must be
#     of this single kind (used by variadic functions).
#   - ``literal_constraint``: optional dict ``{arg_index: allowed_set}``
#     restricting which literal values are permitted at that position.
#   - ``builder``: callable ``(translated_args: list, dialect: str) ->
#     pypika.Term`` that constructs the final pypika expression.
_REGISTRY: dict[str, dict] = {}


def _register(name: str, **entry) -> None:
	"""Register a function in the DSL. Raises if the name is already
	registered — catches typos / double-registration at import time."""
	if name in _REGISTRY:
		raise RuntimeError(f"DSL function {name!r} already registered")
	_REGISTRY[name] = entry


# ---- Argument-kind sentinels ----------------------------------------


_ARG_KINDS = ("expr", "field", "literal", "any")


# Recognised date_part / date_trunc units. The first arg of these
# functions is a literal restricted to this set.
_DATE_UNITS = frozenset({
	"year", "month", "quarter", "week", "day", "fiscal_year",
})


# ---- Phase 1: date functions ----------------------------------------


def _build_date_part(args: list, dialect: str) -> Term:
	"""``date_part(unit, x)`` → integer (year, month, etc.).

	Unit values use lowercase names (year/month/quarter/week/day/
	fiscal_year). pypika.Extract emits ``EXTRACT(UNIT FROM x)`` which
	MariaDB 5.7+ and Postgres both honour. SQLite has no EXTRACT, so
	we fall back to ``strftime('%fmt', x)`` and rely on the test
	suite to verify the dispatch.

	``fiscal_year`` is ERPNext-specific: there's no SQL equivalent, so
	we route through ``frappe.utils.get_fiscal_year`` at the row
	level. That's expensive but rare enough — for hot paths the agent
	should use a date-range WHERE per fiscal year instead.
	"""
	unit, x = args
	unit = unit.lower()  # already validated against _DATE_UNITS
	if unit == "fiscal_year":
		raise InvalidArgumentError(
			"date_part('fiscal_year', ...) is not yet supported in SQL; "
			"use a date-range WHERE per fiscal year instead, or compute "
			"the bucket in the response from get_list rows"
		)
	if dialect == "sqlite":
		# strftime format codes per unit. SQLite returns text; we
		# cast to integer to match EXTRACT's behavior.
		_strftime_fmt = {
			"year": "%Y",
			"month": "%m",
			"quarter": None,  # SQLite has no quarter; build via month/3
			"week": "%W",
			"day": "%d",
		}
		fmt = _strftime_fmt.get(unit)
		if fmt is None:
			# Quarter: ceil(month/3). Build from strftime('%m').
			month_expr = fn.Cast(
				fn.Function("strftime", "%m", x), "INTEGER"
			)
			return fn.Function(
				"CAST",
				fn.Function("CEIL", month_expr / 3),
				"INTEGER",
			)
		return fn.Cast(fn.Function("strftime", fmt, x), "INTEGER")
	# MariaDB / Postgres: SQL-standard EXTRACT.
	if unit == "quarter":
		# EXTRACT(QUARTER FROM x) works on MariaDB and Postgres.
		return fn.Extract("QUARTER", x)
	# year, month, week, day all map directly to EXTRACT.
	return fn.Extract(unit.upper(), x)


def _build_date_trunc(args: list, dialect: str) -> Term:
	"""``date_trunc(unit, x)`` → first day of the bucket.

	Useful for grouping rows by month-start / quarter-start dates
	rather than extracting just the numeric component.

	Postgres has ``DATE_TRUNC('month', x)`` natively. MariaDB has no
	equivalent; we approximate by combining EXTRACT with date
	construction. SQLite uses ``date(x, 'start of month')``.

	Production is MariaDB; the MariaDB path is the load-bearing one.
	"""
	unit, x = args
	unit = unit.lower()
	if unit == "fiscal_year":
		raise InvalidArgumentError(
			"date_trunc('fiscal_year', ...) is not yet supported in SQL; "
			"see date_part documentation for the workaround"
		)
	if dialect == "postgres":
		return fn.Function("DATE_TRUNC", unit, x)
	if dialect == "sqlite":
		# SQLite: date(x, 'start of month') / 'start of year'. No
		# native 'start of quarter' or 'start of week'.
		_modifier = {
			"year": "start of year",
			"month": "start of month",
			"day": "start of day",
		}
		mod = _modifier.get(unit)
		if mod is None:
			raise InvalidArgumentError(
				f"date_trunc({unit!r}, ...) not supported on SQLite; "
				f"use one of: year, month, day"
			)
		return fn.Function("date", x, mod)
	# MariaDB: build YYYY-MM-01 (etc.) via DATE_FORMAT.
	_fmt = {
		"year": "%Y-01-01",
		"month": "%Y-%m-01",
		"day": "%Y-%m-%d",
	}
	fmt_str = _fmt.get(unit)
	if fmt_str is None:
		raise InvalidArgumentError(
			f"date_trunc({unit!r}, ...) not supported on MariaDB; "
			f"use one of: year, month, day"
		)
	return fn.Function(
		"STR_TO_DATE",
		fn.Function("DATE_FORMAT", x, fmt_str),
		"%Y-%m-%d",
	)


def _build_date_add(args: list, dialect: str) -> Term:
	"""``date_add(x, n, unit)`` → x + n units.

	``n`` is a literal integer (can be negative for subtraction).
	``unit`` is a literal from the same set as date_part.
	"""
	x, n, unit = args
	unit = unit.lower()
	if unit == "fiscal_year":
		raise InvalidArgumentError(
			"date_add(..., 'fiscal_year') is not yet supported"
		)
	if dialect == "sqlite":
		# date(x, '+N months') style.
		_singular = {
			"year": "years", "month": "months", "quarter": "months",
			"week": "days", "day": "days",
		}
		multiplier = {"quarter": 3, "week": 7}.get(unit, 1)
		actual_n = n * multiplier
		sign = "+" if actual_n >= 0 else "-"
		modifier = f"{sign}{abs(actual_n)} {_singular[unit]}"
		return fn.Function("date", x, modifier)
	# MariaDB / Postgres: DATE_ADD(x, INTERVAL N UNIT).
	# pypika exposes Function for arbitrary calls.
	return fn.Function(
		"DATE_ADD", x, fn.LiteralValue(f"INTERVAL {n} {unit.upper()}")
	)


_register(
	"date_part",
	arity=(2, 2),
	args=["literal", "expr"],
	literal_constraint={0: _DATE_UNITS},
	builder=_build_date_part,
)
_register(
	"date_trunc",
	arity=(2, 2),
	args=["literal", "expr"],
	literal_constraint={0: _DATE_UNITS},
	builder=_build_date_trunc,
)
_register(
	"date_add",
	arity=(3, 3),
	args=["expr", "literal", "literal"],
	literal_constraint={2: _DATE_UNITS},
	builder=_build_date_add,
)


# ---- Public API: validate + build ------------------------------------


def is_expr_node(node: Any) -> bool:
	"""Return True if ``node`` is a recognised expression node (a
	dict carrying one of the three top-level keys). Used by callers
	in ``query.py`` to distinguish expression entries from bare-string
	field references and legacy aggregate dicts."""
	return (
		isinstance(node, dict)
		and (
			"fn" in node or "field" in node or "literal" in node
		)
	)


def validate_expr(node: Any, depth: int = 1) -> None:
	"""Recursively validate an expression tree.

	Raises ``InvalidArgumentError`` on the first violation. Catches:
	- unknown function names
	- arity mismatches
	- wrong arg kinds (e.g. ``field`` where ``literal`` expected)
	- literal-value constraint violations (e.g. unknown date_part unit)
	- nesting deeper than ``MAX_EXPR_DEPTH``

	Field-reference syntax (``"alias.col"``) is NOT validated here -
	that happens at translate time via ``_resolve_field`` in query.py,
	which has the ``alias_map``. This validator runs before the
	alias_map exists, so we restrict ourselves to structural checks.
	"""
	if depth > MAX_EXPR_DEPTH:
		raise InvalidArgumentError(
			f"expression nesting exceeds the {MAX_EXPR_DEPTH}-level cap"
		)
	if not isinstance(node, dict):
		raise InvalidArgumentError(
			f"expression node must be a dict, got {type(node).__name__}"
		)
	# Leaf nodes: field, literal.
	if "field" in node:
		if not isinstance(node["field"], str) or not node["field"]:
			raise InvalidArgumentError(
				"expression {field: ...} must carry a non-empty string"
			)
		# Disallow other keys alongside ``field`` to keep the shape
		# disambiguous (and force the agent to compose via fn nodes).
		other = set(node) - {"field"}
		if other:
			raise InvalidArgumentError(
				f"expression {{field: ...}} cannot also carry "
				f"{sorted(other)!r}"
			)
		return
	if "literal" in node:
		# ``literal`` accepts any scalar (string, int, float, bool, None).
		# Reject dicts/lists - those would smuggle in unstructured data.
		v = node["literal"]
		if isinstance(v, (dict, list)):
			raise InvalidArgumentError(
				"expression {literal: ...} must carry a scalar "
				"(string / number / bool / None)"
			)
		other = set(node) - {"literal"}
		if other:
			raise InvalidArgumentError(
				f"expression {{literal: ...}} cannot also carry "
				f"{sorted(other)!r}"
			)
		return
	# Function call.
	if "fn" not in node:
		raise InvalidArgumentError(
			"expression node must carry one of: 'fn', 'field', 'literal'"
		)
	name = node["fn"]
	if not isinstance(name, str):
		raise InvalidArgumentError("expression 'fn' must be a string")
	if name not in _REGISTRY:
		raise InvalidArgumentError(
			f"unknown DSL function {name!r}; known: {sorted(_REGISTRY)}"
		)
	entry = _REGISTRY[name]
	args = node.get("args") or []
	if not isinstance(args, list):
		raise InvalidArgumentError(
			f"expression {name!r} args must be a list"
		)
	arity_min, arity_max = entry["arity"]
	if len(args) < arity_min or (arity_max is not None and len(args) > arity_max):
		max_s = "infinity" if arity_max is None else arity_max
		raise InvalidArgumentError(
			f"expression {name!r} takes {arity_min}..{max_s} args, "
			f"got {len(args)}"
		)
	# Per-arg kind check.
	expected_kinds = entry.get("args", [])
	uniform = entry.get("args_uniform")
	for i, a in enumerate(args):
		kind = expected_kinds[i] if i < len(expected_kinds) else (
			uniform if uniform else "any"
		)
		_check_arg_kind(name, i, kind, a)
		# Literal-value constraint (e.g. date_part's unit set).
		constraints = entry.get("literal_constraint") or {}
		if i in constraints and "literal" in a:
			allowed = constraints[i]
			v = a["literal"]
			if isinstance(v, str):
				v_normalized = v.lower()
			else:
				v_normalized = v
			if v_normalized not in allowed:
				raise InvalidArgumentError(
					f"expression {name!r} arg {i} must be one of "
					f"{sorted(allowed)!r}, got {v!r}"
				)
		# Recurse for sub-expressions.
		validate_expr(a, depth=depth + 1)


def _check_arg_kind(fn_name: str, idx: int, expected_kind: str, node: Any) -> None:
	"""Validate one positional arg's node kind against the function's
	declared expectation. ``expected_kind`` is one of _ARG_KINDS."""
	if not isinstance(node, dict):
		raise InvalidArgumentError(
			f"expression {fn_name!r} arg {idx} must be a dict, "
			f"got {type(node).__name__}"
		)
	if expected_kind == "any":
		return
	if expected_kind == "literal":
		if "literal" not in node:
			raise InvalidArgumentError(
				f"expression {fn_name!r} arg {idx} must be a literal "
				f"({{literal: ...}})"
			)
		return
	if expected_kind == "field":
		if "field" not in node:
			raise InvalidArgumentError(
				f"expression {fn_name!r} arg {idx} must be a field "
				f"reference ({{field: 'alias.col'}})"
			)
		return
	if expected_kind == "expr":
		# Any of the three node kinds is acceptable.
		if not is_expr_node(node):
			raise InvalidArgumentError(
				f"expression {fn_name!r} arg {idx} must be a "
				f"{{fn|field|literal}} node"
			)
		return
	raise RuntimeError(f"unreachable: bad expected_kind {expected_kind!r}")


def build_expr(node: dict, resolve_field: Callable[[str], Term]) -> Term:
	"""Translate a validated expression tree to a pypika Term.

	``resolve_field`` is the field-resolution callback - in practice
	this is ``lambda ref: _resolve_field(ref, alias_map)`` from
	query.py, but we keep this module decoupled from query.py to
	avoid circular imports.

	Validation must have run first; this builder assumes well-formed
	input and emits AttributeError on misuse rather than user-facing
	errors.
	"""
	# Leaf: field reference.
	if "field" in node:
		return resolve_field(node["field"])
	# Leaf: literal.
	if "literal" in node:
		v = node["literal"]
		# pypika handles None/bool/int/float/str directly when wrapped
		# in LiteralValue for special cases, but for most scalars the
		# Python value works as-is when composed with Term operators.
		return _literal_term(v)
	# Function call.
	name = node["fn"]
	entry = _REGISTRY[name]
	dialect = _current_dialect()
	# Translate each arg first.
	translated = []
	for a in node.get("args") or []:
		if "literal" in a:
			# Literals stay as raw Python values - the builder may
			# need them as ints / strings rather than pypika Terms.
			translated.append(a["literal"])
		else:
			translated.append(build_expr(a, resolve_field))
	return entry["builder"](translated, dialect)


def _literal_term(v: Any) -> Term:
	"""Wrap a Python scalar in a pypika Term for use as a value in an
	expression. pypika auto-handles most scalars when they appear on
	the right-hand side of an operator (`field == 'Paid'`), but when a
	literal needs to BE the expression (e.g. ``then: {"literal": 0}``
	in CASE), we need an explicit Term wrapper."""
	from pypika.terms import ValueWrapper
	return ValueWrapper(v)


def _current_dialect() -> str:
	"""Return ``"mariadb" | "postgres" | "sqlite"``. Reads
	``frappe.local.conf.db_type`` with a MariaDB default for sites
	that haven't set the field explicitly (older Frappe versions
	default to MariaDB)."""
	db_type = getattr(frappe.local, "conf", {}).get("db_type") if (
		hasattr(frappe, "local")
	) else None
	if db_type in ("mariadb", "postgres", "sqlite"):
		return db_type
	# Default. Production is MariaDB.
	return "mariadb"


# ---- Introspection ---------------------------------------------------


def known_functions() -> list[str]:
	"""Return the list of registered DSL functions in alphabetical
	order. Used by tests and (potentially) by tool-description
	generation to keep the persona's worked-example list in sync."""
	return sorted(_REGISTRY)
