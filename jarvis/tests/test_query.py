"""Tests for jarvis.tools.query — the qb-based, permission-aware
replacement for run_query.

Test surface:

- Spec validation: required fields, alias collisions, unknown operators
- qb translation: spec → SQL substring assertions (one per construct)
- DocType-level read permission per referenced doctype
- Engine.get_permission_conditions woven into the WHERE
- DocType allowlist gate (shared Jarvis Settings field)
- Row guard + confirm_large escape hatch
- Happy path against the always-populated ``tabDocType`` table
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import (
	InvalidArgumentError,
	PermissionDeniedError,
	ResultTooLargeError,
)
from jarvis.tools.query import ROW_GUARD, query


class TestQuerySpecValidation(FrappeTestCase):
	"""Top-of-pipe shape checks. Fail before any DB call."""

	def test_rejects_non_dict_spec(self):
		with self.assertRaises(InvalidArgumentError):
			query("not a dict")
		with self.assertRaises(InvalidArgumentError):
			query(None)

	def test_rejects_missing_from(self):
		with self.assertRaises(InvalidArgumentError):
			query({"select": ["name"]})

	def test_rejects_non_string_from(self):
		with self.assertRaises(InvalidArgumentError):
			query({"from": 123})

	def test_rejects_non_list_joins(self):
		with self.assertRaises(InvalidArgumentError):
			query({"from": "DocType", "joins": "not a list"})

	def test_rejects_join_missing_required_fields(self):
		for missing in ("doctype", "alias", "on"):
			j = {"doctype": "User", "alias": "u",
				 "on": {"u.name": "dt.name"}}
			del j[missing]
			with self.assertRaises(InvalidArgumentError, msg=missing):
				query({"from": "DocType", "alias": "dt", "joins": [j]})

	def test_rejects_alias_collision(self):
		"""Two tables with the same alias would make field references
		ambiguous; the validator must catch it."""
		with self.assertRaises(InvalidArgumentError) as cm:
			query({
				"from": "DocType", "alias": "x",
				"joins": [{"doctype": "User", "alias": "x",
						   "on": {"x.name": "x.name"}}],
			})
		self.assertIn("collides", str(cm.exception))

	def test_rejects_invalid_join_type(self):
		with self.assertRaises(InvalidArgumentError):
			query({
				"from": "DocType",
				"joins": [{"doctype": "User", "alias": "u",
						   "type": "cross",  # not supported
						   "on": {"u.name": "DocType.name"}}],
			})

	def test_rejects_unknown_operator(self):
		with self.assertRaises(InvalidArgumentError) as cm:
			query({
				"from": "DocType",
				"where": [{"field": "name", "op": "REGEX", "value": ".*"}],
			})
		self.assertIn("not allowed", str(cm.exception))

	def test_rejects_invalid_limit(self):
		with patch("frappe.has_permission", return_value=True):
			with self.assertRaises(InvalidArgumentError):
				query({"from": "DocType", "limit": 0})
			with self.assertRaises(InvalidArgumentError):
				query({"from": "DocType", "limit": 10_000})


class TestQueryPermissions(FrappeTestCase):
	"""DocType-level read permission fires per referenced DocType
	BEFORE the query is built/executed - same gate run_query has."""

	def test_rejects_when_user_lacks_doctype_perm(self):
		with patch("frappe.has_permission", return_value=False):
			with self.assertRaises(PermissionDeniedError):
				query({"from": "Sales Invoice"})

	def test_checks_perm_on_every_referenced_doctype(self):
		"""A join across two DocTypes must check both. We let the real
		qb path run and patch only the perm check + the actual SQL
		execution - mocking the qb chain proved fragile."""
		checked = []

		def fake_has_perm(doctype, ptype="read", **_):
			checked.append(doctype)
			return True

		with patch("frappe.has_permission", side_effect=fake_has_perm), \
		     patch("frappe.database.query.Engine") as fake_engine, \
		     patch("pypika.queries.QueryBuilder.run", return_value=[]):
			fake_engine.return_value.get_permission_conditions.return_value = None
			query({
				"from": "Sales Invoice", "alias": "si",
				"joins": [{
					"type": "left",
					"doctype": "Sales Invoice Item",
					"alias": "sii",
					"on": {"sii.parent": "si.name"},
				}],
				"select": ["si.name"],
			})

		self.assertIn("Sales Invoice", checked)
		self.assertIn("Sales Invoice Item", checked)


class TestQueryDocTypeAllowlist(FrappeTestCase):
	"""Same per-site allowlist field that gates run_query also gates
	query. One operator knob controls both tools."""

	def setUp(self):
		# Reset allowlist before each test.
		settings = frappe.get_single("Jarvis Settings")
		settings.run_query_doctype_allowlist = ""
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.clear_document_cache("Jarvis Settings")

	def tearDown(self):
		settings = frappe.get_single("Jarvis Settings")
		settings.run_query_doctype_allowlist = ""
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.clear_document_cache("Jarvis Settings")

	def test_doctype_off_allowlist_is_rejected(self):
		settings = frappe.get_single("Jarvis Settings")
		settings.run_query_doctype_allowlist = "Customer\nSales Invoice"
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.clear_document_cache("Jarvis Settings")

		with patch("frappe.has_permission", return_value=True):
			with self.assertRaises(PermissionDeniedError) as cm:
				query({"from": "DocType"})
			self.assertIn("allowlist", str(cm.exception))

	def test_empty_allowlist_imposes_no_extra_restriction(self):
		"""Default state - allowlist is empty/unset, no extra gate."""
		with patch("frappe.has_permission", return_value=True), \
		     patch("frappe.database.query.Engine") as fake_engine:
			fake_engine.return_value.get_permission_conditions.return_value = None
			result = query({"from": "DocType", "limit": 1})
		self.assertIn("rows", result)


class TestQueryQbTranslation(FrappeTestCase):
	"""Spec → SQL substring assertions. We don't execute - we patch the
	qb run/get_sql calls and check the SQL string produced by qb."""

	def _build_sql(self, spec: dict) -> str:
		"""Helper: build the query through the full pipeline, capture
		the qb expression's resolved SQL via .get_sql()."""
		with patch("frappe.has_permission", return_value=True), \
		     patch("frappe.database.query.Engine") as fake_engine:
			fake_engine.return_value.get_permission_conditions.return_value = None
			# We let the real qb run; patch only the actual SQL exec.
			with patch("pypika.queries.QueryBuilder.run", return_value=[]) as _:
				result = query(spec)
		return result["sql"]

	def test_basic_select_from(self):
		sql = self._build_sql({"from": "DocType", "select": ["name"]})
		# qb backticks the table name in MariaDB / quotes it in Postgres.
		self.assertIn("DocType", sql)
		self.assertIn("name", sql.lower())

	def test_select_aggregate(self):
		sql = self._build_sql({
			"from": "DocType", "alias": "dt",
			"select": [{"agg": "count", "field": "*", "as": "n"}],
		})
		self.assertIn("COUNT", sql.upper())
		self.assertIn("n", sql)  # the alias appears

	def test_where_equality(self):
		sql = self._build_sql({
			"from": "DocType", "alias": "dt",
			"select": ["dt.name"],
			"where": [{"field": "dt.issingle", "op": "=", "value": 0}],
		})
		self.assertIn("issingle", sql)

	def test_where_in(self):
		sql = self._build_sql({
			"from": "DocType", "alias": "dt",
			"select": ["dt.name"],
			"where": [{"field": "dt.module", "op": "in",
					   "value": ["Core", "Custom"]}],
		})
		self.assertIn("IN", sql.upper())

	def test_order_by(self):
		sql = self._build_sql({
			"from": "DocType", "alias": "dt",
			"select": ["dt.name"],
			"order_by": [{"field": "dt.name", "dir": "desc"}],
		})
		self.assertIn("ORDER BY", sql.upper())
		self.assertIn("DESC", sql.upper())

	def test_group_by(self):
		sql = self._build_sql({
			"from": "DocType", "alias": "dt",
			"select": ["dt.module",
					   {"agg": "count", "field": "*", "as": "n"}],
			"group_by": ["dt.module"],
		})
		self.assertIn("GROUP BY", sql.upper())

	def test_limit(self):
		sql = self._build_sql({"from": "DocType", "limit": 42})
		self.assertIn("LIMIT 42", sql.upper())

	def test_in_with_list_value_required(self):
		"""'in' operator demands a list, not a scalar."""
		with patch("frappe.has_permission", return_value=True):
			with self.assertRaises(InvalidArgumentError):
				query({
					"from": "DocType",
					"where": [{"field": "module", "op": "in",
							   "value": "Core"}],  # should be list
				})

	def test_between_demands_two_element_list(self):
		with patch("frappe.has_permission", return_value=True):
			with self.assertRaises(InvalidArgumentError):
				query({
					"from": "DocType",
					"where": [{"field": "name", "op": "between",
							   "value": ["a"]}],  # one element
				})


