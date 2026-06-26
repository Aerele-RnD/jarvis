"""Create a Frappe Dashboard Chart from a doctype's data.

Turns a "show me X over time / grouped by Y" request into a real, saved
Dashboard Chart the customer can pin to a dashboard - instead of dumping numbers
into chat. Supports the common shapes:

  - Count / Sum / Average over time   (a date field on the doctype)
  - Group By                          (count/sum/average per category)

Runs under the calling user: ``doc.insert()`` enforces create permission on
Dashboard Chart, and we check read permission on the charted doctype.
"""
import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError

_CHART_TYPES = {"Count", "Sum", "Average", "Group By"}
_RENDER_TYPES = {"Line", "Bar", "Percentage", "Pie", "Donut", "Heatmap"}
_TIMESPANS = {"Last Year", "Last Quarter", "Last Month", "Last Week", "Select Date Range"}
_INTERVALS = {"Yearly", "Quarterly", "Monthly", "Weekly", "Daily"}
_GROUP_TYPES = {"Count", "Sum", "Average"}


def create_dashboard_chart(
	chart_name: str,
	document_type: str,
	chart_type: str = "Count",
	type: str = "Bar",
	based_on: str | None = None,
	value_based_on: str | None = None,
	group_by_based_on: str | None = None,
	group_by_type: str = "Count",
	aggregate_function_based_on: str | None = None,
	number_of_groups: int = 0,
	timespan: str = "Last Year",
	time_interval: str = "Monthly",
	filters: dict | list | None = None,
	is_public: int = 0,
) -> dict:
	"""Create a Dashboard Chart; return {name, chart_name, chart_type, url}.

	``chart_type``: Count | Sum | Average (time series - need ``based_on`` date
	field; Sum/Average also need ``value_based_on`` numeric field) or ``Group
	By`` (need ``group_by_based_on``; Sum/Average ``group_by_type`` also needs
	``aggregate_function_based_on``). ``type`` is the render style. ``filters``
	is an optional Frappe filter dict/list scoping the charted records.
	"""
	if not chart_name:
		raise InvalidArgumentError("chart_name is required")
	if not document_type:
		raise InvalidArgumentError("document_type is required")
	if chart_type not in _CHART_TYPES:
		raise InvalidArgumentError(f"chart_type must be one of {sorted(_CHART_TYPES)}")
	if type not in _RENDER_TYPES:
		raise InvalidArgumentError(f"type must be one of {sorted(_RENDER_TYPES)}")
	if not frappe.has_permission(document_type, "read"):
		raise PermissionDeniedError(f"no read permission on {document_type!r}")

	doc = frappe.new_doc("Dashboard Chart")
	doc.chart_name = chart_name
	doc.chart_type = chart_type
	doc.document_type = document_type
	doc.type = type
	doc.is_public = 1 if is_public else 0
	doc.filters_json = frappe.as_json(filters if filters is not None else [])

	if chart_type in ("Count", "Sum", "Average"):
		if not based_on:
			raise InvalidArgumentError(f"{chart_type} charts need a date field in 'based_on'")
		if timespan not in _TIMESPANS:
			raise InvalidArgumentError(f"timespan must be one of {sorted(_TIMESPANS)}")
		if time_interval not in _INTERVALS:
			raise InvalidArgumentError(f"time_interval must be one of {sorted(_INTERVALS)}")
		doc.based_on = based_on
		doc.timeseries = 1
		doc.timespan = timespan
		doc.time_interval = time_interval
		if chart_type in ("Sum", "Average"):
			if not value_based_on:
				raise InvalidArgumentError(f"{chart_type} charts need a numeric field in 'value_based_on'")
			doc.value_based_on = value_based_on
	else:  # Group By
		if not group_by_based_on:
			raise InvalidArgumentError("Group By charts need a field in 'group_by_based_on'")
		if group_by_type not in _GROUP_TYPES:
			raise InvalidArgumentError(f"group_by_type must be one of {sorted(_GROUP_TYPES)}")
		doc.group_by_based_on = group_by_based_on
		doc.group_by_type = group_by_type
		if group_by_type in ("Sum", "Average"):
			if not aggregate_function_based_on:
				raise InvalidArgumentError(
					f"group_by_type {group_by_type} needs a numeric field in 'aggregate_function_based_on'"
				)
			doc.aggregate_function_based_on = aggregate_function_based_on
		if number_of_groups:
			doc.number_of_groups = int(number_of_groups)

	doc.insert()
	return {
		"name": doc.name,
		"chart_name": doc.chart_name,
		"chart_type": doc.chart_type,
		"url": f"/app/dashboard-chart/{doc.name}",
	}
