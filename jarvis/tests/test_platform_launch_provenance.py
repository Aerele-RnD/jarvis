"""PP-5 — launch-time provenance is STAMPED at run creation, not just guarded.

The Round-4 panel found that ``_launch_audit`` created the ``Jarvis Agent Run``
without ever setting the three immutable launch facts
(``bundle_version`` / ``preparation_mode`` / ``initiating_human``), so they were
always empty in production: ``preparation_mode`` never snapshotted the
installation's ``activation_state``, ``initiating_human`` was unrecoverable on
manual runs, and the controller's set-once guard could never engage because the
stored value was always empty.

These tests launch a REAL run through the shared ``_launch_audit`` path (the
exact path the scheduler and ``run_agent_now`` take) and assert the stamped
values — not merely that the controller guard fires when a value is pre-injected
(that is covered by ``test_platform_writeback``). ``admin_client.post_agent_run``
is stubbed so the dispatch returns without a live fleet, mirroring
``test_agent_identity``.
"""

import unittest

import frappe

from jarvis.chat import agent_catalog, agent_scheduler, agents_api

LISTING = "Jarvis Agent Listing"
INSTALLATION = "Jarvis Agent Installation"
RUN = "Jarvis Agent Run"
SESSION = "Jarvis Chat Session"
AGENT = "close-auditor"


def _ensure_user(email: str, extra_roles: tuple = ()) -> str:
	from jarvis.permissions import ensure_jarvis_user_role

	ensure_jarvis_user_role()
	if not frappe.db.exists("User", email):
		u = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"enabled": 1,
				"user_type": "System User",
			}
		)
		u.flags.ignore_permissions = True
		u.insert()
	frappe.db.set_value("User", email, "enabled", 1, update_modified=False)
	have = set(frappe.get_roles(email))
	want = {"Jarvis User", *extra_roles}
	missing = [r for r in want if r not in have]
	if missing:
		frappe.get_doc("User", email).add_roles(*missing)
	# close-auditor declares doctypes_required (GL Entry / Account / Company); the
	# run-as A12 gate needs the run-as user to hold those reads. Accounts User grants
	# them without conferring Jarvis roles.
	if frappe.db.exists("Role", "Accounts User") and "Accounts User" not in have:
		frappe.get_doc("User", email).add_roles("Accounts User")
	frappe.clear_cache(user=email)
	frappe.db.commit()
	return email


def _install_as(owner: str) -> str:
	original = frappe.session.user
	frappe.set_user(owner)
	try:
		return agents_api.install_agent(AGENT)["data"]["name"]
	finally:
		frappe.set_user(original)


