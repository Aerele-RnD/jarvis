"""Integration tests for the Agents Marketplace backend (B3).

The load-bearing test is the scheduler-identity regression (S1): a scheduled
audit's conversation is owned by the installation owner and NEVER Administrator
— the single most important control (a scheduled turn otherwise runs jarvis__*
tools as Administrator, bypassing every DocType permission, silently). The rest
cover mutation authZ (S3), the deterministic Run+Findings persistence with
dedupe (O2), and catalog-sync idempotency.
"""
import unittest

import frappe

from jarvis.chat import agent_catalog, agent_runs, agent_scheduler, agents_api

LISTING = "Jarvis Agent Listing"
INSTALLATION = "Jarvis Agent Installation"
RUN = "Jarvis Agent Run"
FINDING = "Jarvis Agent Finding"


def _ensure_user(email: str) -> str:
	if not frappe.db.exists("User", email):
		u = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"enabled": 1,
		})
		u.flags.ignore_permissions = True
		u.insert()
		frappe.db.commit()
	return email


def _install_as(owner: str, agent_slug: str) -> str:
	"""Create an installation owned by ``owner`` (running as that user so the
	if_owner rows land correctly)."""
	original = frappe.session.user
	frappe.set_user(owner)
	try:
		res = agents_api.install_agent(agent_slug)
		return res["data"]["name"]
	finally:
		frappe.set_user(original)


