"""Jarvis Agent Installation DocType controller.

One row per (owner, agent) — a customer user installing a marketplace agent.
Owner-scoped (``if_owner`` permission), exactly like ``Jarvis Custom Skill``.
Enabling / scheduling is a pure DB write (no container restart); the bundle is
only pushed to the container on an explicit Apply
(``jarvis.chat.agents_api.apply_agents``).

All validation lives here so it runs on every insert/save regardless of whether
the write came from the SPA, the Desk, or a test — mirroring
``jarvis_custom_skill.py``.
"""

import frappe
from frappe import _
from frappe.model.document import Document

LISTING = "Jarvis Agent Listing"

# Per-owner install cap, mirroring jarvis_custom_skill._validate_owner_cap.
MAX_INSTALLS_PER_OWNER = 20

# GL-linked dimensions (OTHER than Company) whose User Permissions silently
# record-scope aggregates BEFORE they are summed — so a run_as_user carrying one
# would compute a numerically WRONG total (a false "TB out by X" blocker, wrong
# party balances, flipped YoY). Detected at mapping time -> scoped_visibility=1
# (A12). Company is deliberately excluded: the audit is already company-scoped,
# so a Company User Permission is a scoping consistency, not a slice.
_GL_SCOPED_DIMENSIONS = (
	"Account",
	"Cost Center",
	"Project",
	"Fiscal Year",
	"Finance Book",
	"Customer",
	"Supplier",
	"Employee",
	"Shareholder",
)


