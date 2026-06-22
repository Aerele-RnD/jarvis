"""Structured query tool — qb-based replacement for run_query.

The operator-authored-SQL design of run_query had two structural
problems with the same root cause: WE didn't construct the query,
the agent did.

1. **Multi-DB lock-in.** Raw MariaDB SQL doesn't run on Postgres or
   SQLite. Frappe v15+ supports all three; the framework recommends
   ``frappe.qb`` over raw SQL specifically because qb handles dialect
   translation (column quoting, function name mapping, etc.).

2. **Record-level permissions can't be enforced.** Frappe's
   ``DatabaseQuery.execute()`` weaves WHERE predicates from User
   Permissions, ``permission_query_conditions`` hooks, DocShare,
   ``if_owner`` constraints, and role-based access into the query at
   build time. There's no public hook to weave those into arbitrary
   operator-authored SQL.

The fix for both: **build the query ourselves** from a structured
spec the agent provides. The spec is dialect-agnostic; ``frappe.qb``
handles dialect translation. The query is constructed via the
``Engine`` API; ``Engine.get_permission_conditions()`` (at
``frappe/database/query.py:1619``) returns a pypika ``Criterion`` we
AND into our query's WHERE clause — that one call covers all five
permission layers natively.

Spec shape::

    {
        "from": "Sales Invoice",
        "alias": "si",
        "joins": [
            {"type": "left", "doctype": "Sales Invoice Item",
             "alias": "sii", "on": {"sii.parent": "si.name"}}
        ],
        "select": [
            "si.customer",
            {"agg": "sum", "field": "sii.qty", "as": "total_qty"}
        ],
        "where": [
            {"field": "si.status", "op": "=", "value": "Submitted"},
            {"field": "si.posting_date", "op": ">=", "value": "2026-06-01"}
        ],
        "group_by": ["si.customer"],
        "having": [{"agg": "sum", "field": "sii.qty", "op": ">",
                    "value": 100}],
        "order_by": [{"field": "total_qty", "dir": "desc"}],
        "limit": 100,
    }

Aliases are mandatory on joined tables; the FROM table's alias is
recommended (so the field references remain consistent across the
spec) but tolerated if omitted (the doctype name itself acts as the
implicit alias).

What this tool gives up vs ``run_query``:

- Window functions (rare; not used by the persona today).
- Recursive CTEs (very rare).
- UNION (express via two ``query`` calls + concat in the caller).
- Inline raw SQL fragments — no ``CASE WHEN ...`` or arbitrary
  expressions. The agent can't smuggle SQL through the spec.

These are the deliberate trade for portability + record-level
permission enforcement.
"""

from __future__ import annotations

from typing import Any

import frappe
from pypika import Order
from pypika import functions as fn
from pypika.terms import Criterion

from jarvis.exceptions import (
	InvalidArgumentError,
	PermissionDeniedError,
	ResultTooLargeError,
)
from jarvis.tools.run_query import (
	# Reuse the per-site DocType allowlist gate. Both ``query`` and
	# ``run_query`` honor the same ``Jarvis Settings.run_query_doctype_allowlist``
	# field - one knob gates both tools.
	_load_doctype_allowlist,
)

# Row guard: refuse a result over this size unless the caller passes
# ``confirm_large=True``. Mirrors the run_query guard so the agent's
# mental model carries across the two tools.
ROW_GUARD = 200
MAX_LIMIT = 1000
DEFAULT_LIMIT = 100

# Operators allowed in ``where`` / ``having`` clauses. The dispatch
# table below maps each to a callable that produces a pypika Criterion.
_OPERATORS = {
	"=", "!=",
	"<", "<=", ">", ">=",
	"in", "not in",
	"like", "not like",
	"is null", "is not null",
	"between",
}

# Aggregate functions allowed in ``select`` and ``having``. Each maps
# to a pypika function class; we instantiate it with the resolved
# column at translation time.
_AGGREGATES = {
	"sum": fn.Sum,
	"count": fn.Count,
	"avg": fn.Avg,
	"min": fn.Min,
	"max": fn.Max,
}

