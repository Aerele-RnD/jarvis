"""Unit tests for ``user_can_use_skill`` (pattern-learning plan section 6.6).

Pure-logic tests: the helper accepts any dict-like row, and passing the child
tables + ``user_roles`` explicitly keeps these independent of the
``allowed_roles`` schema being migrated (Wave C wires the helper into the
listing/turn paths and adds the DB-backed integration coverage).
"""

import contextlib

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.custom_skills import learned_skill_clause
from jarvis.jarvis.doctype.jarvis_custom_skill.jarvis_custom_skill import user_can_use_skill

OWNER = "skill-owner@example.com"
PEER = "skill-peer@example.com"
STRANGER = "skill-stranger@example.com"
NONSM = "jcs-sec-nonsm@example.com"


@contextlib.contextmanager
def _as(user: str):
	orig = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(orig)


@contextlib.contextmanager
def _engine_flag():
	prev = frappe.flags.jarvis_pattern_engine
	frappe.flags.jarvis_pattern_engine = True
	try:
		yield
	finally:
		frappe.flags.jarvis_pattern_engine = prev


def _ensure_non_sm(email: str) -> str:
	"""A logged-in user with no System Manager role (created inside the test
	transaction, so it is rolled back with everything else)."""
	if not frappe.db.exists("User", email):
		u = frappe.get_doc({
			"doctype": "User", "email": email,
			"first_name": "jcs-sec", "send_welcome_email": 0, "enabled": 1,
		})
		u.flags.ignore_permissions = True
		u.insert(ignore_permissions=True)
	if "System Manager" in set(frappe.get_roles(email)):
		frappe.get_doc("User", email).remove_roles("System Manager")
	return email


def _skill(**overrides):
	row = frappe._dict(
		name="jcs-visibility-test",
		owner=OWNER,
		shared_with=[],
		allowed_roles=[],
	)
	row.update(overrides)
	return row


class TestUserCanUseSkill(FrappeTestCase):
	def test_owner_passes_despite_role_mismatch(self):
		skill = _skill(allowed_roles=[{"role": "Sales User"}])
		self.assertTrue(user_can_use_skill(skill, OWNER, ["All"]))

	def test_shared_with_passes_despite_role_mismatch(self):
		skill = _skill(
			shared_with=[{"user": PEER}],
			allowed_roles=[{"role": "Sales User"}],
		)
		self.assertTrue(user_can_use_skill(skill, PEER, ["All"]))

	def test_empty_allowed_roles_means_everyone(self):
		self.assertTrue(user_can_use_skill(_skill(), STRANGER, ["All"]))

	def test_role_intersection_passes(self):
		skill = _skill(allowed_roles=[{"role": "Sales User"}, {"role": "Stock User"}])
		self.assertTrue(user_can_use_skill(skill, STRANGER, ["All", "Stock User"]))

	def test_role_mismatch_fails(self):
		skill = _skill(allowed_roles=[{"role": "Sales User"}])
		self.assertFalse(user_can_use_skill(skill, STRANGER, ["All", "Accounts User"]))

	def test_system_manager_always_passes(self):
		skill = _skill(allowed_roles=[{"role": "Sales User"}])
		self.assertTrue(user_can_use_skill(skill, "sm@example.com", ["System Manager"]))

	def test_administrator_always_passes(self):
		skill = _skill(allowed_roles=[{"role": "Sales User"}])
		self.assertTrue(user_can_use_skill(skill, "Administrator"))

	def test_child_rows_as_objects_and_strings(self):
		# Document child rows (attribute access) and pre-plucked strings both work.
		class Row:
			def __init__(self, role):
				self.role = role

		skill = _skill(allowed_roles=[Row("Stock User")])
		self.assertTrue(user_can_use_skill(skill, STRANGER, ["Stock User"]))
		skill = _skill(allowed_roles=["Stock User"])
		self.assertTrue(user_can_use_skill(skill, STRANGER, ["Stock User"]))
		self.assertFalse(user_can_use_skill(skill, STRANGER, ["Sales User"]))


class TestManagedFlagSecurity(FrappeTestCase):
	"""``managed_by_learning`` self-escalation guards (plan section 6.6 security).

	The compiler owns ``managed_by_learning`` and the ``learned-`` slug namespace;
	a normal author must not be able to forge either and have their row auto-
	injected into every user's turn by ``learned_skill_clause``.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.non_sm = _ensure_non_sm(NONSM)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _new(self, **kw):
		doc = frappe.new_doc("Jarvis Custom Skill")
		doc.update({
			"skill_name": kw.pop("skill_name", "jcs-sec-skill"),
			"description": "security fixture",
			"instructions": "body",
			"enabled": 1,
			"user_invocable": 0,
		})
		doc.update(kw)
		return doc

	def test_non_sm_cannot_set_managed_flag(self):
		# A non-SM author flipping managed_by_learning=1 on their OWN row is the
		# rejected escalation - validate() must throw before it can be injected.
		with _as(self.non_sm):
			doc = self._new(skill_name="jcs-sec-managed", managed_by_learning=1)
			with self.assertRaises(frappe.PermissionError):
				doc.insert()

	def test_non_admin_cannot_author_learned_slug(self):
		with _as(self.non_sm):
			doc = self._new(skill_name="learned-selling")
			with self.assertRaises(frappe.ValidationError):
				doc.insert()

	def test_engine_and_admin_can_author_learned_slug(self):
		# Engine flag: a real insert of learned-<domain> goes through (a fresh
		# owner keeps us under the per-owner cap; the production Administrator
		# owner is ~0 so the real compiler apply is likewise clear).
		with _as(self.non_sm), _engine_flag():
			doc = self._new(skill_name="learned-e2esec", managed_by_learning=1)
			doc.insert(ignore_permissions=True)
			self.assertTrue(frappe.db.exists("Jarvis Custom Skill", doc.name))
		# Administrator: the slug reservation is lifted even without the engine
		# flag. Checked in isolation so this dev site's >25 Administrator-owned
		# rows (the per-owner cap) cannot mask the reservation behaviour; a bare
		# _validate_slug() call raises nothing on success.
		with _as("Administrator"):
			self._new(skill_name="learned-admincheck")._validate_slug()

	def test_learned_clause_ignores_non_admin_managed_row(self):
		# Even force-set with the engine flag, a non-Administrator-owned managed
		# row is never injected: the clause query is pinned to owner=Administrator.
		with _as(self.non_sm), _engine_flag():
			doc = self._new(skill_name="learned-rogue", managed_by_learning=1)
			doc.insert(ignore_permissions=True)
		self.assertEqual(doc.owner, self.non_sm)
		self.assertNotIn("learned-rogue", learned_skill_clause(self.non_sm))
		self.assertNotIn("learned-rogue", learned_skill_clause("Administrator"))
