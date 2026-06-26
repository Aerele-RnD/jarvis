"""Tests for the sandboxed run_python_code tool, incl. adversarial escape attempts.

The sandbox is off by default (site_config jarvis_python_sandbox); these enable
it on frappe.conf for the duration of the test only.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.run_python_code import run_python_code


class TestRunPythonCodeGate(FrappeTestCase):
	def test_disabled_by_default(self):
		orig = frappe.conf.get("jarvis_python_sandbox")
		frappe.conf["jarvis_python_sandbox"] = False
		try:
			with self.assertRaises(PermissionDeniedError):
				run_python_code("result = 1")
		finally:
			frappe.conf["jarvis_python_sandbox"] = orig


class TestRunPythonCodeSandbox(FrappeTestCase):
	def setUp(self):
		self._orig = frappe.conf.get("jarvis_python_sandbox")
		frappe.conf["jarvis_python_sandbox"] = True

	def tearDown(self):
		frappe.conf["jarvis_python_sandbox"] = self._orig

	# --- happy paths --------------------------------------------------------
	def test_pandas_groupby(self):
		try:
			import pandas  # noqa: F401
		except ImportError:
			self.skipTest("pandas not installed in the bench env")
		out = run_python_code(
			"import pandas as pd\nresult = pd.DataFrame(data).groupby('g')['v'].sum().to_dict()",
			data=[{"g": "a", "v": 1}, {"g": "a", "v": 2}, {"g": "b", "v": 5}],
		)
		self.assertTrue(out["ok"], out)
		self.assertEqual(out["result"], {"a": 3, "b": 5})

	def test_result_and_stdout(self):
		out = run_python_code("print('hi')\nresult = sum(data)", data=[1, 2, 3])
		self.assertTrue(out["ok"], out)
		self.assertEqual(out["result"], 6)
		self.assertIn("hi", out["stdout"])

	# --- adversarial: blocked imports / builtins ----------------------------
	def test_blocks_os(self):
		out = run_python_code("import os\nresult = os.getcwd()")
		self.assertFalse(out["ok"])
		self.assertIn("blocked", out["error"].lower())

	def test_blocks_socket(self):
		out = run_python_code("import socket\nresult = 1")
		self.assertFalse(out["ok"])
		self.assertIn("blocked", out["error"].lower())

	def test_blocks_subprocess(self):
		out = run_python_code("import subprocess\nresult = 1")
		self.assertFalse(out["ok"])

	def test_blocks_frappe(self):
		out = run_python_code("import frappe\nresult = 1")
		self.assertFalse(out["ok"])
		self.assertIn("blocked", out["error"].lower())

	def test_open_is_unavailable(self):
		out = run_python_code("result = open('/etc/passwd').read()")
		self.assertFalse(out["ok"])  # open removed from builtins -> NameError

	def test_eval_is_unavailable(self):
		out = run_python_code("result = eval('1+1')")
		self.assertFalse(out["ok"])

	# --- resource limits ----------------------------------------------------
	def test_infinite_loop_times_out(self):
		with self.assertRaises(InvalidArgumentError):
			run_python_code("while True:\n    pass", timeout=2)

	# --- input validation ---------------------------------------------------
	def test_empty_code_rejected(self):
		with self.assertRaises(InvalidArgumentError):
			run_python_code("")
