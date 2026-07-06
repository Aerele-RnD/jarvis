"""Tests for the SM-gated learning-board API (jarvis/chat/learned_api.py).

Covers, per plan sections 6.4/6.5/5.1: System-Manager gating (non-SM ->
PermissionError), the managed-only self-host block (and the deliberate
get_learning_status exemption), the frozen list envelope + domain facets +
board counters, the approve/reject/un-approve/restore/snooze lifecycle
transitions with their TOCTOU source guards, the A-class-only batch_approve
guard, run-now enqueue, apply delegation to the compiler, and the settings
read/write window validation.

unittest.TestCase with explicit commits + prefix cleanup (like
test_feature_pages_api / test_agents_marketplace): the endpoints run raw SQL
and need a real non-SM user to prove the permission gate. Every fixture row
carries an ``la-test-`` marker so cleanup is owner-independent.
"""

from __future__ import annotations

import contextlib
import json
import sys
import types
import unittest
from unittest import mock

import frappe

from jarvis.chat import learned_api

JLP = "Jarvis Learned Pattern"
RUN = "Jarvis Pattern Run"
SETTINGS = "Jarvis Settings"

NON_SM = "la-nonsm@example.com"
KEY_PREFIX = "la-test-"


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
def _ensure_non_sm(email: str) -> str:
	# A realistic unauthorized actor for these desk-admin endpoints is a System
	# User who lacks System Manager (e.g. a Sales User), NOT a portal/Website
	# User - a Website User is a weaker negative test and could mask a bug if an
	# endpoint ever gated on user_type instead of the role.
	if not frappe.db.exists("User", email):
		u = frappe.get_doc({
			"doctype": "User", "email": email,
			"first_name": "la-nonsm", "send_welcome_email": 0, "enabled": 1,
			"user_type": "System User",
			"roles": [{"role": "Sales User"}],
		})
		u.flags.ignore_permissions = True
		u.insert()
		frappe.db.commit()
	elif frappe.db.get_value("User", email, "user_type") != "System User":
		# Promote a fixture left over from an older run as a Website User.
		frappe.db.set_value("User", email, "user_type", "System User")
		frappe.db.commit()
	if "System Manager" in set(frappe.get_roles(email)):
		frappe.get_doc("User", email).remove_roles("System Manager")
		frappe.db.commit()
	return email


@contextlib.contextmanager
def _as(user: str):
	orig = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(orig)


def _wipe() -> None:
	for name in frappe.get_all(
		JLP, filters={"pattern_key": ["like", f"{KEY_PREFIX}%"]}, pluck="name"
	):
		frappe.delete_doc(JLP, name, force=True, ignore_permissions=True)
	for name in frappe.get_all(
		RUN, filters={"requested_by": ["like", "%learned-run%"]}, pluck="name"
	):
		frappe.delete_doc(RUN, name, force=True, ignore_permissions=True)
	frappe.db.commit()


def _mk(key: str, **kw) -> str:
	"""Insert a JLP row directly (engine flag bypasses the transition guard so a
	fixture can start in any status)."""
	fields = {
		"doctype": JLP,
		"detector_id": kw.pop("detector_id", "la-test-det"),
		"pattern_key": KEY_PREFIX + key,
		"domain": kw.pop("domain", "selling"),
		"pattern_statement": kw.pop("statement", f"Statement for {key}"),
		"skill_draft": kw.pop(
			"skill_draft",
			f"- Rule {key}. Evidence: 90% of 100 Sales Invoices since 2024-01.",
		),
		"status": kw.pop("status", "Proposed"),
		"surfaced": kw.pop("surfaced", 1),
		"strength_band": kw.pop("strength_band", "High"),
		"sensitivity": kw.pop("sensitivity", "A"),
		"effective_sensitivity": kw.pop("effective_sensitivity", "A"),
	}
	evidence = kw.pop("evidence", None)
	if evidence is not None:
		fields["evidence"] = json.dumps(evidence)
	roles = kw.pop("roles", None)
	if roles:
		fields["roles"] = [{"role": r} for r in roles]
	fields.update(kw)

	frappe.flags.jarvis_pattern_engine = True
	try:
		doc = frappe.get_doc(fields)
		doc.flags.ignore_permissions = True
		doc.insert()
	finally:
		frappe.flags.jarvis_pattern_engine = False
	frappe.db.commit()
	return doc.name


