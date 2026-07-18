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
ALLOWED_ROLE = "Jarvis Agent Allowed Role"

ROLE_X = "Jarvis Agent Test Role X"
ROLE_Y = "Jarvis Agent Test Role Y"


def _ensure_role(role_name: str) -> str:
	if not frappe.db.exists("Role", role_name):
		r = frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1})
		r.flags.ignore_permissions = True
		r.insert()
		frappe.db.commit()
	return role_name


def _give_role(email: str, role_name: str) -> None:
	u = frappe.get_doc("User", email)
	if not any(r.role == role_name for r in u.roles):
		u.append("roles", {"role": role_name})
		u.flags.ignore_permissions = True
		u.save()
		frappe.db.commit()


def _ensure_user(email: str) -> str:
	from jarvis.permissions import ensure_jarvis_user_role

	ensure_jarvis_user_role()
	if not frappe.db.exists("User", email):
		u = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"enabled": 1,
			"user_type": "System User",
		})
		u.flags.ignore_permissions = True
		u.insert()
		frappe.db.commit()
	if frappe.db.get_value("User", email, "user_type") != "System User":
		frappe.db.set_value("User", email, "user_type", "System User", update_modified=False)
		frappe.clear_cache(user=email)
	# The agents endpoints are chat-surface: they now require the Jarvis User
	# role (security review TASK 8). Grant it so the fixtures reach the
	# agent-specific allowed_roles / owner gates they actually test.
	if "Jarvis User" not in set(frappe.get_roles(email)):
		frappe.get_doc("User", email).add_roles("Jarvis User")
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
		cls.admin = _ensure_user("agent-admin@example.com")
		_ensure_role(ROLE_X)
		_ensure_role(ROLE_Y)  # assigned to NOBODY — used to revoke access
		_give_role(cls.owner, ROLE_X)
		_give_role(cls.admin, "System Manager")

	def setUp(self):
		frappe.set_user("Administrator")
		# Clean this test's installs/runs/findings so reruns are deterministic.
		for dt in (FINDING, RUN, INSTALLATION):
			for owner in (self.owner, self.other, self.admin):
				for n in frappe.get_all(dt, filters={"owner": owner}, pluck="name"):
					frappe.delete_doc(dt, n, force=True, ignore_permissions=True)
		# Clear any role restriction left by a previous test (bench-admin state).
		frappe.db.delete(ALLOWED_ROLE, {"parenttype": LISTING, "parentfield": "allowed_roles"})
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

	def test_list_findings_returns_redetections_for_each_observing_run(self):
		# Regression: dedupe keeps ONE Finding row per fingerprint (its `run`
		# field stays the FIRST discovering run), so the run drill-down must
		# return the findings each run OBSERVED — matching that run's
		# findings_count — not just the rows it created.
		inst_name = _install_as(self.owner, "audit-auditor")
		frappe.set_user(self.owner)
		try:
			run1 = agent_runs.record_scrutiny_run(inst_name, "manual", None, self._scrutiny_result())
			run2 = agent_runs.record_scrutiny_run(inst_name, "manual", None, self._scrutiny_result())
			for run in (run1, run2):
				res = agents_api.list_findings(run=run.name)
				rows = res["rows"]
				self.assertEqual(len(rows), 2, f"drill-down of {run.name}")
				self.assertEqual(res["total"], 2, f"total for {run.name}")
				self.assertEqual(
					res["total"],
					frappe.db.get_value(RUN, run.name, "findings_count"),
					f"count/drill-down mismatch for {run.name}",
				)
			# A third run observing only ONE finding drills down to exactly it,
			# while the earlier runs' drill-downs are unchanged (history stable).
			only_tb = {"findings": [self._scrutiny_result()["findings"][1]]}
			run3 = agent_runs.record_scrutiny_run(inst_name, "manual", None, only_tb)
			self.assertEqual(
				[r["rule_id"] for r in agents_api.list_findings(run=run3.name)["rows"]], ["R-TB"]
			)
			self.assertEqual(agents_api.list_findings(run=run1.name)["total"], 2)
			self.assertEqual(agents_api.list_findings(run=run2.name)["total"], 2)
			# Unknown run -> zeroed envelope, never an error.
			self.assertEqual(agents_api.list_findings(run="no-such-run")["total"], 0)
		finally:
			frappe.set_user("Administrator")

	def test_run_completion_stamps_installation_last_run_at(self):
		from frappe.utils import now_datetime

		inst_name = _install_as(self.owner, "audit-auditor")
		# Manual-only install: last_run_at stamps on completion; next_run_at
		# must NOT be invented for an unscheduled install.
		frappe.db.set_value(
			INSTALLATION, inst_name,
			{"schedule_enabled": 0, "next_run_at": None, "last_run_at": None},
			update_modified=False,
		)
		frappe.db.commit()
		frappe.set_user(self.owner)
		try:
			agent_runs.record_scrutiny_run(inst_name, "manual", None, self._scrutiny_result())
		finally:
			frappe.set_user("Administrator")
		inst = frappe.db.get_value(
			INSTALLATION, inst_name, ["last_run_at", "next_run_at"], as_dict=True
		)
		self.assertIsNotNone(inst.last_run_at)
		self.assertIsNone(inst.next_run_at)

		# Scheduled install: completion stamps last_run_at AND recomputes a
		# future next_run_at (the scheduler path reaches the same code).
		frappe.db.set_value(
			INSTALLATION, inst_name,
			{
				"schedule_enabled": 1, "schedule_frequency": "daily",
				"schedule_time": "09:00:00", "last_run_at": None,
			},
			update_modified=False,
		)
		frappe.db.commit()
		frappe.set_user(self.owner)
		try:
			agent_runs.record_scrutiny_run(inst_name, "scheduled", None, self._scrutiny_result())
		finally:
			frappe.set_user("Administrator")
		inst = frappe.db.get_value(
			INSTALLATION, inst_name, ["last_run_at", "next_run_at"], as_dict=True
		)
		self.assertIsNotNone(inst.last_run_at)
		self.assertIsNotNone(inst.next_run_at)
		self.assertGreater(inst.next_run_at, now_datetime())

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
		# 7 agents in the registry, all Published.
		self.assertEqual(count2, 7)
		published = frappe.get_all(LISTING, filters={"status": "Published"}, pluck="name")
		# All 7 registry agents are Published as of marketplace v2 (the 3 former
		# Coming-Soon agents shipped: ar-collections, bank-recon, analytical-review).
		self.assertEqual(len(published), 7)
		for slug in published:
			row = frappe.db.get_value(LISTING, slug, ["delivery", "skill_bundle"], as_dict=True)
			bundle = frappe.parse_json(row.skill_bundle) or []
			has_body = any((b or {}).get("body", "").strip() for b in bundle)
			if row.delivery == "delegate":
				# Phase 0A / A2: a delegate agent's SKILL body must NEVER be stored
				# in the customer DB — it lives only in the admin bundle store.
				self.assertFalse(has_body, f"{slug} (delegate) leaked a skill body into the DB")
			else:
				# Legacy agents keep the bundled body for the bench to push.
				self.assertTrue(has_body, f"{slug} (legacy) bundle body empty")

	# ------------------------------------------------------------------ #
	# (d2) Phase 0A — delegate agent stub + body-free enablement signal
	# ------------------------------------------------------------------ #
	def test_delegate_agent_ships_stub_and_enablement_signal(self):
		"""A2 / Phase 0A: a delegate agent's SKILL body NEVER enters the customer
		DB, and its push-payload entry is a body-free ENABLEMENT SIGNAL that the
		admin relay (Phase 2C) routes by ``delivery == 'delegate'`` — carrying
		tools_allow / timeout_s / nature / model looked up from the bundled
		registry, no proprietary body."""
		DELEGATE = "close-auditor"
		# The Listing stub carries the metadata but NOT the body.
		row = frappe.db.get_value(LISTING, DELEGATE, ["delivery", "skill_bundle"], as_dict=True)
		self.assertEqual(row.delivery, "delegate")
		bundle = frappe.parse_json(row.skill_bundle) or []
		self.assertFalse(
			any((b or {}).get("body", "").strip() for b in bundle),
			"delegate agent leaked a SKILL body into the customer DB",
		)

		# Install + enable for an owner who can read what it scans (A12), so the
		# enablement signal is emitted rather than skipped. Accounts User grants
		# read on GL Entry / Account / Company.
		if frappe.db.exists("Role", "Accounts User"):
			_give_role(self.owner, "Accounts User")
		inst = _install_as(self.owner, DELEGATE)
		frappe.db.set_value(INSTALLATION, inst, "enabled", 1)
		frappe.db.commit()

		payload = agent_catalog.build_agent_push_payload(owner=self.owner)
		sig = next(p for p in payload if p["slug"] == f"agent-{DELEGATE}")
		self.assertEqual(sig["delivery"], "delegate")
		self.assertNotIn("body", sig)  # body-free — the whole point
		self.assertEqual(sig["nature"], "auditor")
		self.assertEqual(sig["timeout_s"], 2400)
		self.assertIn("model", sig)  # present (may be None) so 2C can default it
		self.assertIn("exec", sig["tools_allow"])
		self.assertIn("jarvis__get_balance_on", sig["tools_allow"])

	# ------------------------------------------------------------------ #
	# (e) RBAC — role-gated install / run (server-side enforcement)
	# ------------------------------------------------------------------ #
	def _restrict(self, slug: str, roles: list) -> None:
		original = frappe.session.user
		frappe.set_user("Administrator")
		try:
			agents_api.set_agent_roles(slug, roles)
		finally:
			frappe.set_user(original)

	def test_role_gated_install(self):
		self._restrict("audit-auditor", [ROLE_X])

		# User WITHOUT the role: server-side PermissionError, no row created.
		frappe.set_user(self.other)
		try:
			with self.assertRaises(frappe.PermissionError):
				agents_api.install_agent("audit-auditor")
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(
			frappe.db.exists(INSTALLATION, {"owner": self.other, "agent": "audit-auditor"})
		)

		# User WITH the role installs fine.
		inst = _install_as(self.owner, "audit-auditor")
		self.assertTrue(frappe.db.exists(INSTALLATION, inst))

		# A System Manager (who does NOT hold ROLE_X) is always allowed.
		inst_admin = _install_as(self.admin, "audit-auditor")
		self.assertTrue(frappe.db.exists(INSTALLATION, inst_admin))

	def test_role_gated_run_agent_now(self):
		# Install + enable while UNRESTRICTED, then restrict — the run gate must
		# catch an owner whose roles no longer permit the agent.
		inst_other = _install_as(self.other, "audit-auditor")
		frappe.db.set_value(INSTALLATION, inst_other, "enabled", 1)
		inst_owner = _install_as(self.owner, "audit-auditor")
		frappe.db.set_value(INSTALLATION, inst_owner, "enabled", 1)
		frappe.db.commit()
		self._restrict("audit-auditor", [ROLE_X])

		import jarvis.chat.api as chat_api
		calls = []
		orig_send = chat_api.send_message
		chat_api.send_message = lambda **kw: (
			calls.append(frappe.session.user)
			or {"ok": True, "run_id": "x", "message_id": "m", "conversation_id": kw.get("conversation")}
		)
		try:
			# self.other lacks ROLE_X -> refused, and NO turn was dispatched.
			frappe.set_user(self.other)
			with self.assertRaises(frappe.PermissionError):
				agents_api.run_agent_now(inst_other)
			self.assertEqual(calls, [])

			# self.owner holds ROLE_X -> runs.
			frappe.set_user(self.owner)
			result = agents_api.run_agent_now(inst_owner)
			self.assertTrue(result["ok"])
			self.assertEqual(calls, [self.owner])
		finally:
			frappe.set_user("Administrator")
			chat_api.send_message = orig_send

	def test_list_agents_allowed_flags_and_roles_roundtrip(self):
		res = None
		frappe.set_user("Administrator")
		res = agents_api.set_agent_roles("audit-auditor", [ROLE_X])
		self.assertEqual(res["allowed_roles"], [ROLE_X])

		def _row(user):
			frappe.set_user(user)
			try:
				return next(r for r in agents_api.list_agents() if r["name"] == "audit-auditor")
			finally:
				frappe.set_user("Administrator")

		blocked = _row(self.other)
		self.assertEqual(blocked["allowed"], 0)
		self.assertEqual(blocked["allowed_roles"], [ROLE_X])
		permitted = _row(self.owner)
		self.assertEqual(permitted["allowed"], 1)
		sm = _row(self.admin)  # System Manager: always allowed
		self.assertEqual(sm["allowed"], 1)

		# [] clears the restriction -> unrestricted for everyone.
		res = agents_api.set_agent_roles("audit-auditor", [])
		self.assertEqual(res["allowed_roles"], [])
		self.assertEqual(_row(self.other)["allowed"], 1)
		self.assertEqual(_row(self.other)["allowed_roles"], [])

	# ------------------------------------------------------------------ #
	# (f) RBAC — admin endpoints are System Manager ONLY
	# ------------------------------------------------------------------ #
	def test_admin_endpoints_reject_non_system_manager(self):
		frappe.set_user(self.other)
		try:
			with self.assertRaises(frappe.PermissionError):
				agents_api.set_agent_roles("audit-auditor", [ROLE_X])
			with self.assertRaises(frappe.PermissionError):
				agents_api.set_listing_status("audit-auditor", "Deprecated")
			with self.assertRaises(frappe.PermissionError):
				agents_api.get_agent_admin_overview()
		finally:
			frappe.set_user("Administrator")
		# Nothing leaked through: listing untouched.
		self.assertEqual(frappe.db.get_value(LISTING, "audit-auditor", "status"), "Published")
		self.assertEqual(
			frappe.get_all(ALLOWED_ROLE, filters={"parent": "audit-auditor"}, pluck="role"), []
		)

	def test_set_listing_status_valid_and_invalid(self):
		frappe.set_user(self.admin)  # a real SM user, not Administrator
		try:
			res = agents_api.set_listing_status("audit-auditor", "Coming Soon")
			self.assertEqual(res["status"], "Coming Soon")
			self.assertEqual(
				frappe.db.get_value(LISTING, "audit-auditor", "status"), "Coming Soon"
			)
			with self.assertRaises(frappe.ValidationError):
				agents_api.set_listing_status("audit-auditor", "Draft")  # registry-only
			with self.assertRaises(frappe.ValidationError):
				agents_api.set_listing_status("audit-auditor", "bogus")
		finally:
			frappe.set_user("Administrator")
			agents_api.set_listing_status("audit-auditor", "Published")  # restore

	def test_get_agent_admin_overview_shape(self):
		inst = _install_as(self.owner, "audit-auditor")
		frappe.set_user("Administrator")
		agents_api.set_agent_roles("audit-auditor", [ROLE_X])

		frappe.set_user(self.admin)
		try:
			out = agents_api.get_agent_admin_overview()
		finally:
			frappe.set_user("Administrator")

		for excluded in ("Administrator", "Guest", "All"):
			self.assertNotIn(excluded, out["roles"])
		self.assertIn(ROLE_X, out["roles"])

		row = next(l for l in out["listings"] if l["agent_slug"] == "audit-auditor")
		self.assertEqual(row["allowed_roles"], [ROLE_X])
		self.assertEqual(row["status"], "Published")
		install_row = next(i for i in row["installs"] if i["installation"] == inst)
		self.assertEqual(install_row["owner"], self.owner)
		for key in (
			"enabled", "schedule_enabled", "schedule_frequency",
			"next_run_at", "last_run_at", "sync_status",
		):
			self.assertIn(key, install_row)

	# ------------------------------------------------------------------ #
	# (g) RBAC — scheduler skips an owner whose roles were revoked
	# ------------------------------------------------------------------ #
	def test_scheduler_skips_and_records_when_owner_lost_role(self):
		from frappe.utils import add_days, now_datetime

		inst_name = _install_as(self.owner, "audit-auditor")
		now = now_datetime()
		frappe.db.set_value(
			INSTALLATION,
			inst_name,
			{
				"enabled": 1,
				"schedule_enabled": 1,
				"schedule_frequency": "daily",
				"next_run_at": add_days(now, -1),
			},
		)
		frappe.db.commit()
		# ROLE_Y is held by NOBODY -> the owner's roles no longer permit the agent.
		self._restrict("audit-auditor", [ROLE_Y])

		# Insulate from any OTHER due installation on this (dev) site: push their
		# slots out and restore afterwards, so the cron run only touches ours.
		parked = {
			r.name: r.next_run_at
			for r in frappe.get_all(
				INSTALLATION,
				filters={
					"enabled": 1, "schedule_enabled": 1,
					"next_run_at": ["<=", now], "name": ["!=", inst_name],
				},
				fields=["name", "next_run_at"],
			)
		}
		for n in parked:
			frappe.db.set_value(INSTALLATION, n, "next_run_at", add_days(now, 2), update_modified=False)
		frappe.db.commit()

		import jarvis.chat.api as chat_api
		calls = []
		orig_send = chat_api.send_message
		chat_api.send_message = lambda **kw: calls.append(kw) or {"ok": True}
		try:
			agent_scheduler.run_due_agent_audits()
		finally:
			chat_api.send_message = orig_send
			for n, ts in parked.items():
				frappe.db.set_value(INSTALLATION, n, "next_run_at", ts, update_modified=False)
			frappe.db.commit()

		# NO turn was dispatched.
		self.assertEqual(calls, [])
		# A failed run records WHY, owned by the installation owner.
		runs = frappe.get_all(
			RUN,
			filters={"installation": inst_name, "status": "failed"},
			fields=["owner", "error"],
		)
		self.assertEqual(len(runs), 1)
		self.assertEqual(runs[0]["owner"], self.owner)
		self.assertIn("roles no longer permit", runs[0]["error"])
		# The slot was consumed: next_run_at advanced into the future.
		inst = frappe.db.get_value(
			INSTALLATION, inst_name, ["next_run_at", "last_run_at"], as_dict=True
		)
		self.assertIsNotNone(inst.last_run_at)
		self.assertGreater(inst.next_run_at, now)

	# ------------------------------------------------------------------ #
	# (h) RBAC — sync preserves admin roles; push payload excludes blocked
	# ------------------------------------------------------------------ #
	def test_sync_agent_listings_preserves_allowed_roles(self):
		self._restrict("audit-auditor", [ROLE_X])
		agent_catalog.sync_agent_listings()  # re-sync from the bundled registry
		roles = frappe.get_all(
			ALLOWED_ROLE,
			filters={"parenttype": LISTING, "parent": "audit-auditor"},
			pluck="role",
		)
		self.assertEqual(roles, [ROLE_X])
		# ... while registry-owned fields WERE re-synced (still Published).
		self.assertEqual(frappe.db.get_value(LISTING, "audit-auditor", "status"), "Published")

	def test_push_payload_excludes_install_of_blocked_owner(self):
		inst_name = _install_as(self.owner, "audit-auditor")
		frappe.db.set_value(INSTALLATION, inst_name, "enabled", 1)
		frappe.db.commit()

		payload = agent_catalog.build_agent_push_payload(owner=self.owner)
		self.assertTrue(any(p["slug"] == "agent-audit-auditor" for p in payload))

		self._restrict("audit-auditor", [ROLE_Y])  # owner does NOT hold ROLE_Y
		payload = agent_catalog.build_agent_push_payload(owner=self.owner)
		self.assertEqual(payload, [])

		self._restrict("audit-auditor", [])  # clear -> included again
		payload = agent_catalog.build_agent_push_payload(owner=self.owner)
		self.assertTrue(any(p["slug"] == "agent-audit-auditor" for p in payload))