# Join type → pypika method name on the QueryBuilder.
_JOIN_METHODS = {
	"inner": "inner_join",
	"left": "left_join",
	"right": "right_join",
}


def query(spec: dict, confirm_large: bool = False) -> dict:
	"""Execute a structured query spec and return rows + the resolved SQL.

	Returns ``{"sql": "<resolved SQL>", "rows": [...]}``. The SQL is
	included for operator triage / debugging (mirrors run_query).

	Pipeline:

	1. Validate spec shape (raise ``InvalidArgumentError`` on failure).
	2. Extract referenced DocTypes (FROM + joins).
	3. DocType-level read permission check per referenced DocType.
	4. Per-site DocType allowlist check (reused from run_query).
	5. Build the qb query from the spec.
	6. Apply ``Engine.get_permission_conditions()`` for each referenced
	   DocType — weaves User Permissions + permission_query_conditions
	   hooks + DocShare + if_owner + role-based access predicates into
	   the WHERE clause. The single critical call that makes this tool
	   permission-honoring where run_query couldn't be.
	7. Execute via ``.run(as_dict=True)``.
	8. Row guard.

	Raises:
		InvalidArgumentError: spec is malformed.
		PermissionDeniedError: caller lacks DocType-level read OR a
			referenced DocType is not on the per-site allowlist.
		ResultTooLargeError: result exceeds ``ROW_GUARD`` and
			``confirm_large`` is False.
	"""
	if not isinstance(spec, dict):
		raise InvalidArgumentError("spec must be a dict")

	# Step 1: validate spec shape (lightweight; deep validation happens
	# during translation when we have type context).
	_validate_spec_shape(spec)

	# Step 2: collect all referenced DocTypes for the permission gates.
	doctypes = _collect_doctypes(spec)

	# Step 3: DocType-level read permission gate (mirrors run_query).
	for dt in doctypes:
		if not frappe.has_permission(dt, ptype="read"):
			raise PermissionDeniedError(
				f"no read permission on referenced DocType: {dt}"
			)

	# Step 4: per-site DocType allowlist (defense-in-depth).
	allowlist = _load_doctype_allowlist()
	if allowlist is not None:
		for dt in doctypes:
			if dt not in allowlist:
				raise PermissionDeniedError(
					f"DocType {dt!r} is not in this site's query allowlist; "
					f"add it to Jarvis Settings.run_query_doctype_allowlist "
					f"to enable."
				)

	# Step 5: translate spec → qb expression. ``alias_map`` carries the
	# spec-alias → pypika.Table mapping so where/select/group_by/etc.
	# can resolve "alias.field" references.
	from_table, alias_map = _build_from_and_aliases(spec)
	q = frappe.qb.from_(from_table)

	# Joins.
	for j in spec.get("joins") or []:
		joined_table = frappe.qb.DocType(j["doctype"]).as_(j["alias"])
		alias_map[j["alias"]] = (j["doctype"], joined_table)
		on_criterion = _build_on_criterion(j["on"], alias_map)
		join_method_name = _JOIN_METHODS[j.get("type", "inner")]
		q = getattr(q, join_method_name)(joined_table).on(on_criterion)

	# SELECT.
	select_terms = _build_select(spec.get("select") or ["name"], alias_map)
	q = q.select(*select_terms)

	# WHERE.
	for w in spec.get("where") or []:
		q = q.where(_build_predicate(w, alias_map))

	# GROUP BY.
	for gb in spec.get("group_by") or []:
		q = q.groupby(_resolve_field(gb, alias_map))

	# HAVING.
	for h in spec.get("having") or []:
		q = q.having(_build_predicate(h, alias_map))

	# ORDER BY.
	for ob in spec.get("order_by") or []:
		field = _resolve_field(ob["field"], alias_map, allow_alias=True)
		direction = Order.desc if ob.get("dir", "asc").lower() == "desc" else Order.asc
		q = q.orderby(field, order=direction)

	# LIMIT. ``or`` would treat 0 as falsy and silently substitute the
	# default; explicit None-check preserves operator intent and lets
	# the validation below catch 0 as the invalid value it is.
	limit_raw = spec.get("limit")
	limit = DEFAULT_LIMIT if limit_raw is None else int(limit_raw)
	if limit <= 0 or limit > MAX_LIMIT:
		raise InvalidArgumentError(f"limit must be between 1 and {MAX_LIMIT}")
	q = q.limit(limit)

	# Step 6: weave record-level permission predicates per DocType.
	# This is the structural difference vs run_query - one call per
	# doctype, all five permission layers covered. Engine returns
	# ``None`` when the user has no restrictions for the doctype; we
	# skip appending in that case (no-op).
	#
	# Engine is normally bootstrapped via ``get_query()``; we don't go
	# through that path because we already have our own qb query built.
	# Instead we instantiate Engine directly and set the few attributes
	# its permission helpers read: ``user``, ``ignore_user_permissions``,
	# ``ignore_permissions``. Anything else
	# ``get_permission_conditions()`` touches we'll discover via test
	# failures and add here.
	from frappe.database.query import Engine
	engine = Engine()
	engine.user = frappe.session.user
	engine.ignore_user_permissions = False
	engine.ignore_permissions = False
	# Engine's permission-condition helpers introspect ``self.query`` to
	# find which tables are in scope (for things like related-doctype
	# joins driven by User Permissions). Sharing our being-built query
	# lets the engine see the full join graph; the get_permission_conditions
	# call is read-only on the query so mutations are safe.
	engine.query = q
	# Some permission_query_conditions hooks consult ``self.tables``;
	# pre-populate it from our alias_map.
	engine.tables = [table for (_, table) in alias_map.values()]
	for dt in doctypes:
		# Find the table object we built for this doctype. If the spec
		# has multiple references to the same doctype (rare; usually
		# self-join scenarios) we apply the predicate to each instance.
		for alias, (resolved_dt, table) in alias_map.items():
			if resolved_dt == dt:
				cond = engine.get_permission_conditions(dt, table)
				if cond is not None:
					q = q.where(cond)

	# Step 7: execute.
	rows = q.run(as_dict=True)

	# Step 8: row guard (post-execute - we can't know the row count
	# without running, and limiting earlier would break aggregates).
	if len(rows) > ROW_GUARD and not confirm_large:
		raise ResultTooLargeError(
			row_count=len(rows),
			limit=ROW_GUARD,
			tool="query",
		)

	# Resolve the SQL for the operator triage payload. ``get_sql()``
	# is the qb call that produces the final dialect-specific SQL
	# string; safe to expose since the spec doesn't carry secrets.
	try:
		resolved_sql = q.get_sql()
	except Exception:
		resolved_sql = "<sql resolution failed>"

	return {"sql": resolved_sql, "rows": rows}