class TestPlatformLaunchProvenance(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		agent_catalog.sync_agent_listings()
		cls.owner = _ensure_user("plp-owner@example.com")
		cls.listing_version = frappe.db.get_value(LISTING, AGENT, "version")

	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup()
		# Stub the fleet dispatch so _launch_audit completes without a live fleet.
		import jarvis.admin_client as admin_client

		self._orig_post = admin_client.post_agent_run
		admin_client.post_agent_run = lambda **kw: {"run_id": kw.get("run_id"), "status": "queued"}

	def tearDown(self):
		import jarvis.admin_client as admin_client

		admin_client.post_agent_run = self._orig_post
		frappe.set_user("Administrator")
		frappe.db.rollback()
		self._cleanup()

	def _cleanup(self):
		frappe.db.delete(
			"Jarvis Agent Allowed Role",
			{"parenttype": LISTING, "parentfield": "allowed_roles"},
		)
		for dt in (RUN, INSTALLATION):
			for n in frappe.get_all(dt, filters={"owner": self.owner}, pluck="name"):
				frappe.delete_doc(dt, n, force=True, ignore_permissions=True)
		for n in frappe.get_all(SESSION, filters={"user": self.owner}, pluck="name"):
			frappe.delete_doc(SESSION, n, force=True, ignore_permissions=True)
		frappe.db.commit()

	# ------------------------------------------------------------------ #
	# A MANUAL launch stamps all three immutable facts (PP-5 acceptance 1)
	# ------------------------------------------------------------------ #
	def test_manual_launch_stamps_all_three_facts(self):
		inst_name = _install_as(self.owner)  # self-map: run_as == owner == triggerer
		frappe.db.set_value(INSTALLATION, inst_name, "enabled", 1, update_modified=False)
		frappe.db.commit()
		inst = frappe.get_doc(INSTALLATION, inst_name)

		frappe.set_user(self.owner)
		try:
			result = agent_scheduler._launch_audit(inst, trigger="manual")
		finally:
			frappe.set_user("Administrator")
		run = result["run"]

		vals = frappe.db.get_value(
			RUN, run, ["bundle_version", "preparation_mode", "initiating_human"], as_dict=True
		)
		# bundle_version is the SNAPSHOT of the installed version (== listing.version
		# at install), stamped even though listing/installation versions are mutable.
		self.assertEqual(vals.bundle_version, inst.installed_version)
		self.assertEqual(vals.bundle_version, self.listing_version)
		# preparation_mode snapshots the installation's activation_state (fresh
		# install is always shadow — PP-4).
		self.assertEqual(vals.preparation_mode, "shadow")
		# initiating_human is the human who triggered the manual run (self-mapped, so
		# the run-as session user IS the triggerer here).
		self.assertEqual(vals.initiating_human, self.owner)

	# ------------------------------------------------------------------ #
	# A SCHEDULED launch stamps bundle/prep but NO initiating_human
	# ------------------------------------------------------------------ #
	def test_scheduled_launch_has_no_initiating_human(self):
		inst_name = _install_as(self.owner)
		frappe.db.set_value(INSTALLATION, inst_name, "enabled", 1, update_modified=False)
		frappe.db.commit()
		inst = frappe.get_doc(INSTALLATION, inst_name)

		# Mirror the scheduler's S1 hinge: the audit is created inside set_user(run_as).
		frappe.set_user(self.owner)
		try:
			result = agent_scheduler._launch_audit(inst, trigger="scheduled")
		finally:
			frappe.set_user("Administrator")
		run = result["run"]

		vals = frappe.db.get_value(
			RUN, run, ["bundle_version", "preparation_mode", "initiating_human"], as_dict=True
		)
		self.assertEqual(vals.bundle_version, inst.installed_version)
		self.assertEqual(vals.preparation_mode, "shadow")
		# No human initiated a cron run.
		self.assertFalse(vals.initiating_human)

	# ------------------------------------------------------------------ #
	# The STAMPED value now engages the controller's set-once guard
	# (the finding: the guard "never even engages because stored is empty")
	# ------------------------------------------------------------------ #
	def test_stamped_bundle_version_is_immutable(self):
		inst_name = _install_as(self.owner)
		frappe.db.set_value(INSTALLATION, inst_name, "enabled", 1, update_modified=False)
		frappe.db.commit()
		inst = frappe.get_doc(INSTALLATION, inst_name)

		frappe.set_user(self.owner)
		try:
			result = agent_scheduler._launch_audit(inst, trigger="manual")
		finally:
			frappe.set_user("Administrator")
		run = result["run"]

		# stored is now NON-empty, so the PP-5 guard engages on an ORM re-save.
		doc = frappe.get_doc(RUN, run)
		doc.bundle_version = "tampered-9.9.9"
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)

	# ------------------------------------------------------------------ #
	# preparation_mode is a SNAPSHOT: a later promotion does not rewrite it
	# ------------------------------------------------------------------ #
	def test_preparation_mode_snapshots_shadow_even_when_installed_state_changes(self):
		inst_name = _install_as(self.owner)
		frappe.db.set_value(INSTALLATION, inst_name, "enabled", 1, update_modified=False)
		frappe.db.commit()
		inst = frappe.get_doc(INSTALLATION, inst_name)

		frappe.set_user(self.owner)
		try:
			result = agent_scheduler._launch_audit(inst, trigger="manual")
		finally:
			frappe.set_user("Administrator")
		run = result["run"]

		self.assertEqual(frappe.db.get_value(RUN, run, "preparation_mode"), "shadow")
		# Even if the installation is later flipped live, the run's stamped snapshot
		# stays shadow (raw set_value on the install; the run field is immutable).
		frappe.db.set_value(INSTALLATION, inst_name, "activation_state", "live", update_modified=False)
		frappe.db.commit()
		self.assertEqual(frappe.db.get_value(RUN, run, "preparation_mode"), "shadow")
