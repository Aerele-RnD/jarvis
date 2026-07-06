"""End-to-end flow test: seed -> engine run -> proposals -> approve -> compile -> activation.

Exercises the full Phase 1 pipeline on a seeded mini-org, verifying the pieces that the
per-module unit tests touch only in isolation: the engine driver producing real proposals
from real ERPNext rows, the A-only compilation rule, the batch-approve A-class guard, and
the deterministic turn-context injection for a role-matched user.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.tests.learning import factory
from jarvis.learning import orchestrator, engine, compiler
from jarvis.chat import learned_api


class TestPatternLearningE2E(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		# This dev bench carries ~124 enabled custom skills (far over the 25 cap);
		# park them so managed-skill inserts / apply can run, restore in teardown.
		# Production managed sites have Administrator owning ~0 skills, so no parking
		# is needed there (test-environment isolation only).
		cls._parked = frappe.get_all(
			"Jarvis Custom Skill", filters={"enabled": 1}, pluck="name"
		)
		for n in cls._parked:
			frappe.db.set_value("Jarvis Custom Skill", n, "enabled", 0, update_modified=False)
		factory.wipe()
		factory.build(commit=True)
		frappe.get_single("Jarvis Settings").db_set(
			"pattern_learning_enabled", 1, update_modified=False
		)
		# clear any prior proposals for a deterministic count
		frappe.flags.jarvis_pattern_engine = True
		for n in frappe.get_all("Jarvis Learned Pattern", pluck="name"):
			frappe.delete_doc("Jarvis Learned Pattern", n, force=True, ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.flags.jarvis_pattern_engine = True
		for n in frappe.get_all("Jarvis Learned Pattern", pluck="name"):
			frappe.delete_doc("Jarvis Learned Pattern", n, force=True, ignore_permissions=True)
		factory.wipe()
		for n in getattr(cls, "_parked", []):
			if frappe.db.exists("Jarvis Custom Skill", n):
				frappe.db.set_value("Jarvis Custom Skill", n, "enabled", 1, update_modified=False)
		frappe.db.commit()
		super().tearDownClass()

	def test_full_flow(self):
		# 1. run the engine via the manual (window-bypassing) path
		res = orchestrator.run_now("Administrator")
		run_name = res.get("run") if isinstance(res, dict) else res
		self.assertTrue(run_name, "run_now must return a run name")
		engine.run_pattern_analysis(run_name)
		frappe.db.commit()

		run = frappe.get_doc("Jarvis Pattern Run", run_name)
		self.assertIn(run.status, ("Completed", "Partial"))
		self.assertGreater(run.detectors_completed or 0, 0)

		# 2. real proposals were produced from the seeded org
		props = frappe.get_all(
			"Jarvis Learned Pattern",
			fields=["name", "detector_id", "effective_sensitivity", "strength_band", "status"],
		)
		self.assertGreater(len(props), 0, "engine must produce at least one proposal")
		self._props = props
		print(f"[E2E] proposals={len(props)} "
		      f"A={sum(p.effective_sensitivity=='A' for p in props)} "
		      f"B={sum(p.effective_sensitivity=='B' for p in props)}")

		# 3. API envelope shape
		env = learned_api.list_learned_patterns_page()
		for key in ("rows", "total"):
			self.assertIn(key, env)

		# 4. approve an A-class, verify transition, then un-approve round-trip
		a = [p for p in props if p.effective_sensitivity == "A"]
		self.assertTrue(a, "seeded org must yield at least one A-class pattern")
		tgt = a[0].name
		learned_api.approve_learned_pattern(tgt)
		frappe.db.commit()
		self.assertEqual(frappe.db.get_value("Jarvis Learned Pattern", tgt, "status"), "Approved")
		learned_api.unapprove_learned_pattern(tgt)
		frappe.db.commit()
		self.assertEqual(frappe.db.get_value("Jarvis Learned Pattern", tgt, "status"), "Proposed")
		learned_api.approve_learned_pattern(tgt)
		frappe.db.commit()

		# 5. batch_approve must refuse any B/C
		bc = [p for p in props if p.effective_sensitivity in ("B", "C") and p.status == "Proposed"]
		if bc:
			with self.assertRaises(frappe.ValidationError):
				learned_api.batch_approve([bc[0].name])

		# 6. compile: only A-class content reaches the pushed body
		bodies = compiler.compile_domain_skills()
		compiled = {
			d: (b.get("body") if isinstance(b, dict) else b) or ""
			for d, b in bodies.items()
		}
		self.assertTrue(any(compiled.values()), "at least one A-class domain must compile a body")
		joined = "\n".join(compiled.values())
		# no stats jargon and no em-dashes in pushed bodies (plan 6.3)
		for banned in ("p-value", "lift=", "Wilson", "—"):
			self.assertNotIn(banned, joined)
		print("[E2E] compiled domains:", {d: len(b) for d, b in compiled.items() if b})

	def test_turn_injection_role_scoped(self):
		"""A managed learned skill injects for a matching role, not for a mismatched one."""
		from jarvis.chat import custom_skills as cs

		# create a managed learned-selling skill scoped to Sales User
		frappe.set_user("Administrator")
		slug = "learned-selling"
		if frappe.db.exists("Jarvis Custom Skill", {"skill_name": slug}):
			frappe.delete_doc("Jarvis Custom Skill", frappe.db.get_value(
				"Jarvis Custom Skill", {"skill_name": slug}, "name"), force=True)
		doc = frappe.get_doc({
			"doctype": "Jarvis Custom Skill",
			"skill_name": slug,
			"description": "Learned selling habits for this org.",
			"instructions": "# Learned selling habits\n- test rule",
			"enabled": 1,
			"user_invocable": 0,
			"managed_by_learning": 1,
			"allowed_roles": [{"role": "Sales User"}],
		})
		doc.flags.ignore_permissions = True
		# This dev bench's Administrator owns ~121 skills (over the per-owner cap);
		# skip the cap validation for this managed fixture. Production Administrator
		# owns ~0, so the real apply path is unaffected. We are testing injection here,
		# not the cap (which has its own coverage in test_compiler).
		doc.flags.ignore_validate = True
		doc.insert()
		frappe.db.commit()
		try:
			clause_fn = getattr(cs, "learned_skill_clause", None)
			self.assertIsNotNone(clause_fn, "learned_skill_clause must exist for turn injection")
			# a user holding Sales User sees the injection - the Phase-2 namespace
			# wire slug learned-<domain> verbatim, never custom-learned-<domain>
			sales_clause = clause_fn(_user_with_role("Sales User"))
			self.assertIn("learned-selling", sales_clause)
			self.assertNotIn("custom-learned-selling", sales_clause)
			# a user without it does not
			acct_clause = clause_fn(_user_with_role("Accounts User"))
			self.assertNotIn("learned-selling", acct_clause)
			print("[E2E] turn injection: sales matched, accounts suppressed")
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("Jarvis Custom Skill", doc.name, force=True)
			frappe.db.commit()


def _user_with_role(role):
	"""Return an existing enabled user holding `role`, or Administrator as a fallback."""
	users = frappe.get_all(
		"Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent", limit=5
	)
	for u in users:
		if u not in ("Administrator", "Guest") and frappe.db.get_value("User", u, "enabled"):
			return u
	# create a throwaway user for the role
	email = f"e2e-{role.lower().replace(' ', '-')}@example.com"
	if not frappe.db.exists("User", email):
		u = frappe.get_doc({
			"doctype": "User", "email": email, "first_name": "E2E",
			"roles": [{"role": role}], "enabled": 1,
		})
		u.flags.ignore_permissions = True
		u.insert()
		frappe.db.commit()
	return email