class TestQueryPermissionConditionsWoven(FrappeTestCase):
	"""The critical test: Engine.get_permission_conditions returns
	a Criterion; query() must AND it into the WHERE."""

	def test_permission_condition_appears_in_sql(self):
		"""Patch Engine to return a recognisable criterion; assert the
		predicate appears in the resolved SQL."""
		from pypika import Field
		# A literal-equality criterion: ``modified = 'sentinel-marker'``.
		# Easy to spot in the produced SQL.
		sentinel = Field("modified") == "sentinel-marker"

		with patch("frappe.has_permission", return_value=True), \
		     patch("frappe.database.query.Engine") as fake_engine:
			fake_engine.return_value.get_permission_conditions.return_value = sentinel
			with patch("pypika.queries.QueryBuilder.run", return_value=[]):
				result = query({"from": "DocType", "select": ["name"]})

		self.assertIn("sentinel-marker", result["sql"])

	def test_none_from_engine_is_skipped(self):
		"""When the user has no restrictions, Engine returns None - we
		must not append anything to the WHERE."""
		with patch("frappe.has_permission", return_value=True), \
		     patch("frappe.database.query.Engine") as fake_engine:
			fake_engine.return_value.get_permission_conditions.return_value = None
			with patch("pypika.queries.QueryBuilder.run", return_value=[]):
				result = query({"from": "DocType", "select": ["name"]})

		# No WHERE clause should appear when nothing constrains the query.
		# (qb only renders WHERE when at least one where() was called.)
		self.assertNotIn("WHERE", result["sql"].upper())


