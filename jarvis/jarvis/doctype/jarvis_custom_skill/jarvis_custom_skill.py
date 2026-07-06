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
# Bare-slug prefix reserved for the learning engine's compiled ``learned-<domain>``
# rows. A normal author is blocked from minting a ``learned-selling`` etc. slug so
# they cannot masquerade as a compiled learned skill; only the compiler (which
# sets ``frappe.flags.jarvis_pattern_engine``) or Administrator may author it.
LEARNED_PREFIX = "learned-"

SKILL_DOCTYPE = "Jarvis Custom Skill"


def _managed_flag_privileged(user: str | None = None) -> bool:
	"""True for writes allowed to touch the engine-owned ``managed_by_learning``
	flag: the compiler (which sets ``frappe.flags.jarvis_pattern_engine``),
	Administrator, or a System Manager. Everyone else is a normal author."""
	if frappe.flags.jarvis_pattern_engine:
		return True
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return "System Manager" in frappe.get_roles(user)


def user_can_use_skill(skill, user: str | None = None, user_roles: list[str] | None = None) -> bool:
	"""Allowed-Roles visibility rule (pattern-learning plan section 6.6).

	A user may see/invoke a skill iff they are the owner, are in
	``shared_with``, ``allowed_roles`` is empty (= everyone), or their roles
	intersect ``allowed_roles``. System Manager (and Administrator) always
	passes. ``skill`` may be a Document or any dict-like row; when the row
	does not carry the child tables (e.g. a ``frappe.get_all`` row) they are
	fetched by parent name. Instruction-level enforcement only - the skill
	files stay readable in the shared container.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	if user_roles is None:
		user_roles = frappe.get_roles(user)
	if "System Manager" in user_roles:
		return True
	if (skill.get("owner") or "") == user:
		return True
	if user in _child_values(skill, "shared_with", "user", "Jarvis Custom Skill Share"):
		return True
	allowed = _child_values(skill, "allowed_roles", "role", "Jarvis Custom Skill Allowed Role")
	if not allowed:
		return True
	return bool(set(allowed) & set(user_roles))


def _child_values(skill, fieldname: str, value_field: str, child_doctype: str) -> list[str]:
	rows = skill.get(fieldname)
	if rows is None:
		# Row without child tables loaded: fall back to a parent lookup.
		parent = skill.get("name")
		if not parent:
			return []
		return frappe.get_all(
			child_doctype,
			filters={"parenttype": SKILL_DOCTYPE, "parent": parent},
			pluck=value_field,
		)
	values = []
	for row in rows:
		value = (
			row
			if isinstance(row, str)
			else (row.get(value_field) if hasattr(row, "get") else getattr(row, value_field, None))
		)
		if value:
			values.append(value)
	return values


class JarvisCustomSkill(Document):
	def validate(self):
		self._validate_slug()
		self._validate_lengths()
		self._validate_unique_per_owner()
		self._validate_owner_cap()
		self._guard_managed_flag()

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
		# ``learned-`` is engine-only: the compiler authors ``learned-<domain>``
		# rows as Administrator under the engine flag; block every other author so
		# a customer cannot forge a skill that looks compiler-managed.
		if self.skill_name.startswith(LEARNED_PREFIX) and not (
			frappe.flags.jarvis_pattern_engine or frappe.session.user == "Administrator"
		):
			frappe.throw(
				_(
					"Skill name must not start with '{0}' (reserved for skills the "
					"learning engine manages)."
				).format(LEARNED_PREFIX)
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

	def _guard_managed_flag(self):
		"""``managed_by_learning`` is engine-owned (plan section 6.6 security).

		Without this guard a non-privileged owner could flip the flag to 1 on
		their OWN row via ``frappe.client.set_value`` / REST (the field carries no
		permlevel), and ``learned_skill_clause`` would then inject that rogue skill
		into EVERY user's chat turn. Only the compiler (engine flag), Administrator
		or a System Manager may set or change it; a normal author is frozen at its
		stored value (0 for their own rows)."""
		if _managed_flag_privileged():
			return
		new_val = 1 if self.managed_by_learning else 0
		before = self.get_doc_before_save()
		old_val = (1 if before.managed_by_learning else 0) if before is not None else 0
		if new_val or new_val != old_val:
			frappe.throw(
				_("Only the learning engine can set 'Managed by Learning'."),
				frappe.PermissionError,
			)