# ---- Spec validation ------------------------------------------------


def _validate_spec_shape(spec: dict) -> None:
	"""Top-of-pipe shape check. Catches obvious mistakes early so the
	translator below can assume its inputs are well-formed."""
	if "from" not in spec or not isinstance(spec["from"], str):
		raise InvalidArgumentError("spec.from must be a DocType name (string)")

	if "joins" in spec:
		if not isinstance(spec["joins"], list):
			raise InvalidArgumentError("spec.joins must be a list")
		seen_aliases = {spec.get("alias") or spec["from"]}
		for i, j in enumerate(spec["joins"]):
			if not isinstance(j, dict):
				raise InvalidArgumentError(f"spec.joins[{i}] must be a dict")
			for k in ("doctype", "alias", "on"):
				if k not in j:
					raise InvalidArgumentError(
						f"spec.joins[{i}] missing required field: {k}"
					)
			if j["alias"] in seen_aliases:
				raise InvalidArgumentError(
					f"spec.joins[{i}] alias {j['alias']!r} collides with "
					f"another table in this query"
				)
			seen_aliases.add(j["alias"])
			if j.get("type", "inner") not in _JOIN_METHODS:
				raise InvalidArgumentError(
					f"spec.joins[{i}].type must be one of: "
					f"{sorted(_JOIN_METHODS)}"
				)

	for clause in ("where", "having"):
		if clause not in spec:
			continue
		if not isinstance(spec[clause], list):
			raise InvalidArgumentError(f"spec.{clause} must be a list")
		for i, p in enumerate(spec[clause]):
			if not isinstance(p, dict) or "op" not in p:
				raise InvalidArgumentError(
					f"spec.{clause}[{i}] must be a dict with 'op'"
				)
			if p["op"] not in _OPERATORS:
				raise InvalidArgumentError(
					f"spec.{clause}[{i}].op {p['op']!r} not allowed; "
					f"must be one of {sorted(_OPERATORS)}"
				)