class TestQueryRowGuard(FrappeTestCase):
	"""Row guard fires when result exceeds ``ROW_GUARD`` and the
	caller didn't opt in via ``confirm_large``."""

	def test_guard_fires_above_threshold(self):
		with patch("frappe.has_permission", return_value=True), \
		     patch("frappe.database.query.Engine") as fake_engine:
			fake_engine.return_value.get_permission_conditions.return_value = None
			# tabDocType has hundreds of rows on every Frappe site - a
			# reliable fixture for the row-guard test.
			with self.assertRaises(ResultTooLargeError) as cm:
				query({"from": "DocType", "limit": ROW_GUARD + 50})
			self.assertEqual(cm.exception.tool, "query")
			self.assertGreater(cm.exception.row_count, ROW_GUARD)

	def test_guard_silent_under_threshold(self):
		with patch("frappe.has_permission", return_value=True), \
		     patch("frappe.database.query.Engine") as fake_engine:
			fake_engine.return_value.get_permission_conditions.return_value = None
			result = query({"from": "DocType", "limit": ROW_GUARD - 50})
		self.assertLessEqual(len(result["rows"]), ROW_GUARD - 50)

	def test_guard_opt_in_bypasses(self):
		with patch("frappe.has_permission", return_value=True), \
		     patch("frappe.database.query.Engine") as fake_engine:
			fake_engine.return_value.get_permission_conditions.return_value = None
			result = query(
				{"from": "DocType", "limit": ROW_GUARD + 50},
				confirm_large=True,
			)
		self.assertGreater(len(result["rows"]), ROW_GUARD)


class TestQueryHappyPath(FrappeTestCase):
	"""End-to-end against the real DB. Uses ``tabDocType`` which
	always exists and which the test fixture user has read on
	(System Manager)."""

	def test_returns_rows_and_resolved_sql(self):
		result = query({
			"from": "DocType", "alias": "dt",
			"select": ["dt.name"],
			"where": [{"field": "dt.issingle", "op": "=", "value": 1}],
			"order_by": [{"field": "dt.name", "dir": "asc"}],
			"limit": 5,
		})
		self.assertIn("sql", result)
		self.assertIn("rows", result)
		self.assertGreater(len(result["rows"]), 0)
		self.assertIn("name", result["rows"][0])

	def test_aggregate_with_group_by(self):
		"""Real aggregate query: count DocTypes per module."""
		result = query({
			"from": "DocType", "alias": "dt",
			"select": ["dt.module",
					   {"agg": "count", "field": "*", "as": "n"}],
			"group_by": ["dt.module"],
			"order_by": [{"field": "n", "dir": "desc"}],
			"limit": 5,
		})
		self.assertGreater(len(result["rows"]), 0)
		self.assertIn("module", result["rows"][0])
		self.assertIn("n", result["rows"][0])
		self.assertGreater(result["rows"][0]["n"], 0)