class TestAgentsMarketplace(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		agent_catalog.sync_agent_listings()
		cls.owner = _ensure_user("agent-owner@example.com")
		cls.other = _ensure_user("agent-other@example.com")

	def setUp(self):
		frappe.set_user("Administrator")
		# Clean this test's installs/runs/findings so reruns are deterministic.
		for dt in (FINDING, RUN, INSTALLATION):
			for owner in (self.owner, self.other):
				for n in frappe.get_all(dt, filters={"owner": owner}, pluck="name"):
					frappe.delete_doc(dt, n, force=True, ignore_permissions=True)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------ #
	# (a) THE scheduler-identity regression test (S1)
	# ------------------------------------------------------------------ #
	def test_scheduled_run_owner_is_installation_owner_never_administrator(self):
		inst_name = _install_as(self.owner, "audit-auditor")
		frappe.db.set_value(INSTALLATION, inst_name, "enabled", 1)
		frappe.db.commit()
		inst = frappe.get_doc(INSTALLATION, inst_name)

		# Drive the scheduler's exact launch path AS the owner (what
		# run_due_agent_audits does inside set_user(owner)). Stub the turn
		# dispatch so no real openclaw/RQ is needed.
		import jarvis.chat.api as chat_api
		orig_send = chat_api.send_message
		chat_api.send_message = lambda **kw: {"ok": True, "run_id": "x", "message_id": "m", "conversation_id": kw.get("conversation")}
		original_user = frappe.session.user
		try:
			frappe.set_user(self.owner)
			result = agent_scheduler._launch_audit(inst, trigger="scheduled")
		finally:
			frappe.set_user(original_user)
			chat_api.send_message = orig_send

		conv = result["conversation"]
		run = result["run"]
		conv_owner = frappe.db.get_value("Jarvis Conversation", conv, "owner")
		run_owner = frappe.db.get_value(RUN, run, "owner")
		self.assertEqual(conv_owner, self.owner)
		self.assertNotEqual(conv_owner, "Administrator")
		self.assertEqual(run_owner, self.owner)
		self.assertNotEqual(run_owner, "Administrator")

	def test_fail_closed_guard_rejects_administrator_owner(self):
		# The identity guard must refuse Administrator / Guest / disabled users.
		self.assertFalse(agent_scheduler._valid_owner("Administrator"))
		self.assertFalse(agent_scheduler._valid_owner("Guest"))
		self.assertTrue(agent_scheduler._valid_owner(self.owner))

	def test_run_agent_now_executes_as_owner_not_triggering_admin(self):
		# A System Manager (Administrator) triggering ANOTHER owner's audit must
		# dispatch the turn under the OWNER's identity — so jarvis__* tool calls
		# are scoped to the owner's permissions, not the admin's (the manual-path
		# analogue of the S1 scheduler hinge).
		inst_name = _install_as(self.owner, "audit-auditor")
		frappe.db.set_value(INSTALLATION, inst_name, "enabled", 1)
		frappe.db.commit()

		import jarvis.chat.api as chat_api
		captured = {}
		orig_send = chat_api.send_message

		def _cap(**kw):
			captured["user"] = frappe.session.user
			return {"ok": True, "run_id": "x", "message_id": "m", "conversation_id": kw.get("conversation")}

		chat_api.send_message = _cap
		original_user = frappe.session.user
		try:
			frappe.set_user("Administrator")  # a System Manager triggers someone else's audit
			result = agents_api.run_agent_now(inst_name)
		finally:
			frappe.set_user(original_user)
			chat_api.send_message = orig_send

		# The turn was dispatched while the session was the OWNER, not Administrator.
		self.assertEqual(captured.get("user"), self.owner)
		conv_owner = frappe.db.get_value("Jarvis Conversation", result["data"]["conversation"], "owner")
		self.assertEqual(conv_owner, self.owner)
		self.assertNotEqual(conv_owner, "Administrator")

	# ------------------------------------------------------------------ #
	# (b) mutation authZ (S3)
	# ------------------------------------------------------------------ #
	def test_non_owner_cannot_set_enabled_another_owners_install(self):
		inst_name = _install_as(self.owner, "audit-auditor")
		original_user = frappe.session.user
		frappe.set_user(self.other)
		try:
			with self.assertRaises(frappe.PermissionError):
				agents_api.set_enabled(inst_name, 1)
		finally:
			frappe.set_user(original_user)
		# The install stays disabled — the non-owner write never landed.
		self.assertEqual(int(frappe.db.get_value(INSTALLATION, inst_name, "enabled")), 0)

	# ------------------------------------------------------------------ #
	# (c) record_scrutiny_run — Run + Findings with dedupe (O2)
	# ------------------------------------------------------------------ #
	def _scrutiny_result(self):
		return {
			"findings": [
				{
					"rule_id": "R-DORMANT", "severity": "warning",
					"statement": "Dormant creditor balance", "detail": "Supplier X: 50000",
					"ref_doctype": "Supplier", "ref_name": "Supplier X", "amount": 50000,
				},
				{
					"rule_id": "R-TB", "severity": "blocker",
					"statement": "Trial balance out", "detail": "out by 12.00",
					"ref_doctype": "Company", "ref_name": "Acme", "amount": 12,
				},
			]
		}

	def test_record_scrutiny_run_creates_run_and_findings_with_dedupe(self):
		inst_name = _install_as(self.owner, "audit-auditor")
		frappe.set_user(self.owner)
		try:
			# First run: two findings, both new + open.
			run1 = agent_runs.record_scrutiny_run(inst_name, "manual", None, self._scrutiny_result())
			self.assertEqual(run1.status, "completed")
			self.assertEqual(run1.findings_count, 2)
			self.assertEqual(run1.blocker_count, 1)
			open1 = frappe.get_all(FINDING, filters={"owner": self.owner, "state": "open"}, fields=["name", "fingerprint", "first_seen_run", "last_seen_run"])
			self.assertEqual(len(open1), 2)

			# Second run: SAME findings -> no new open rows; last_seen_run bumped.
			run2 = agent_runs.record_scrutiny_run(inst_name, "manual", None, self._scrutiny_result())
			open2 = frappe.get_all(FINDING, filters={"owner": self.owner, "state": "open"}, pluck="name")
			self.assertEqual(len(open2), 2)  # deduped — still two, not four
			dormant = frappe.get_all(
				FINDING,
				filters={"owner": self.owner, "rule_id": "R-DORMANT", "state": "open"},
				fields=["first_seen_run", "last_seen_run"],
			)[0]
			self.assertEqual(dormant["first_seen_run"], run1.name)  # unchanged
			self.assertEqual(dormant["last_seen_run"], run2.name)   # bumped

			# Third run: only the TB finding -> the dormant one auto-resolves.
			only_tb = {"findings": [self._scrutiny_result()["findings"][1]]}
			agent_runs.record_scrutiny_run(inst_name, "manual", None, only_tb)
			resolved = frappe.get_all(FINDING, filters={"owner": self.owner, "rule_id": "R-DORMANT"}, fields=["state"])[0]
			self.assertEqual(resolved["state"], "resolved")
			still_open = frappe.get_all(FINDING, filters={"owner": self.owner, "state": "open"}, pluck="name")
			self.assertEqual(len(still_open), 1)  # only TB remains open
		finally:
			frappe.set_user("Administrator")

	def test_partial_when_truncated(self):
		inst_name = _install_as(self.owner, "audit-auditor")
		frappe.set_user(self.owner)
		try:
			run = agent_runs.record_scrutiny_run(inst_name, "scheduled", None, self._scrutiny_result(), truncated=True)
			self.assertEqual(run.status, "partial")
			self.assertTrue(run.coverage_note)
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------------------------------ #
	# (d) catalog sync idempotency
	# ------------------------------------------------------------------ #
	def test_sync_agent_listings_idempotent(self):
		r1 = agent_catalog.sync_agent_listings()
		count1 = frappe.db.count(LISTING)
		r2 = agent_catalog.sync_agent_listings()
		count2 = frappe.db.count(LISTING)
		self.assertEqual(count1, count2)  # no dup rows on re-sync
		self.assertEqual(r2["created"], 0)  # nothing created the second time
		# 7 domains in the registry; 4 Published with a non-empty skill bundle.
		self.assertEqual(count2, 7)
		published = frappe.get_all(LISTING, filters={"status": "Published"}, pluck="name")
		self.assertEqual(len(published), 4)
		for slug in published:
			bundle = frappe.parse_json(frappe.db.get_value(LISTING, slug, "skill_bundle")) or []
			self.assertTrue(bundle and bundle[0].get("body", "").strip(), f"{slug} bundle body empty")