def _collect_doctypes(spec: dict) -> list[str]:
	"""Return the list of DocTypes the spec references — FROM + joins.
	De-duplicated while preserving first-seen order so error messages
	read naturally to the operator."""
	out: list[str] = [spec["from"]]
	for j in spec.get("joins") or []:
		dt = j["doctype"]
		if dt not in out:
			out.append(dt)
	return out


# ---- Translation: spec → qb expressions -----------------------------


def _build_from_and_aliases(spec: dict) -> tuple[Any, dict]:
	"""Build the FROM table and seed the alias_map with the FROM entry.
	The alias_map maps spec-alias → (doctype, pypika.Table) so later
	stages can resolve ``"alias.field"`` references."""
	from_dt = spec["from"]
	alias = spec.get("alias") or from_dt
	# ``frappe.qb.DocType("Name")`` returns a pypika Table; ``.as_(alias)``
	# applies the alias. When the spec doesn't supply an alias we still
	# call ``.as_()`` so the doctype name + alias_map stay symmetric.
	table = frappe.qb.DocType(from_dt).as_(alias)
	alias_map = {alias: (from_dt, table)}
	return table, alias_map


def _resolve_field(field_ref: str, alias_map: dict, allow_alias: bool = False):
	"""Resolve a ``"alias.field"`` reference to a pypika Field.

	When ``allow_alias=True``, a bare name (no dot) is permitted and
	returned as a pypika ``Field`` without table qualification — this
	is the ORDER BY case where the operator may reference a SELECT
	alias like ``total_qty``."""
	if "." not in field_ref:
		if allow_alias:
			from pypika import Field
			return Field(field_ref)
		# A bare reference like "name" is ambiguous in a join; require
		# the alias prefix for clarity.
		if len(alias_map) == 1:
			# Single-doctype query — the alias is unambiguous; resolve
			# against the only table.
			((_, table),) = list(alias_map.values())
			return table[field_ref]
		raise InvalidArgumentError(
			f"field reference {field_ref!r} is ambiguous in a multi-table "
			f"query; prefix with the alias (e.g. 'si.name')"
		)
	alias, field = field_ref.split(".", 1)
	if alias not in alias_map:
		raise InvalidArgumentError(
			f"field reference {field_ref!r} uses unknown alias {alias!r}; "
			f"known aliases: {sorted(alias_map)}"
		)
	_, table = alias_map[alias]
	return table[field]


def _build_on_criterion(on_spec: dict, alias_map: dict) -> Criterion:
	"""Build the JOIN ON criterion from a dict of column-equalities.

	The ``on`` shape is ``{"sii.parent": "si.name"}`` — left key is a
	field reference, right value is either another field reference (for
	column-equality, the common case) or a literal value (for static
	conditions). We auto-detect: if the value resolves as a known
	alias.field, treat it as column-equality; otherwise as a literal.
	"""
	terms = []
	for lhs_ref, rhs_ref in on_spec.items():
		lhs = _resolve_field(lhs_ref, alias_map)
		# Treat as column-equality if rhs looks like alias.field with a
		# known alias. Otherwise it's a literal value.
		if (
			isinstance(rhs_ref, str)
			and "." in rhs_ref
			and rhs_ref.split(".", 1)[0] in alias_map
		):
			rhs = _resolve_field(rhs_ref, alias_map)
		else:
			rhs = rhs_ref
		terms.append(lhs == rhs)
	# Multiple ON conditions get AND-combined.
	out: Criterion = terms[0]
	for t in terms[1:]:
		out = out & t
	return out


