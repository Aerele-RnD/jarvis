"""Tests for jarvis.tools.run_query - read-only SQL with safety bounds."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.run_query import run_query


class TestRunQueryValidation(FrappeTestCase):
	"""The defensive validation layer - failures should never reach
	``frappe.db.sql``. Each test asserts on the *type* of rejection, not the
	wording of the message, so the error copy can evolve.
	"""

	def test_rejects_empty_query(self):
		with self.assertRaises(InvalidArgumentError):
			run_query(query="")
		with self.assertRaises(InvalidArgumentError):
			run_query(query="   ")

	def test_rejects_invalid_limit(self):
		with self.assertRaises(InvalidArgumentError):
			run_query("SELECT 1 FROM tabDocType", limit=0)
		with self.assertRaises(InvalidArgumentError):
			run_query("SELECT 1 FROM tabDocType", limit=10_000)

	def test_rejects_non_select(self):
		for q in [
			"INSERT INTO tabDocType (name) VALUES ('x')",
			"UPDATE tabDocType SET name='x'",
			"DELETE FROM tabDocType",
			"DROP TABLE tabDocType",
		]:
			with self.assertRaises(InvalidArgumentError, msg=f"should reject: {q}"):
				run_query(q)

	def test_rejects_multi_statement(self):
		with self.assertRaises(InvalidArgumentError):
			run_query("SELECT 1 FROM tabDocType; SELECT 2 FROM tabDocType")

	def test_rejects_comments(self):
		for q in [
			"SELECT name FROM tabDocType -- comment",
			"SELECT name /* foo */ FROM tabDocType",
			"SELECT name FROM tabDocType # mysql comment",
		]:
			with self.assertRaises(InvalidArgumentError, msg=f"should reject: {q}"):
				run_query(q)

	def test_rejects_dml_inside_select(self):
		"""A SELECT with an embedded INSERT in a subquery must still fail."""
		with self.assertRaises(InvalidArgumentError):
			run_query(
				"SELECT name FROM tabDocType WHERE name IN "
				"(INSERT INTO tabFoo VALUES (1))"
			)

	def test_rejects_non_tab_tables(self):
		"""Frappe internal tables (__Auth, sequence stores) must be off-limits."""
		with self.assertRaises(InvalidArgumentError):
			run_query("SELECT name FROM __Auth")
		with self.assertRaises(InvalidArgumentError):
			run_query("SELECT * FROM information_schema.tables")

	def test_rejects_query_with_no_tables(self):
		with self.assertRaises(InvalidArgumentError):
			run_query("SELECT 1")

	# ----- Sprint-1 (2026-06-16) bypass surfaces ---------------------

	def test_rejects_into_outfile(self):
		"""SELECT ... INTO OUTFILE writes the result set to the MariaDB
		server's filesystem. With FILE privilege, an attacker could exfil
		whatever the bench's DB user can read into a path they later
		fetch via another route."""
		with self.assertRaises(InvalidArgumentError) as cm:
			run_query("SELECT name FROM tabDocType INTO OUTFILE '/tmp/leak.txt'")
		self.assertIn("INTO", str(cm.exception).upper())

	def test_rejects_into_dumpfile(self):
		with self.assertRaises(InvalidArgumentError):
			run_query("SELECT name FROM tabDocType INTO DUMPFILE '/tmp/leak'")

	def test_rejects_load_file(self):
		"""LOAD_FILE('/etc/passwd') AS x - filesystem read in a column."""
		with self.assertRaises(InvalidArgumentError) as cm:
			run_query("SELECT LOAD_FILE('/etc/passwd') AS x FROM tabDocType")
		self.assertIn("LOAD_FILE", str(cm.exception))

	def test_rejects_sleep(self):
		"""SLEEP(N) ties up a connection for N seconds; a few concurrent
		calls saturate the Frappe DB pool."""
		with self.assertRaises(InvalidArgumentError) as cm:
			run_query("SELECT name FROM tabDocType WHERE SLEEP(10)")
		self.assertIn("SLEEP", str(cm.exception))

	def test_rejects_benchmark(self):
		"""BENCHMARK(1e9, MD5('x')) - the family that SLEEP belongs to."""
		with self.assertRaises(InvalidArgumentError):
			run_query("SELECT BENCHMARK(1000000, MD5('x')) FROM tabDocType")

	def test_rejects_get_lock(self):
		"""GET_LOCK('jarvis-test', 0) holds a server-side named lock; a
		conspiracy of stuck connections is a coordination DoS."""
		with self.assertRaises(InvalidArgumentError) as cm:
			run_query("SELECT GET_LOCK('x', 0) FROM tabDocType")
		self.assertIn("GET_LOCK", str(cm.exception))

	def test_rejects_release_lock(self):
		with self.assertRaises(InvalidArgumentError):
			run_query("SELECT RELEASE_LOCK('x') FROM tabDocType")

	def test_rejects_comma_from_to_information_schema(self):
		"""The leading-FROM regex catches the FIRST table after FROM, but
		comma-continuations slip past: ``FROM tabDocType, information_schema.tables t``
		grants access to internal schemas the agent has no business reading.
		"""
		with self.assertRaises(InvalidArgumentError) as cm:
			run_query(
				"SELECT name FROM tabDocType, information_schema.tables t WHERE 1=1"
			)
		self.assertIn("information_schema", str(cm.exception))

	def test_rejects_backticked_information_schema(self):
		with self.assertRaises(InvalidArgumentError):
			run_query(
				"SELECT name FROM tabDocType, `information_schema`.tables t WHERE 1=1"
			)

	def test_rejects_mysql_user_table(self):
		"""``mysql.user`` carries password hashes. Same comma-FROM family."""
		with self.assertRaises(InvalidArgumentError) as cm:
			run_query("SELECT * FROM tabDocType, mysql.user u WHERE 1=1")
		self.assertIn("mysql", str(cm.exception))

	def test_rejects_comma_from_to_non_tab_table(self):
		"""Even if the second table isn't in a forbidden schema, it must
		still start with ``tab`` - the second comma slot was previously
		unchecked."""
		with self.assertRaises(InvalidArgumentError) as cm:
			run_query("SELECT name FROM tabDocType, __Auth a WHERE 1=1")
		# Error message should call out the bad identifier.
		self.assertIn("__Auth", str(cm.exception))

	def test_load_file_false_positive_when_used_as_column_name(self):
		"""``load_file`` substring inside another identifier must NOT
		trigger the function reject (word-boundary check)."""
		# A column named ``upload_filename`` happens to contain "load_file";
		# the function reject must use a word-boundary + open-paren so this
		# benign case passes the function check. We don't actually run it
		# (no such column / DocType), so we expect the table-not-found-flow
		# error path, NOT an InvalidArgumentError about LOAD_FILE.
		with patch("frappe.has_permission", return_value=True), \
		     patch("jarvis.tools.run_query.frappe.db.sql",
		           return_value=[{"upload_filename": "x"}]):
			result = run_query(
				"SELECT upload_filename FROM tabDocType LIMIT 1"
			)
		self.assertTrue("rows" in result, msg=result)


class TestRunQueryPermissions(FrappeTestCase):
	"""DocType-level read permission is the only line of defense we provide.
	Verify the gate is per-DocType and fires before frappe.db.sql runs.
	"""

	def test_rejects_when_user_lacks_doctype_perm(self):
		with patch("frappe.has_permission", return_value=False):
			with self.assertRaises(PermissionDeniedError):
				run_query("SELECT name FROM tabSales Invoice")

	def test_checks_perm_on_every_referenced_doctype(self):
		"""A JOIN across two DocTypes must check both."""
		checked = []

		def fake_has_perm(doctype, ptype="read", **_):
			checked.append(doctype)
			return True

		with patch("frappe.has_permission", side_effect=fake_has_perm):
			# Patch sql so we don't actually execute the SELECT - only care
			# about the perm-check side effect.
			with patch("frappe.db.sql", return_value=[]):
				run_query(
					"SELECT si.name FROM `tabSales Invoice` AS si "
					"JOIN `tabSales Invoice Item` AS sii ON sii.parent = si.name"
				)

		self.assertIn("Sales Invoice", checked)
		self.assertIn("Sales Invoice Item", checked)


class TestRunQueryLimitInjection(FrappeTestCase):
	"""LIMIT is the only bound on result size - it must always be present
	and never exceed the cap. Test the rewriter, not the SQL execution.
	"""

	def test_injects_limit_when_missing(self):
		captured = {}

		def fake_sql(q, **_):
			captured["sql"] = q
			return []

		with patch("frappe.has_permission", return_value=True):
			with patch("frappe.db.sql", side_effect=fake_sql):
				run_query("SELECT name FROM tabDocType", limit=50)

		self.assertIn("LIMIT 50", captured["sql"].upper())

	def test_clamps_existing_limit(self):
		captured = {}

		def fake_sql(q, **_):
			captured["sql"] = q
			return []

		with patch("frappe.has_permission", return_value=True):
			with patch("frappe.db.sql", side_effect=fake_sql):
				run_query("SELECT name FROM tabDocType LIMIT 9999", limit=25)

		self.assertIn("LIMIT 25", captured["sql"])
		self.assertNotIn("9999", captured["sql"])

	def test_preserves_offset_in_limit(self):
		captured = {}

		def fake_sql(q, **_):
			captured["sql"] = q
			return []

		with patch("frappe.has_permission", return_value=True):
			with patch("frappe.db.sql", side_effect=fake_sql):
				run_query("SELECT name FROM tabDocType LIMIT 100, 9999", limit=25)

		self.assertIn("LIMIT 100, 25", captured["sql"])


class TestRunQueryHappyPath(FrappeTestCase):
	"""End-to-end against the real DB. Uses ``tabDocType`` which always
	exists and which the test fixture user has read on (System Manager).
	"""

	def test_returns_rows_and_executed_sql(self):
		result = run_query("SELECT name FROM tabDocType ORDER BY name", limit=5)
		self.assertIn("sql", result)
		self.assertIn("rows", result)
		self.assertIn("LIMIT 5", result["sql"].upper())
		self.assertGreater(len(result["rows"]), 0)
		self.assertIn("name", result["rows"][0])

	def test_backtick_table_names_work(self):
		result = run_query(
			"SELECT name FROM `tabDocType` WHERE issingle = 1 ORDER BY name",
			limit=3,
		)
		self.assertGreater(len(result["rows"]), 0)

	def test_rejects_query_returning_unnamed_columns(self):
		# Without a column alias on the count() expression, frappe.db.sql
		# returns the column under a generated name - we accept that.
		# This test is here as documentation: as_dict=True does give us
		# names back, so the validation in the code is defensive only.
		result = run_query("SELECT COUNT(*) AS n FROM tabDocType", limit=1)
		self.assertEqual(len(result["rows"]), 1)
		self.assertIn("n", result["rows"][0])
