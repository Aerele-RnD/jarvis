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

# Per-owner install cap, mirroring jarvis_custom_skill._validate_owner_cap.
MAX_INSTALLS_PER_OWNER = 20


class JarvisAgentInstallation(Document):
	def validate(self):
		self._validate_unique_per_owner()
		self._validate_owner_cap()

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
