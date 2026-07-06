"""Learned-pattern lifecycle tests (plan section 6.5): dedupe / draft-freeze /
durable-but-reversible suppression / snooze expiry / retention / overlap.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from jarvis.learning import lifecycle

JLP = "Jarvis Learned Pattern"
JLP_ROLE = "Jarvis Learned Pattern Role"
RUN = "Jarvis Pattern Run"
SKILL = "Jarvis Custom Skill"

KEY = "_lc-key-1"
OVERLAP_SKILL = "lc-overlap-skill"


def _candidate(pattern_key=KEY, **over):
	c = {
		"detector_id": "buy-supplier-stockness",
		"pattern_key": pattern_key,
		"domain": "buying",
		"company": None,
		"roles": ["Purchase User"],
		"pattern_statement": "Supplier ThreadCo supplies only non-stock items.",
		"skill_draft": (
			'- Supplier "ThreadCo" supplies only non-stock items. '
			"Evidence: 95% of 40 Purchase Orders since 2025-01."
		),
		"support_n": 40,
		"n_rows": 40,
		"exception_n": 2,
		"confidence_pct": 95.0,
		"wilson_low": 0.85,
		"gap": 0.30,
		"strength_band": "Medium",
		"temporal_spread": {"distinct_days": 10},
		"evidence": {"antecedent": "ThreadCo"},
		"exceptions": [],
		"exceptions_cluster": None,
		"sensitivity": "B",
		"effective_sensitivity": "B",
		"not_applicable": False,
	}
	c.update(over)
	return c


class TestLifecycle(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.run = frappe.get_doc(
			{"doctype": RUN, "trigger": "manual", "status": "Running"}
		).insert(ignore_permissions=True)
		frappe.local._jarvis_overlap_index = None

	def tearDown(self):
		frappe.db.delete(JLP_ROLE, {"parenttype": JLP})
		frappe.db.delete(JLP, {"pattern_key": ["like", "_lc-%"]})
		frappe.db.delete(SKILL, {"skill_name": OVERLAP_SKILL})
		frappe.db.delete(RUN, {"name": self.run.name})
		frappe.local._jarvis_overlap_index = None
		frappe.db.commit()
		super().tearDown()

	def _row(self, key=KEY):
		name = frappe.db.exists(JLP, {"pattern_key": key})
		return frappe.get_doc(JLP, name) if name else None

	def _reject(self, key=KEY, **fields):
		name = frappe.db.exists(JLP, {"pattern_key": key})
		payload = {"status": "Rejected"}
		payload.update(fields)
		frappe.db.set_value(JLP, name, payload, update_modified=False)

	# --- create / dedupe ---------------------------------------------------- #
	def test_insert_creates_proposed_with_roles(self):
		self.assertEqual(lifecycle.upsert_candidate(_candidate(), self.run), "created")
		row = self._row()
		self.assertEqual(row.status, "Proposed")
		self.assertEqual(row.support_n, 40)
		self.assertEqual(row.first_seen_run, self.run.name)
		self.assertIn("Purchase User", [r.role for r in row.roles])

	def test_dedupe_refreshes_non_terminal(self):
		lifecycle.upsert_candidate(_candidate(), self.run)
		out = lifecycle.upsert_candidate(_candidate(support_n=55), self.run)
		self.assertEqual(out, "updated")
		self.assertEqual(self._row().support_n, 55)
		self.assertEqual(self._row().status, "Proposed")

	def test_edited_draft_is_not_overwritten(self):
		lifecycle.upsert_candidate(_candidate(), self.run)
		name = self._row().name
		frappe.db.set_value(
			JLP, name, {"draft_edited": 1, "skill_draft": "- SM edited rule."},
			update_modified=False,
		)
		lifecycle.upsert_candidate(_candidate(skill_draft="- fresh detector text."), self.run)
		self.assertEqual(self._row().skill_draft, "- SM edited rule.")

	# --- suppression (durable but reversible) ------------------------------- #
	def test_rejected_stays_suppressed_when_not_stronger(self):
		lifecycle.upsert_candidate(_candidate(), self.run)
		self._reject(strength_band="Medium", support_n=40)
		out = lifecycle.upsert_candidate(_candidate(strength_band="Medium", support_n=42), self.run)
		self.assertEqual(out, "duplicate")
		row = self._row()
		self.assertEqual(row.status, "Rejected")
		self.assertEqual(row.last_seen_run, self.run.name)

	def test_rejected_reappears_on_band_rise(self):
		lifecycle.upsert_candidate(_candidate(), self.run)
		self._reject(strength_band="Medium", support_n=40, review_note="not now")
		out = lifecycle.upsert_candidate(
			_candidate(strength_band="High", wilson_low=0.95), self.run
		)
		self.assertEqual(out, "created")
		row = self._row()
		self.assertEqual(row.status, "Proposed")
		self.assertEqual(row.surfaced, 0)
		self.assertIn("re-proposed", (row.review_note or "").lower())

	def test_rejected_reappears_on_support_growth(self):
		lifecycle.upsert_candidate(_candidate(), self.run)
		self._reject(strength_band="Medium", support_n=40)
		out = lifecycle.upsert_candidate(
			_candidate(strength_band="Medium", support_n=70), self.run
		)
		self.assertEqual(out, "created")
		self.assertEqual(self._row().status, "Proposed")

	def test_superseded_is_skipped(self):
		lifecycle.upsert_candidate(_candidate(), self.run)
		name = self._row().name
		frappe.db.set_value(JLP, name, {"status": "Superseded"}, update_modified=False)
		out = lifecycle.upsert_candidate(_candidate(support_n=99), self.run)
		self.assertEqual(out, "duplicate")
		row = self._row()
		self.assertEqual(row.status, "Superseded")
		self.assertEqual(row.support_n, 40)  # not refreshed
		self.assertEqual(row.last_seen_run, self.run.name)

	# --- snooze expiry / retention ------------------------------------------ #
	def test_snooze_expiry_unsnoozes_elapsed(self):
		lifecycle.upsert_candidate(_candidate(), self.run)
		name = self._row().name
		past = str(add_to_date(now_datetime(), days=-1).date())
		frappe.db.set_value(
			JLP, name, {"status": "Snoozed", "snoozed_until": past, "surfaced": 1},
			update_modified=False,
		)
		res = lifecycle.snooze_expiry()
		self.assertGreaterEqual(res["unsnoozed"], 1)
		row = self._row()
		self.assertEqual(row.status, "Proposed")
		self.assertEqual(row.surfaced, 0)

	def test_retention_archives_old_rejected_and_trims_evidence(self):
		lifecycle.upsert_candidate(_candidate(), self.run)
		name = self._row().name
		old = str(add_to_date(now_datetime(), days=-200))
		frappe.db.set_value(JLP, name, {"status": "Rejected"}, update_modified=False)
		frappe.db.set_value(JLP, name, {"modified": old}, update_modified=False)
		res = lifecycle.retention()
		self.assertGreaterEqual(res["archived"], 1)
		row = self._row()
		self.assertEqual(row.status, "Archived")
		self.assertIn(row.evidence, (None, ""))

	def test_recent_rejected_not_archived(self):
		lifecycle.upsert_candidate(_candidate(), self.run)
		name = self._row().name
		frappe.db.set_value(JLP, name, {"status": "Rejected"}, update_modified=False)
		lifecycle.retention()
		self.assertEqual(self._row().status, "Rejected")

	# --- overlap warning ---------------------------------------------------- #
	def test_overlap_warning_set_against_enabled_custom_skill(self):
		# Low-level insert bypasses the per-owner cap (this dev site is near it).
		d = frappe.new_doc(SKILL)
		d.update({
			"skill_name": OVERLAP_SKILL,
			"description": "Supplier ThreadCo supplies only non-stock items handling",
			"instructions": "Body about supplier non-stock items handling.",
			"enabled": 1,
			"user_invocable": 0,
			"managed_by_learning": 0,
		})
		d.owner = "Administrator"
		d.name = "lc-overlap-row"
		d.flags.name_set = True
		d.db_insert()
		frappe.local._jarvis_overlap_index = None  # rebuild against the new skill
		lifecycle.upsert_candidate(_candidate(), self.run)
		self.assertTrue((self._row().overlap_warning or "").strip())


class TestRevalidateStub(FrappeTestCase):
	def test_revalidate_active_is_noop_stub(self):
		res = lifecycle.revalidate_active(None)
		self.assertTrue(res.get("stub"))
		self.assertEqual(res.get("staled"), 0)


class TestSurfacingSortKey(FrappeTestCase):
	"""Plan section 6.4 surfacing priority (fix 8): party-specific personalization
	(effective_sensitivity B/C) ranked ahead of A config-cleanup, then band, then
	support_n desc. Pure ordering helper - no DB."""

	def test_party_ranked_ahead_of_config_cleanup(self):
		# A-class config-cleanup, strong band, big support...
		a = {"effective_sensitivity": "A", "strength_band": "High", "support_n": 500}
		# ...still ranks BELOW a weaker party-specific B row.
		b = {"effective_sensitivity": "B", "strength_band": "Medium", "support_n": 30}
		ordered = sorted([a, b], key=lifecycle.surfacing_sort_key)
		self.assertIs(ordered[0], b)
		self.assertIs(ordered[1], a)

	def test_within_class_band_then_support(self):
		high = {"effective_sensitivity": "B", "strength_band": "High", "support_n": 10}
		med = {"effective_sensitivity": "B", "strength_band": "Medium", "support_n": 999}
		self.assertEqual(
			sorted([med, high], key=lifecycle.surfacing_sort_key), [high, med]
		)
		a_small = {"effective_sensitivity": "A", "strength_band": "High", "support_n": 5}
		a_big = {"effective_sensitivity": "A", "strength_band": "High", "support_n": 50}
		self.assertEqual(
			sorted([a_small, a_big], key=lifecycle.surfacing_sort_key), [a_big, a_small]
		)

	def test_c_class_also_counts_as_party(self):
		c = {"effective_sensitivity": "C", "strength_band": "Low", "support_n": 1}
		a = {"effective_sensitivity": "A", "strength_band": "High", "support_n": 999}
		self.assertEqual(sorted([a, c], key=lifecycle.surfacing_sort_key), [c, a])
