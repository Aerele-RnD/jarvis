"""Unit tests for jarvis.site_profile.render (pure-Python, no DB)."""

import unittest

try:
	from jarvis.site_profile.render import (
		DEFAULT_BUDGET,
		EMPTY_MESSAGE,
		apply_scope_match,
		render_profile_md,
	)
except ImportError:  # pragma: no cover - fallback when `jarvis` (frappe app) won't import
	import importlib.util
	import pathlib

	_path = pathlib.Path(__file__).resolve().parents[1] / "site_profile" / "render.py"
	_spec = importlib.util.spec_from_file_location("jarvis_site_profile_render", _path)
	_module = importlib.util.module_from_spec(_spec)
	_spec.loader.exec_module(_module)
	DEFAULT_BUDGET = _module.DEFAULT_BUDGET
	EMPTY_MESSAGE = _module.EMPTY_MESSAGE
	apply_scope_match = _module.apply_scope_match
	render_profile_md = _module.render_profile_md


def _mk(
	n_doctypes,
	n_modules=3,
	n_apps=1,
	include_workflows=True,
	include_core=True,
	include_reports=True,
	include_print_formats=True,
	include_scripts=True,
	extra_keys=False,
	long_module_names=False,
):
	"""Fabricate a realistic site-profile dict: ``n_doctypes`` custom doctypes
	spread round-robin across ``n_modules`` modules owned by ``n_apps`` apps.
	``extra_keys`` plants forbidden content under unread keys on every item
	type; ``long_module_names`` pads module names for the shed-ladder tests."""
	apps = [f"custom_app_{i}" for i in range(n_apps)]
	modules = {}
	module_names = []
	for i in range(n_modules):
		name = f"Module{i:04d}"
		if long_module_names:
			name += "_" + "x" * 60
		module_names.append(name)
		modules[name] = apps[i % n_apps]

	doctypes = []
	for i in range(n_doctypes):
		mod = module_names[i % n_modules] if n_modules else None
		d = {
			"name": f"Custom Doctype {i:04d}",
			"module": mod,
			"istable": 1 if i % 5 == 0 else 0,
			"issingle": 0,
			"is_submittable": 1 if i % 3 == 0 else 0,
		}
		if extra_keys:
			d["options"] = "Gold\nBlacklisted"
			d["description"] = "SECRET-BIZ-FACT"
		doctypes.append(d)
	doctypes.sort(key=lambda d: d["name"])

	workflows = []
	if include_workflows and doctypes:
		wf = {
			"name": "Vehicle Approval",
			"doctype": doctypes[0]["name"],
			"states": ["Draft", "Verified", "Approved"],
		}
		if extra_keys:
			wf["description"] = "SECRET-BIZ-FACT"
		workflows.append(wf)

	core_customizations = []
	if include_core:
		cc = {
			"doctype": "Sales Invoice",
			"custom_field_count": 9,
			"notable_fields": ["vehicle", "route_code"],
			"property_setter_count": 4,
		}
		if extra_keys:
			cc["options"] = "Gold\nBlacklisted"
		core_customizations.append(cc)

	reports = []
	if include_reports:
		rep = {"name": "Monthly Fuel Consumption", "doctype": "Fuel Entry", "report_type": "Script Report"}
		if extra_keys:
			rep["description"] = "SECRET-BIZ-FACT"
		reports.append(rep)

	print_formats = []
	if include_print_formats:
		pf = {"name": "Fleet Tax Invoice", "doctype": "Sales Invoice"}
		if extra_keys:
			pf["options"] = "Gold\nBlacklisted"
		print_formats.append(pf)

	scripts = {"server": {}, "client": {}}
	if include_scripts and doctypes:
		scripts = {"server": {doctypes[0]["name"]: 2, "": 1}, "client": {"Sales Invoice": 1}}

	return {
		"apps": apps,
		"modules": modules,
		"custom_doctypes": doctypes,
		"core_customizations": core_customizations,
		"workflows": workflows,
		"reports": reports,
		"print_formats": print_formats,
		"scripts": scripts,
	}


