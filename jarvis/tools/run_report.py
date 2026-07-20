import frappe
from frappe.desk.query_report import run as frappe_run_report

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError


def run_report(report_name: str, filters: dict | None = None) -> dict:
	"""Execute a saved Frappe Report by name.

	Frappe enforces report-level permissions internally and raises frappe.PermissionError
	on denial; we translate that to PermissionDeniedError so all tools share one
	exception contract. Returns a dict with `columns` and `result` keys.
	"""
	if not report_name:
		raise InvalidArgumentError("report_name is required")

	if not frappe.db.exists("Report", report_name):
		raise InvalidArgumentError(f"unknown Report: {report_name}")

	try:
		return frappe_run_report(report_name=report_name, filters=filters or {})
	except frappe.PermissionError as e:
		raise PermissionDeniedError(str(e) or f"no permission to run report {report_name}") from e