def _build_select(select_spec: list, alias_map: dict) -> list:
	"""Translate the select list. Entries can be:
	- bare string ``"si.customer"`` → resolved field
	- dict ``{"agg": "sum", "field": "sii.qty", "as": "total_qty"}`` →
	  aggregate function wrapping the field, with ``.as_()`` aliased."""
	out = []
	for item in select_spec:
		if isinstance(item, str):
			out.append(_resolve_field(item, alias_map))
		elif isinstance(item, dict):
			agg_name = item.get("agg")
			if agg_name not in _AGGREGATES:
				raise InvalidArgumentError(
					f"select aggregate {agg_name!r} not allowed; "
					f"must be one of {sorted(_AGGREGATES)}"
				)
			field_ref = item.get("field")
			if agg_name == "count" and field_ref == "*":
				expr = fn.Count("*")
			elif field_ref:
				expr = _AGGREGATES[agg_name](_resolve_field(field_ref, alias_map))
			else:
				raise InvalidArgumentError(
					f"select aggregate {agg_name!r} missing 'field'"
				)
			if "as" in item:
				expr = expr.as_(item["as"])
			out.append(expr)
		else:
			raise InvalidArgumentError(
				f"select entry must be a string or dict; got {type(item).__name__}"
			)
	return out


def _build_predicate(p: dict, alias_map: dict) -> Criterion:
	"""Translate a WHERE/HAVING predicate dict to a pypika Criterion.

	Predicate shapes:

	- Plain field predicate::

	    {"field": "si.status", "op": "=", "value": "Submitted"}

	- Aggregate predicate (HAVING)::

	    {"agg": "sum", "field": "sii.qty", "op": ">", "value": 100}

	The aggregate variant wraps the field in the agg function; we
	support both shapes in WHERE and HAVING uniformly so the agent
	doesn't have to remember which clause permits which.
	"""
	op = p["op"]
	# Resolve the left side: either a bare field or an aggregate.
	if "agg" in p:
		agg_name = p["agg"]
		if agg_name not in _AGGREGATES:
			raise InvalidArgumentError(
				f"predicate aggregate {agg_name!r} not allowed; "
				f"must be one of {sorted(_AGGREGATES)}"
			)
		field_ref = p.get("field")
		if agg_name == "count" and field_ref == "*":
			lhs = fn.Count("*")
		elif field_ref:
			lhs = _AGGREGATES[agg_name](_resolve_field(field_ref, alias_map))
		else:
			raise InvalidArgumentError(
				f"predicate aggregate {agg_name!r} missing 'field'"
			)
	else:
		field_ref = p.get("field")
		if not field_ref:
			raise InvalidArgumentError(
				f"predicate missing 'field' or 'agg'/'field' pair"
			)
		lhs = _resolve_field(field_ref, alias_map)

	# Apply the operator. Each branch produces a Criterion.
	if op == "=":
		return lhs == p["value"]
	if op == "!=":
		return lhs != p["value"]
	if op == "<":
		return lhs < p["value"]
	if op == "<=":
		return lhs <= p["value"]
	if op == ">":
		return lhs > p["value"]
	if op == ">=":
		return lhs >= p["value"]
	if op == "in":
		values = p.get("value")
		if not isinstance(values, list):
			raise InvalidArgumentError(
				f"'in' operator requires a list value; got {type(values).__name__}"
			)
		return lhs.isin(values)
	if op == "not in":
		values = p.get("value")
		if not isinstance(values, list):
			raise InvalidArgumentError(
				f"'not in' operator requires a list value"
			)
		return lhs.notin(values)
	if op == "like":
		return lhs.like(p["value"])
	if op == "not like":
		return lhs.not_like(p["value"])
	if op == "is null":
		return lhs.isnull()
	if op == "is not null":
		return lhs.isnotnull()
	if op == "between":
		values = p.get("value")
		if not isinstance(values, list) or len(values) != 2:
			raise InvalidArgumentError(
				f"'between' operator requires a 2-element list value"
			)
		return lhs[slice(*values)]
	# Unreachable - _validate_spec_shape already restricts op to _OPERATORS.
	raise InvalidArgumentError(f"unsupported operator: {op}")