_EMPTY_DATA = {
	"apps": [],
	"modules": {},
	"custom_doctypes": [],
	"core_customizations": [],
	"workflows": [],
	"reports": [],
	"print_formats": [],
	"scripts": {"server": {}, "client": {}},
}

# The example dict from the site_profile input contract, reused verbatim for the
# scope/match tests so the fixture stays traceable to the spec.
_SPEC_DATA = {
	"apps": ["fleet_mgmt"],
	"modules": {"Fleet": "fleet_mgmt"},
	"custom_doctypes": [
		{"name": "Vehicle Log", "module": "Fleet", "istable": 0, "issingle": 0, "is_submittable": 1},
	],
	"core_customizations": [
		{
			"doctype": "Sales Invoice",
			"custom_field_count": 9,
			"notable_fields": ["vehicle", "route_code"],
			"property_setter_count": 4,
		},
	],
	"workflows": [
		{"name": "Vehicle Approval", "doctype": "Vehicle Log", "states": ["Draft", "Verified", "Approved"]},
	],
	"reports": [
		{"name": "Monthly Fuel Consumption", "doctype": "Fuel Entry", "report_type": "Script Report"},
	],
	"print_formats": [{"name": "Fleet Tax Invoice", "doctype": "Sales Invoice"}],
	"scripts": {"server": {"Vehicle Log": 2, "": 1}, "client": {"Sales Invoice": 1}},
}