class JarvisAgentInstallation(Document):
	def validate(self):
		self._validate_unique_per_owner()
		self._validate_owner_cap()
		self._validate_run_as_user()
		self._validate_schedule_budget()

	def on_update(self):
		self._audit_cross_user_run_as()

	def _validate_schedule_budget(self):
		"""A14: warn (do not hard-block) when an enabled schedule's expected monthly
		runs exceed the per-installation run budget — the run would be starved
		mid-month, so surface it at configuration time rather than as a silent
		month-long outage. A msgprint (not a throw) keeps daily/weekly saves working
		while flagging a budget that a bench admin set too low."""
		if not self.get("schedule_enabled"):
			return
		from jarvis.chat.agent_scheduler import (
			_agent_run_budget_monthly, _expected_monthly_runs,
		)

		expected = _expected_monthly_runs(self.get("schedule_frequency"))
		budget = _agent_run_budget_monthly()
		if expected > budget:
			frappe.msgprint(
				_(
					"This {0} schedule expects up to {1} runs/month but the agent run "
					"budget is {2}; later runs this month will be skipped until the "
					"budget is raised in Jarvis Settings."
				).format(self.get("schedule_frequency") or "daily", expected, budget),
				indicator="orange",
				alert=True,
			)

	def _audit_cross_user_run_as(self):
		"""FIX 10 / A4: audit EVERY cross-user run_as mapping, on ANY write surface —
		Desk form, data import, bulk edit, direct ``doc.save()``, not just the SPA
		``set_run_as_user`` endpoint. The escalation GUARD is in validate() (holds
		everywhere); this makes the AUDIT hold everywhere too, so the exact authority
		residual A4 requires to be traceable can never occur untraced. Fires only when
		run_as_user CHANGES to someone OTHER than the setter (a self-map is not an
		escalation); the Link-free Data activity row survives the uninstall cascade."""
		target = (self.run_as_user or "").strip()
		setter = frappe.session.user
		if not target or target == setter:
			return
		before = self.get_doc_before_save()
		old = ((before.run_as_user or "").strip()) if before else ""
		if old == target:
			return  # unchanged mapping — an incidental save, already audited when set
		from jarvis.chat.agent_activity import log_activity

		log_activity(
			agent=self.agent,
			agent_title=frappe.db.get_value(LISTING, self.agent, "title"),
			installation=self.name,
			action="run_as_changed",
			detail=f"run as {target} (set by {setter})"
			+ (" (scoped visibility)" if self.get("scoped_visibility") else ""),
			owner=self.owner,
		)

	def _validate_unique_per_owner(self):
		# One install of a given agent per owner. Frappe has no composite-unique
		# on (owner, agent), so enforce it here (an owner re-installing the same
		# agent must reuse / re-enable the existing row).
		owner = self.owner or frappe.session.user
		clash = frappe.db.exists(
			"Jarvis Agent Installation",
			{"owner": owner, "agent": self.agent, "name": ["!=", self.name or ""]},
		)
		if clash:
			frappe.throw(_("You have already installed this agent."))

	def _validate_owner_cap(self):
		if not self.is_new():
			return
		owner = self.owner or frappe.session.user
		count = frappe.db.count("Jarvis Agent Installation", {"owner": owner})
		if count >= MAX_INSTALLS_PER_OWNER:
			frappe.throw(
				_("You can have at most {0} installed agents.").format(MAX_INSTALLS_PER_OWNER)
			)

	# ------------------------------------------------------------------ #
	# run_as_user — the moat's second half (A4 escalation + A12 perms).
	#
	# This runs on EVERY insert/save regardless of write surface (SPA / Desk /
	# test), so it — not the API layer — is the authoritative escalation guard:
	# the bench trusts the per-run Jarvis Chat Session row and enforces NOTHING
	# at call_tool, so install-time is the only place a low-priv installer can be
	# stopped from mapping the agent to run as a high-priv user (data exfil).
	# ------------------------------------------------------------------ #
	def _validate_run_as_user(self):
		target = (self.run_as_user or "").strip()
		if not target:
			# reqd:1 also enforces this; the explicit throw keeps the escalation
			# block below from ever running against a None.
			frappe.throw(_("Run-as user is required."))

		# Only re-litigate the mapping when it is actually being (re)assigned.
		# An unrelated save (enable / schedule / config) on a row whose
		# run_as_user is unchanged must not be blocked just because, e.g., an
		# admin earlier mapped it cross-user — and perms drift is re-checked at
		# each run's session-mint, not on every incidental write.
		if not self.is_new():
			old = frappe.db.get_value("Jarvis Agent Installation", self.name, "run_as_user")
			if old and old == target:
				return

		# Existence + enabled + never Administrator/Guest — reuse the exact
		# fail-closed shape the scheduler applies at run time.
		from jarvis.chat.agent_scheduler import _valid_owner

		if not _valid_owner(target):
			frappe.throw(
				_("Run-as user must be an existing, enabled, non-system user.")
			)

		self._validate_run_as_escalation(target)
		self._validate_run_as_permissions(target)

	def _validate_run_as_escalation(self, target: str) -> None:
		"""A4: a non-admin setter may map ONLY to themselves; any cross-user
		mapping needs Jarvis Admin (``has_jarvis_admin_access`` — SM or Jarvis
		Admin, never an invented permission); binding to a System Manager
		additionally requires the setter BE a System Manager."""
		from jarvis.permissions import has_jarvis_admin_access

		setter = frappe.session.user
		if target != setter and not has_jarvis_admin_access(setter):
			frappe.throw(
				_("You may only set this agent to run as yourself."),
				frappe.PermissionError,
			)
		target_is_sm = "System Manager" in frappe.get_roles(target)
		setter_is_sm = setter == "Administrator" or "System Manager" in frappe.get_roles(setter)
		if target_is_sm and not setter_is_sm:
			frappe.throw(
				_("Only a System Manager may map an agent to run as a System Manager."),
				frappe.PermissionError,
			)

	def _validate_run_as_permissions(self, target: str) -> None:
		"""A12: the EXECUTING identity must actually be able to read what the
		agent scans (a sliced aggregate is numerically wrong, not just narrower).
		Require ``target`` read on every declared ``doctypes_required``
		(fail-closed on a missing read); detect a GL-dimension User Permission and
		stamp ``scoped_visibility`` (a flag + message for now, not a hard refuse)."""
		for dt in self._required_doctypes():
			if not frappe.has_permission(dt, "read", user=target):
				frappe.throw(
					_(
						"Run-as user {0} lacks read access to {1}, which this agent requires."
					).format(target, dt)
				)
		self.scoped_visibility = 1 if self._detect_scoped_visibility(target) else 0

	def _required_doctypes(self) -> list[str]:
		raw = frappe.db.get_value(LISTING, self.agent, "doctypes_required")
		try:
			vals = frappe.parse_json(raw) if raw else []
		except Exception:
			vals = []
		# Guard has_permission against a bogus catalog entry; a non-existent
		# required doctype is a bundle-authoring bug, not a user-perm failure.
		return [
			d for d in vals
			if isinstance(d, str) and d.strip() and frappe.db.exists("DocType", d.strip())
		]

	def _detect_scoped_visibility(self, target: str) -> bool:
		from frappe.permissions import get_user_permissions

		try:
			perms = get_user_permissions(target) or {}
		except Exception:
			return False
		return any(dt in perms for dt in _GL_SCOPED_DIMENSIONS)
