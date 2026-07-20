import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.run_report import run_report


class TestRunReport(FrappeTestCase):
	def test_runs_known_report(self):
		company = frappe.defaults.get_global_default("company")
		if not company:
			self.skipTest("test bench has no default company; happy-path covered in E2E task")
		result = run_report(
			report_name="Sales Register",
			filters={"from_date": "2020-01-01", "to_date": "2020-01-02", "company": company},
		)
		self.assertIn("columns", result)
		self.assertIn("result", result)

	def test_rejects_unknown_report(self):
		with self.assertRaises(InvalidArgumentError):
			run_report(report_name="Definitely Not A Report")

	def test_rejects_missing_report_name(self):
		with self.assertRaises(InvalidArgumentError):
			run_report(report_name="")

	def test_permission_check_blocks_unauthorized_user(self):
		user_email = "reportless@example.com"
		if not frappe.db.exists("User", user_email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": user_email,
					"first_name": "Reportless",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		frappe.set_user(user_email)
		try:
			with self.assertRaises(PermissionDeniedError):
				run_report(report_name="Sales Register")
		finally:
			frappe.set_user("Administrator")