class TestLearnedApi(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		cls.non_sm = _ensure_non_sm(NON_SM)

	def setUp(self):
		frappe.set_user("Administrator")
		_wipe()

	def tearDown(self):
		frappe.set_user("Administrator")
		_wipe()

	# ------------------------------------------------------------------ #
	# SM gating
	# ------------------------------------------------------------------ #
	def test_non_sm_is_refused(self):
		_mk("g1")
		with _as(self.non_sm):
			for call in (
				lambda: learned_api.list_learned_patterns_page(),
				lambda: learned_api.pending_learned_count(),
				lambda: learned_api.get_learning_status(),
				lambda: learned_api.run_pattern_analysis_now(),
			):
				with self.assertRaises(frappe.PermissionError):
					call()

	# ------------------------------------------------------------------ #
	# self-host block (+ get_learning_status exemption)
	# ------------------------------------------------------------------ #
	def test_self_host_blocks_feature_endpoints(self):
		name = _mk("sh1")
		with mock.patch("jarvis.selfhost.is_self_hosted", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				learned_api.list_learned_patterns_page()
			with self.assertRaises(frappe.ValidationError):
				learned_api.get_learned_pattern(name)
			with self.assertRaises(frappe.ValidationError):
				learned_api.approve_learned_pattern(name)
			# get_learning_status is exempt: it reports self_hosted so the tab can
			# render the managed-only empty state.
			status = learned_api.get_learning_status()
			self.assertEqual(status["self_hosted"], 1)

	# ------------------------------------------------------------------ #
	# list envelope + facets + counters
	# ------------------------------------------------------------------ #
	def test_list_envelope_shape_and_facets(self):
		_mk("e1", domain="selling", surfaced=1)
		_mk("e2", domain="buying", surfaced=1)
		_mk("e3", domain="selling", surfaced=1, strength_band="Low")
		_mk("q1", domain="stock", surfaced=0)  # queued (unsurfaced)
		_mk("ap1", domain="accounts", surfaced=1, status="Approved")

		out = learned_api.list_learned_patterns_page(status="Proposed", surfaced=1)
		for key in (
			"rows", "total", "has_more", "start", "page_length", "facets",
			"queued_count", "pending_apply_count", "review_activity",
		):
			self.assertIn(key, out)

		self.assertIn("domain", out["facets"])
		facet_domains = {f["value"] for f in out["facets"]["domain"]}
		self.assertIn("selling", facet_domains)
		self.assertIn("buying", facet_domains)

		# queued_count counts the unsurfaced Proposed row.
		self.assertGreaterEqual(out["queued_count"], 1)
		# pending_apply_count counts the Approved row.
		self.assertGreaterEqual(out["pending_apply_count"], 1)

		# rows are plain-English cards: raw stats must NOT be present.
		self.assertTrue(out["rows"])
		row = out["rows"][0]
		for banned in ("support_n", "n_rows", "confidence_pct", "wilson_low", "gap"):
			self.assertNotIn(banned, row)
		for present in ("pattern_statement", "strength_band", "domain", "status"):
			self.assertIn(present, row)

	def test_list_domain_filter_and_search(self):
		_mk("d1", domain="selling", statement="apples for dealer")
		_mk("d2", domain="buying", statement="oranges for supplier")

		only_selling = learned_api.list_learned_patterns_page(domain="selling")
		stmts = {r["pattern_statement"] for r in only_selling["rows"]}
		self.assertIn("apples for dealer", stmts)
		self.assertNotIn("oranges for supplier", stmts)

		found = learned_api.list_learned_patterns_page(search="oranges")
		stmts = {r["pattern_statement"] for r in found["rows"]}
		self.assertIn("oranges for supplier", stmts)
		self.assertNotIn("apples for dealer", stmts)

	def test_list_rejects_bad_filters(self):
		with self.assertRaises(frappe.ValidationError):
			learned_api.list_learned_patterns_page(domain="not-a-domain")
		with self.assertRaises(frappe.ValidationError):
			learned_api.list_learned_patterns_page(status="Bogus")
		with self.assertRaises(frappe.ValidationError):
			learned_api.list_learned_patterns_page(strength="Enormous")

	# ------------------------------------------------------------------ #
	# detail drill-down
	# ------------------------------------------------------------------ #
	def test_get_learned_pattern_drilldown(self):
		name = _mk(
			"det1",
			support_n=214, n_rows=800, confidence_pct=96.0, wilson_low=0.91,
			gap=0.4, roles=["System Manager"],
			evidence={"exceptions": [{"ref": "SINV-1"}], "base_rate": 0.5},
		)
		out = learned_api.get_learned_pattern(name)
		self.assertEqual(out["name"], name)
		self.assertEqual(out["support_n"], 214)  # drill-down keeps the raw stats
		self.assertEqual(out["roles"], ["System Manager"])
		self.assertEqual(out["evidence"]["base_rate"], 0.5)
		self.assertEqual(len(out["exceptions"]), 1)
		self.assertTrue(out["compiled_preview"])  # falls back to skill_draft

	def test_compiled_preview_is_single_bullet(self):
		# The drill-down preview is THIS pattern's compiled bullet (previously the
		# call passed a pattern name where compile_preview wanted a domain, so it
		# always fell back to the raw draft - fix 4).
		name = _mk(
			"cp1",
			skill_draft="- Prefer letterhead LH1. Evidence: 95% of 80 Sales Invoices since 2024-03.",
		)
		out = learned_api.get_learned_pattern(name)
		self.assertTrue(out["compiled_preview"].startswith("- "))
		self.assertIn(name, out["compiled_preview"])  # JLP ref appended by the compiler

	# ------------------------------------------------------------------ #
	# lifecycle transitions + TOCTOU
	# ------------------------------------------------------------------ #
	def test_approve_stamps_and_transitions(self):
		name = _mk("a1")
		out = learned_api.approve_learned_pattern(name)
		self.assertEqual(out["status"], "Approved")
		doc = frappe.get_doc(JLP, name)
		self.assertEqual(doc.status, "Approved")
		self.assertEqual(doc.reviewed_by, "Administrator")
		self.assertEqual(doc.approved_by, "Administrator")
		self.assertTrue(doc.reviewed_at)
		self.assertFalse(doc.draft_edited)

	def test_approve_with_edit_freezes_evidence(self):
		name = _mk("a2")
		out = learned_api.approve_learned_pattern(name, edited_skill_draft="- My edited rule.")
		self.assertEqual(out["draft_edited"], 1)
		doc = frappe.get_doc(JLP, name)
		self.assertEqual(doc.skill_draft, "- My edited rule.")
		self.assertEqual(doc.draft_edited, 1)
		detail = learned_api.get_learned_pattern(name)
		self.assertTrue(detail["frozen_evidence_label"])

	def test_approve_toctou_guard(self):
		name = _mk("a3")
		learned_api.approve_learned_pattern(name)
		# A second approve sees the row is no longer Proposed and refuses.
		with self.assertRaises(frappe.ValidationError):
			learned_api.approve_learned_pattern(name)

	def test_approve_refuses_non_a_class(self):
		# B/C are insight-only in Phase 1: approve must refuse (the compiler is
		# A-only, so a B/C Approved row would never activate and would wedge the
		# pending-apply bar) and point the SM to Acknowledge.
		b = _mk("bc1", effective_sensitivity="B")
		with self.assertRaises(frappe.ValidationError):
			learned_api.approve_learned_pattern(b)
		self.assertEqual(frappe.db.get_value(JLP, b, "status"), "Proposed")
		c = _mk("bc2", effective_sensitivity="C")
		with self.assertRaises(frappe.ValidationError):
			learned_api.approve_learned_pattern(c)
		self.assertEqual(frappe.db.get_value(JLP, c, "status"), "Proposed")

	def test_acknowledge_b_class_is_terminal_and_uncounted(self):
		before = learned_api._pending_apply_count()
		b = _mk("ack1", effective_sensitivity="B", surfaced=1)
		out = learned_api.acknowledge_learned_pattern(b)
		self.assertTrue(out["acknowledged"])
		self.assertEqual(out["status"], "Rejected")
		self.assertEqual(frappe.db.get_value(JLP, b, "review_note"), learned_api.ACK_NOTE)
		self.assertEqual(frappe.db.get_value(JLP, b, "reviewed_by"), "Administrator")
		# acknowledged rows are NOT pending-apply (they are terminal, not Approved).
		self.assertEqual(learned_api._pending_apply_count(), before)
		# already terminal -> a second acknowledge is refused (source guard).
		with self.assertRaises(frappe.ValidationError):
			learned_api.acknowledge_learned_pattern(b)

	def test_acknowledge_refuses_a_class(self):
		a = _mk("ack2", effective_sensitivity="A")
		with self.assertRaises(frappe.ValidationError):
			learned_api.acknowledge_learned_pattern(a)
		self.assertEqual(frappe.db.get_value(JLP, a, "status"), "Proposed")

	def test_pending_apply_count_excludes_bc_approved(self):
		# Only A-class Approved rows are pending-apply; B/C Approved (which the
		# compiler would never activate) must not inflate the count.
		baseline = learned_api._pending_apply_count()
		_mk("pa1", status="Approved", effective_sensitivity="A")
		_mk("pa2", status="Approved", effective_sensitivity="B")
		_mk("pa3", status="Approved", effective_sensitivity="C")
		self.assertEqual(learned_api._pending_apply_count(), baseline + 1)

	def test_reject_requires_reason(self):
		name = _mk("r1")
		with self.assertRaises(frappe.ValidationError):
			learned_api.reject_learned_pattern(name, reason="   ")
		out = learned_api.reject_learned_pattern(name, reason="not a real habit")
		self.assertEqual(out["status"], "Rejected")
		self.assertEqual(frappe.db.get_value(JLP, name, "review_note"), "not a real habit")

	def test_unapprove_returns_to_proposed(self):
		name = _mk("u1")
		learned_api.approve_learned_pattern(name)
		out = learned_api.unapprove_learned_pattern(name)
		self.assertEqual(out["status"], "Proposed")
		self.assertFalse(frappe.db.get_value(JLP, name, "approved_by"))
		# Cannot un-approve something that is not Approved.
		with self.assertRaises(frappe.ValidationError):
			learned_api.unapprove_learned_pattern(name)

	def test_unapprove_blocked_while_apply_pending(self):
		name = _mk("u2", status="Approved")
		with mock.patch.object(learned_api, "_apply_pending", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				learned_api.unapprove_learned_pattern(name)
		self.assertEqual(frappe.db.get_value(JLP, name, "status"), "Approved")

	def test_unapprove_blocked_while_apply_marker_set(self):
		# The compiler's apply-in-progress marker closes the compile -> flip TOCTOU
		# window that the sync-status `pending` flag alone misses.
		name = _mk("u3", status="Approved")
		with mock.patch("jarvis.learning.compiler.apply_in_progress", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				learned_api.unapprove_learned_pattern(name)
		self.assertEqual(frappe.db.get_value(JLP, name, "status"), "Approved")

	def test_restore_rejected(self):
		name = _mk("rr1", status="Rejected", review_note="was wrong")
		out = learned_api.restore_rejected_pattern(name)
		self.assertEqual(out["status"], "Proposed")
		with self.assertRaises(frappe.ValidationError):
			learned_api.restore_rejected_pattern(name)  # already Proposed

	def test_snooze_validates_days(self):
		name = _mk("sn1")
		with self.assertRaises(frappe.ValidationError):
			learned_api.snooze_learned_pattern(name, days=5)
		out = learned_api.snooze_learned_pattern(name, days=30)
		self.assertEqual(out["status"], "Snoozed")
		self.assertTrue(frappe.db.get_value(JLP, name, "snoozed_until"))

	# ------------------------------------------------------------------ #
	# batch approve (A-only)
	# ------------------------------------------------------------------ #
	def test_batch_approve_a_only(self):
		a1 = _mk("b1", effective_sensitivity="A")
		a2 = _mk("b2", effective_sensitivity="A")
		out = learned_api.batch_approve([a1, a2])
		self.assertEqual(out["count"], 2)
		self.assertEqual(frappe.db.get_value(JLP, a1, "status"), "Approved")
		self.assertEqual(frappe.db.get_value(JLP, a2, "status"), "Approved")

	def test_batch_approve_refuses_mixed_sensitivity(self):
		a1 = _mk("b3", effective_sensitivity="A")
		b1 = _mk("b4", effective_sensitivity="B")
		with self.assertRaises(frappe.ValidationError):
			learned_api.batch_approve([a1, b1])
		# The whole batch is refused: the A-class row must NOT have been approved.
		self.assertEqual(frappe.db.get_value(JLP, a1, "status"), "Proposed")

	def test_batch_approve_unknown_name(self):
		with self.assertRaises(frappe.ValidationError):
			learned_api.batch_approve(["JLP-does-not-exist"])

	# ------------------------------------------------------------------ #
	# badges / counters
	# ------------------------------------------------------------------ #
	def test_pending_learned_count(self):
		_mk("p1", surfaced=1, status="Proposed")
		_mk("p2", surfaced=0, status="Proposed")  # queued, not counted
		_mk("p3", surfaced=1, status="Approved")  # decided, not counted
		self.assertEqual(learned_api.pending_learned_count(), 1)

	# ------------------------------------------------------------------ #
	# apply delegation + status proxy
	# ------------------------------------------------------------------ #
	def test_apply_learned_skills_delegates_to_compiler(self):
		stub = types.ModuleType("jarvis.learning.compiler")
		stub.apply_learned_skills = lambda: {"ok": True, "sentinel": "compiled"}
		with mock.patch.dict(sys.modules, {"jarvis.learning.compiler": stub}):
			out = learned_api.apply_learned_skills()
		self.assertEqual(out["sentinel"], "compiled")

	def test_get_learned_apply_status_proxies_sync(self):
		out = learned_api.get_learned_apply_status()
		self.assertIn("last_sync_status", out)
		self.assertIn("pending", out)

	# ------------------------------------------------------------------ #
	# run now
	# ------------------------------------------------------------------ #
	def test_run_now_enqueues(self):
		orig_enabled = frappe.db.get_single_value(SETTINGS, "pattern_learning_enabled")
		frappe.db.set_single_value(SETTINGS, "pattern_learning_enabled", 1)
		frappe.db.commit()
		try:
			with mock.patch("frappe.enqueue") as enq:
				out = learned_api.run_pattern_analysis_now()
			self.assertTrue(out["ok"])
			self.assertTrue(out["run"])
			self.assertTrue(frappe.db.exists(RUN, out["run"]))
			self.assertTrue(enq.called)
			# clean the run row up regardless of its requested_by value
			frappe.delete_doc(RUN, out["run"], force=True, ignore_permissions=True)
			frappe.db.commit()
		finally:
			frappe.db.set_single_value(SETTINGS, "pattern_learning_enabled", orig_enabled or 0)
			frappe.db.commit()

	# ------------------------------------------------------------------ #
	# settings read/write + window validation
	# ------------------------------------------------------------------ #
	def test_get_learning_settings_shape(self):
		out = learned_api.get_learning_settings()
		self.assertIn("settings", out)
		self.assertIn("pattern_window_start", out["settings"])
		self.assertIsNone(out["preflight"])  # lazy: not computed unless asked

	def test_set_learning_settings_writes_and_validates_window(self):
		s = frappe.get_single(SETTINGS)
		orig = {f: s.get(f) for f in learned_api._SETTINGS_FIELDS}
		try:
			with mock.patch("frappe.enqueue"):
				# A valid write persists.
				learned_api.set_learning_settings(
					{"pattern_max_proposals_per_run": 7}
				)
				self.assertEqual(
					frappe.db.get_single_value(SETTINGS, "pattern_max_proposals_per_run"), 7
				)
				# Enabling with a sub-1h window is rejected by the doc validation.
				with self.assertRaises(frappe.ValidationError):
					learned_api.set_learning_settings({
						"pattern_learning_enabled": 1,
						"pattern_window_start": "02:00:00",
						"pattern_window_end": "02:30:00",
					})
		finally:
			with mock.patch("frappe.enqueue"):
				restore = frappe.get_single(SETTINGS)
				for f, v in orig.items():
					restore.set(f, v)
				restore.save()
				frappe.db.commit()

	def test_set_learning_settings_rejects_unknown_field(self):
		with self.assertRaises(frappe.ValidationError):
			learned_api.set_learning_settings({"pattern_learning_enabled": 1, "llm_model": "x"})

	def test_set_learning_settings_no_on_update_side_effect(self):
		# A pattern_* write must NOT run Jarvis Settings.on_update (LLM pool
		# re-sync); the fix writes via db.set_value(update_modified=False) after an
		# inline window validation, so no save hook fires (fix 5).
		s = frappe.get_single(SETTINGS)
		orig = {f: s.get(f) for f in learned_api._SETTINGS_FIELDS}
		try:
			with mock.patch("frappe.enqueue") as enq:
				learned_api.set_learning_settings({"pattern_max_proposals_per_run": 9})
			self.assertEqual(
				frappe.db.get_single_value(SETTINGS, "pattern_max_proposals_per_run"), 9
			)
			self.assertFalse(enq.called)
		finally:
			frappe.db.set_single_value(SETTINGS, orig, update_modified=False)
			frappe.db.commit()

	def test_get_learning_settings_coalesces_nulls_to_defaults(self):
		# A never-seeded Single reads null for the pattern_* config; the read must
		# coalesce to the field defaults so the card never shows blank/0 (fix 6).
		s = frappe.get_single(SETTINGS)
		orig = {f: s.get(f) for f in learned_api._SETTINGS_FIELDS}
		try:
			frappe.db.set_value(
				SETTINGS, SETTINGS,
				{
					"pattern_window_start": None,
					"pattern_window_end": None,
					"pattern_max_proposals_per_run": None,
					"pattern_row_budget_per_night": None,
				},
				update_modified=False,
			)
			frappe.db.commit()
			frappe.clear_document_cache(SETTINGS, SETTINGS)
			out = learned_api.get_learning_settings()["settings"]
			self.assertEqual(out["pattern_window_start"], "01:00:00")
			self.assertEqual(out["pattern_window_end"], "05:00:00")
			self.assertEqual(out["pattern_max_proposals_per_run"], 10)
			self.assertEqual(out["pattern_row_budget_per_night"], 500000)
		finally:
			frappe.db.set_single_value(SETTINGS, orig, update_modified=False)
			frappe.db.commit()
			frappe.clear_document_cache(SETTINGS, SETTINGS)

	def test_seed_settings_defaults_fills_only_nulls(self):
		# bootstrap.after_migrate persists the pattern_* defaults when null (Frappe
		# does not backfill Single defaults on migrate) - fix 6.
		from frappe.utils import get_time

		from jarvis.learning import bootstrap

		s = frappe.get_single(SETTINGS)
		orig = {f: s.get(f) for f in learned_api._SETTINGS_FIELDS}
		try:
			frappe.db.set_value(
				SETTINGS, SETTINGS,
				{k: None for k in bootstrap._SETTINGS_DEFAULTS},
				update_modified=False,
			)
			# a non-null operator value must NOT be clobbered
			frappe.db.set_value(
				SETTINGS, SETTINGS, {"pattern_max_proposals_per_run": 3},
				update_modified=False,
			)
			frappe.db.commit()
			frappe.clear_document_cache(SETTINGS, SETTINGS)
			bootstrap._seed_settings_defaults()

			def _hhmmss(field):
				# get_single_value casts Time to timedelta; normalize to HH:MM:SS.
				return str(get_time(str(frappe.db.get_single_value(SETTINGS, field))))

			self.assertEqual(_hhmmss("pattern_window_start"), "01:00:00")
			self.assertEqual(_hhmmss("pattern_window_end"), "05:00:00")
			self.assertEqual(
				frappe.db.get_single_value(SETTINGS, "pattern_row_budget_per_night"), 500000
			)
			# left the operator's non-null value alone
			self.assertEqual(
				frappe.db.get_single_value(SETTINGS, "pattern_max_proposals_per_run"), 3
			)
		finally:
			frappe.db.set_single_value(SETTINGS, orig, update_modified=False)
			frappe.db.commit()
			frappe.clear_document_cache(SETTINGS, SETTINGS)

	def test_naming_series_readiness_uses_series_table(self):
		# The cfg-naming-series detector's antecedent is a DocType name; readiness
		# must measure numbered documents (tabSeries), not recent DocType creations
		# (~0 on a stable site -> permanent false data_starved) - fix 7.
		from jarvis.learning import bootstrap, registry

		series_total = int(
			frappe.db.sql("select coalesce(sum(`current`), 0) from `tabSeries`")[0][0]
		)
		self.assertEqual(bootstrap._naming_series_doc_count(), series_total)

		naming = registry.get_detector("cfg-naming-series")
		self.assertEqual(
			bootstrap._readiness_count(
				naming, naming["doctype"], naming.get("window_months") or 12
			),
			series_total,
		)
		# a normal party/group detector still counts its OWN doctype's recent rows.
		other = registry.get_detector("sell-group-payment-terms")
		self.assertEqual(
			bootstrap._readiness_count(other, other["doctype"], 18),
			bootstrap._count_recent(other["doctype"], 18),
		)


if __name__ == "__main__":
	unittest.main()
