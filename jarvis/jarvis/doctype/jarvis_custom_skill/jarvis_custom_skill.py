"""Jarvis Custom Skill DocType controller.

One row per customer-authored skill. Each row renders to a SKILL.md that is
pushed into the customer's openclaw container (under ``openclaw_state/
custom_skills/custom-<slug>/SKILL.md``) and loaded ALONGSIDE the shared
read-only persona skills. Rows are owned by the Frappe user who created them
(``if_owner`` permission); the push itself is bench-global (a Jarvis bench maps
to one customer / one container) and is triggered explicitly via
``jarvis.chat.custom_skills_api.apply_custom_skills``.

All the user-facing validation lives here so it runs on every insert/save
regardless of whether the write came from the SPA, the Desk, or a test.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document

# A skill_name is a bare slug the customer authors (e.g. "invoicing"). It is
# lowercased and must be hyphen-separated alphanumerics. Everywhere it reaches
# openclaw it is prefixed with ``custom-`` (see chat/custom_skills.py) so it can
# never collide with a shared persona skill name.
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MIN_SLUG_LEN = 3
MAX_SLUG_LEN = 40
MAX_DESC_LEN = 500
MAX_INSTR_LEN = 20000
MAX_SKILLS_PER_OWNER = 25
RESERVED_PREFIX = "custom-"


class JarvisCustomSkill(Document):
	def validate(self):
		self._validate_slug()
		self._validate_lengths()
		self._validate_unique_per_owner()
		self._validate_owner_cap()

	def _validate_slug(self):
		self.skill_name = (self.skill_name or "").strip().lower()
		if not self.skill_name:
			frappe.throw(_("Skill name is required."))
		if self.skill_name.startswith(RESERVED_PREFIX):
			frappe.throw(
				_("Skill name must not start with '{0}' (added automatically).").format(
					RESERVED_PREFIX
				)
			)
		if not (MIN_SLUG_LEN <= len(self.skill_name) <= MAX_SLUG_LEN):
			frappe.throw(
				_("Skill name must be {0}-{1} characters.").format(
					MIN_SLUG_LEN, MAX_SLUG_LEN
				)
			)
		if not SLUG_RE.fullmatch(self.skill_name):
			frappe.throw(
				_(
					"Skill name may only contain lowercase letters, digits and "
					"single hyphens (e.g. 'monthly-close')."
				)
			)

	def _validate_lengths(self):
		self.description = (self.description or "").strip()
		self.instructions = (self.instructions or "").strip()
		if not self.description:
			frappe.throw(_("Description is required."))
		if not self.instructions:
			frappe.throw(_("Instructions are required."))
		if len(self.description) > MAX_DESC_LEN:
			frappe.throw(_("Description must be at most {0} characters.").format(MAX_DESC_LEN))
		if len(self.instructions) > MAX_INSTR_LEN:
			frappe.throw(
				_("Instructions must be at most {0} characters.").format(MAX_INSTR_LEN)
			)

	def _validate_unique_per_owner(self):
		# Frappe's field-level ``unique`` is global, not per-owner; enforce
		# (owner, skill_name) uniqueness here so two customers can both have a
		# skill named "invoicing".
		owner = self.owner or frappe.session.user
		clash = frappe.db.exists(
			"Jarvis Custom Skill",
			{
				"owner": owner,
				"skill_name": self.skill_name,
				"name": ["!=", self.name or ""],
			},
		)
		if clash:
			frappe.throw(_("You already have a skill named '{0}'.").format(self.skill_name))

	def _validate_owner_cap(self):
		if not self.is_new():
			return
		owner = self.owner or frappe.session.user
		count = frappe.db.count("Jarvis Custom Skill", {"owner": owner})
		if count >= MAX_SKILLS_PER_OWNER:
			frappe.throw(
				_("You can have at most {0} custom skills.").format(MAX_SKILLS_PER_OWNER)
			)