class TestSiteProfileRender(unittest.TestCase):
	def test_realistic_thirty_doctypes_renders_tier_zero(self):
		data = _mk(30, n_modules=5)
		doc = render_profile_md(data)
		self.assertLessEqual(len(doc), DEFAULT_BUDGET)
		# First doctype is submittable, a child table, and carries the workflow.
		self.assertIn("- Custom Doctype 0000 - submittable, child table, workflow: Vehicle Approval", doc)
		self.assertIn("(notable: vehicle, route_code)", doc)
		self.assertIn("Monthly Fuel Consumption", doc)

	def test_150_doctypes_budget_4000_sheds_to_fit(self):
		data = _mk(150, n_modules=8)
		doc = render_profile_md(data, budget=4000)
		self.assertLessEqual(len(doc), 4000)
		self.assertIn("## How to go deeper", doc)
		self.assertIn("## Custom DocTypes", doc)

	def test_400_doctypes_budget_2000_hits_floor_tier(self):
		data = _mk(400, n_modules=6)
		doc = render_profile_md(data, budget=2000)
		self.assertLessEqual(len(doc), 2000)
		self.assertIn("## How to go deeper", doc)
		# No individual doctype line survives at the floor - only module rollups.
		self.assertNotIn("Custom Doctype 0000", doc)
		self.assertIn("doctypes", doc)

	def test_pathological_300_modules_truncates_with_more_modules_marker(self):
		data = _mk(
			300,
			n_modules=300,
			long_module_names=True,
			include_workflows=False,
			include_core=False,
			include_reports=False,
			include_print_formats=False,
			include_scripts=False,
		)
		doc = render_profile_md(data, budget=1500)
		self.assertLessEqual(len(doc), 1500)
		self.assertIn("more modules", doc)
		self.assertIn("## How to go deeper", doc)

	def test_empty_input_returns_empty_message(self):
		self.assertEqual(render_profile_md(_EMPTY_DATA), EMPTY_MESSAGE)

	def test_custom_empty_message_honored(self):
		custom = "Nothing custom on this site."
		self.assertEqual(render_profile_md(_EMPTY_DATA, empty_message=custom), custom)

	def test_planted_forbidden_content_never_reaches_output(self):
		data = _mk(30, n_modules=5, extra_keys=True)
		tier_zero = render_profile_md(data)
		self.assertNotIn("Blacklisted", tier_zero)
		self.assertNotIn("SECRET-BIZ-FACT", tier_zero)

		floor = render_profile_md(data, budget=1200)
		self.assertNotIn("Blacklisted", floor)
		self.assertNotIn("SECRET-BIZ-FACT", floor)

	def test_recipe_survives_at_every_tier(self):
		data = _mk(200, n_modules=6)
		for budget in (30000, 4000, 2000, 1200):
			with self.subTest(budget=budget):
				doc = render_profile_md(data, budget=budget)
				self.assertIn("## How to go deeper", doc)
				self.assertIn("jarvis__get_schema('<DocType>')", doc)

	def test_apply_scope_match_custom_fields_scope_keeps_only_core_customizations(self):
		out = apply_scope_match(_SPEC_DATA, {"custom_fields"}, None)
		self.assertEqual(out["core_customizations"], _SPEC_DATA["core_customizations"])
		self.assertEqual(out["custom_doctypes"], [])
		self.assertEqual(out["workflows"], [])
		self.assertEqual(out["reports"], [])
		self.assertEqual(out["print_formats"], [])
		self.assertEqual(out["scripts"], {"server": {}, "client": {}})
		self.assertEqual(out["apps"], [])
		self.assertEqual(out["modules"], {})

	def test_apply_scope_match_none_scope_keeps_everything(self):
		out = apply_scope_match(_SPEC_DATA, None, None)
		for key in _SPEC_DATA:
			self.assertEqual(out[key], _SPEC_DATA[key])

	def test_apply_scope_match_invoice_keeps_matches_and_drops_others(self):
		out = apply_scope_match(_SPEC_DATA, None, "invoice")
		self.assertEqual(out["core_customizations"], _SPEC_DATA["core_customizations"])
		self.assertEqual(out["print_formats"], _SPEC_DATA["print_formats"])
		self.assertEqual(out["scripts"], {"server": {}, "client": {"Sales Invoice": 1}})
		self.assertEqual(out["custom_doctypes"], [])
		self.assertEqual(out["workflows"], [])
		self.assertEqual(out["reports"], [])
		self.assertEqual(out["apps"], [])

	def test_apply_scope_match_no_hits_empties_everything(self):
		out = apply_scope_match(_SPEC_DATA, None, "zzz-nonexistent")
		self.assertEqual(render_profile_md(out), EMPTY_MESSAGE)

	def test_workflow_annotation_only_on_matching_doctype_line(self):
		data = {
			"apps": ["fleet_mgmt"],
			"modules": {"Fleet": "fleet_mgmt"},
			"custom_doctypes": [
				{"name": "Trip Sheet", "module": "Fleet", "istable": 0, "issingle": 0, "is_submittable": 0},
				{"name": "Vehicle Log", "module": "Fleet", "istable": 0, "issingle": 0, "is_submittable": 0},
			],
			"core_customizations": [],
			"workflows": [
				{"name": "Vehicle Approval", "doctype": "Vehicle Log", "states": ["Draft", "Verified", "Approved"]},
			],
			"reports": [],
			"print_formats": [],
			"scripts": {"server": {}, "client": {}},
		}
		doc = render_profile_md(data)
		self.assertIn("- Vehicle Log - workflow: Vehicle Approval", doc)
		self.assertIn("- Trip Sheet\n", doc)
		self.assertNotIn("Trip Sheet - workflow", doc)

	def test_module_not_in_modules_mapping_lands_under_other_customizations(self):
		data = {
			"apps": ["fleet_mgmt"],
			"modules": {"Fleet": "fleet_mgmt"},
			"custom_doctypes": [
				{"name": "Ledger Tweak", "module": "Accounts", "istable": 0, "issingle": 0, "is_submittable": 0},
			],
			"core_customizations": [],
			"workflows": [],
			"reports": [],
			"print_formats": [],
			"scripts": {"server": {}, "client": {}},
		}
		doc = render_profile_md(data)
		self.assertIn("### Other customizations - 1 doctypes", doc)
		self.assertIn("- Ledger Tweak", doc)


if __name__ == "__main__":
	unittest.main()
