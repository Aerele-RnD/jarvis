"""Skill tools (find_skills / get_skill / create_custom_skill) + scope plumbing.

DB-backed: rows are created through the real doctype as non-SM System Users
(``frappe.set_user``) so controller validation, the ``user_can_use_skill``
visibility rules and the Personal-scope owner-only rule are exercised for
real. Registry/classification tests import ``jarvis.api`` /
``jarvis.tools.registry`` lazily (inside the test) because the registry
imports every tool module — including the wiki pair built alongside this
feature — at load time.
"""

import contextlib

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.custom_skills import (
	build_push_payload,
	personal_skill_clause,
	personal_skills_cache_key,
	prefixed_slug,
)
from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.create_custom_skill import create_custom_skill
from jarvis.tools.find_skills import find_skills
from jarvis.tools.get_skill import get_skill

SKILL = "Jarvis Custom Skill"
# All fixture slugs share this prefix so leftovers from committed runs are
# swept in setUpClass.
PFX = "sttool"

OWNER = "sttool-owner@example.com"
PEER = "sttool-peer@example.com"
THIRD = "sttool-third@example.com"
WEB = "sttool-web@example.com"


@contextlib.contextmanager
def _as(user: str):
	orig = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(orig)


def _ensure_system_user(email: str) -> str:
	"""A non-SM System User (realistic tool caller)."""
	if not frappe.db.exists("User", email):
		u = frappe.get_doc({
			"doctype": "User", "email": email,
			"first_name": "sttool", "send_welcome_email": 0, "enabled": 1,
			"user_type": "System User",
			"roles": [{"role": "Sales User"}],
		})
		u.flags.ignore_permissions = True
		u.insert(ignore_permissions=True)
	elif frappe.db.get_value("User", email, "user_type") != "System User":
		frappe.db.set_value("User", email, "user_type", "System User")
	if "System Manager" in set(frappe.get_roles(email)):
		frappe.get_doc("User", email).remove_roles("System Manager")
	return email


def _ensure_website_user(email: str) -> str:
	if not frappe.db.exists("User", email):
		u = frappe.get_doc({
			"doctype": "User", "email": email,
			"first_name": "sttool-web", "send_welcome_email": 0, "enabled": 1,
			"user_type": "Website User",
		})
		u.flags.ignore_permissions = True
		u.insert(ignore_permissions=True)
	return email


def _sweep_fixture_skills():
	for name in frappe.get_all(
		SKILL, filters={"skill_name": ["like", f"{PFX}-%"]}, pluck="name"
	):
		frappe.delete_doc(SKILL, name, force=True, ignore_permissions=True)


def _make_skill(owner: str, skill_name: str, description: str, *,
				scope: str = "Org", shared_with=None, allowed_roles=None,
				enabled: int = 1):
	"""Insert a row through the real doctype as ``owner`` (child tables can't
	be passed through the tool)."""
	with _as(owner):
		doc = frappe.get_doc({
			"doctype": SKILL,
			"skill_name": skill_name,
			"description": description,
			"instructions": f"instructions for {skill_name}",
			"scope": scope,
			"enabled": enabled,
			"user_invocable": 1,
			"shared_with": [{"user": u} for u in (shared_with or [])],
			"allowed_roles": [{"role": r} for r in (allowed_roles or [])],
		})
		doc.insert()
	return doc


class SkillToolsTestCase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_sweep_fixture_skills()
		_ensure_system_user(OWNER)
		_ensure_system_user(PEER)
		_ensure_system_user(THIRD)
		_ensure_website_user(WEB)

	def setUp(self):
		frappe.set_user("Administrator")
		for user in (OWNER, PEER, THIRD):
			frappe.cache().delete_value(personal_skills_cache_key(user))

	def tearDown(self):
		frappe.set_user("Administrator")
		_sweep_fixture_skills()


class TestFindSkills(SkillToolsTestCase):
	def test_short_or_empty_query_rejected(self):
		with _as(OWNER):
			for bad in ("", "  ", "a"):
				with self.assertRaises(InvalidArgumentError):
					find_skills(bad)

	def test_personal_row_invisible_to_other_user(self):
		with _as(OWNER):
			create_custom_skill(
				f"{PFX}-priv-alpha", "sttool marker alpha steps",
				"do the alpha thing", scope="Personal",
			)
		with _as(OWNER):
			mine = find_skills("marker alpha")
			self.assertEqual(
				[s["skill_name"] for s in mine["skills"]], [f"{PFX}-priv-alpha"])
			self.assertEqual(mine["skills"][0]["scope"], "Personal")
		with _as(PEER):
			theirs = find_skills("marker alpha")
			self.assertEqual(theirs["count"], 0)
			self.assertEqual(theirs["skills"], [])

	def test_org_row_visible_to_everyone(self):
		_make_skill(OWNER, f"{PFX}-org-beta", "sttool marker beta steps")
		with _as(PEER):
			res = find_skills("marker beta")
			names = [s["skill_name"] for s in res["skills"]]
			self.assertIn(f"{PFX}-org-beta", names)
			row = res["skills"][names.index(f"{PFX}-org-beta")]
			self.assertEqual(row["scope"], "Org")
			self.assertFalse(row["managed"])

	def test_shared_row_visible_despite_role_mismatch(self):
		# allowed_roles doesn't match PEER, but the explicit share wins;
		# THIRD (no share, no role) never sees it.
		_make_skill(
			OWNER, f"{PFX}-shared-gamma", "sttool marker gamma steps",
			shared_with=[PEER], allowed_roles=["Sales Manager"],
		)
		with _as(PEER):
			names = [s["skill_name"] for s in find_skills("marker gamma")["skills"]]
			self.assertIn(f"{PFX}-shared-gamma", names)
		with _as(THIRD):
			self.assertEqual(find_skills("marker gamma")["count"], 0)

	def test_disabled_rows_excluded(self):
		_make_skill(OWNER, f"{PFX}-off-delta", "sttool marker delta steps", enabled=0)
		with _as(OWNER):
			self.assertEqual(find_skills("marker delta")["count"], 0)

	def test_like_wildcards_are_escaped(self):
		# An unescaped "_" would make "a_b" match "axb" too.
		_make_skill(OWNER, f"{PFX}-lit-underscore", "sttool token a_b here")
		_make_skill(OWNER, f"{PFX}-lit-decoy", "sttool token axb here")
		with _as(OWNER):
			names = [s["skill_name"] for s in find_skills("token a_b")["skills"]]
			self.assertEqual(names, [f"{PFX}-lit-underscore"])

	def test_limit_caps_results(self):
		for i in range(3):
			_make_skill(OWNER, f"{PFX}-lim-{i}", "sttool marker limitcase steps")
		with _as(OWNER):
			res = find_skills("marker limitcase", limit=2)
			self.assertEqual(res["count"], 2)
			self.assertEqual(len(res["skills"]), 2)

	def test_gate_rejects_guest_and_website_user(self):
		with _as("Guest"):
			with self.assertRaises(PermissionDeniedError):
				find_skills("marker beta")
		with _as(WEB):
			with self.assertRaises(PermissionDeniedError):
				find_skills("marker beta")


class TestGetSkill(SkillToolsTestCase):
	def test_bare_and_custom_prefixed_names_resolve(self):
		with _as(OWNER):
			create_custom_skill(
				f"{PFX}-fetch-me", "sttool fetch desc", "fetch body",
				scope="Personal",
			)
		with _as(OWNER):
			for query_name in (f"{PFX}-fetch-me", f"custom-{PFX}-fetch-me"):
				out = get_skill(query_name)
				self.assertEqual(out["skill_name"], f"{PFX}-fetch-me")
				self.assertEqual(out["instructions"], "fetch body")
				self.assertEqual(out["scope"], "Personal")
				self.assertEqual(out["enabled"], 1)

	def test_unknown_skill_is_invalid_argument(self):
		with _as(OWNER):
			with self.assertRaises(InvalidArgumentError):
				get_skill(f"{PFX}-does-not-exist")

	def test_personal_row_denied_to_other_user(self):
		with _as(OWNER):
			create_custom_skill(
				f"{PFX}-priv-fetch", "sttool priv fetch", "secret body",
				scope="Personal",
			)
		with _as(PEER):
			with self.assertRaises(PermissionDeniedError):
				get_skill(f"{PFX}-priv-fetch")

	def test_role_scoped_org_row_denied_without_role_or_share(self):
		_make_skill(
			OWNER, f"{PFX}-role-only", "sttool role only",
			allowed_roles=["Sales Manager"],
		)
		with _as(PEER):
			with self.assertRaises(PermissionDeniedError):
				get_skill(f"{PFX}-role-only")

	def test_own_row_preferred_over_same_named_foreign_row(self):
		# skill_name is unique per owner, not globally.
		_make_skill(OWNER, f"{PFX}-dup-name", "sttool dup owner copy")
		_make_skill(PEER, f"{PFX}-dup-name", "sttool dup peer copy")
		with _as(PEER):
			self.assertEqual(get_skill(f"{PFX}-dup-name")["description"],
							 "sttool dup peer copy")


class TestCreateCustomSkill(SkillToolsTestCase):
	def test_creates_personal_by_default_with_note(self):
		with _as(OWNER):
			out = create_custom_skill(
				f"{PFX}-mk-default", "sttool mk desc", "mk body")
		self.assertEqual(out["scope"], "Personal")
		self.assertEqual(out["skill_name"], f"{PFX}-mk-default")
		self.assertIn("note", out)
		row = frappe.db.get_value(
			SKILL, out["name"], ["owner", "scope", "enabled"], as_dict=True)
		self.assertEqual(row.owner, OWNER)
		self.assertEqual(row.scope, "Personal")
		self.assertEqual(int(row.enabled), 1)

	def test_org_scope_note_mentions_apply(self):
		with _as(OWNER):
			out = create_custom_skill(
				f"{PFX}-mk-org", "sttool mk org desc", "mk org body", scope="Org")
		self.assertEqual(out["scope"], "Org")
		self.assertIn("Apply", out["note"])

	def test_invalid_scope_rejected(self):
		with _as(OWNER):
			with self.assertRaises(InvalidArgumentError):
				create_custom_skill(
					f"{PFX}-mk-badscope", "d", "i", scope="Team")

	def test_slug_and_cap_violations_surface_as_jarvis_errors(self):
		with _as(OWNER):
			# Bad slug grammar.
			with self.assertRaises(InvalidArgumentError):
				create_custom_skill("Bad Slug!", "sttool desc", "body")
			# Reserved wire prefix.
			with self.assertRaises(InvalidArgumentError):
				create_custom_skill("custom-sttool-x", "sttool desc", "body")
			# Length cap (description > 500).
			with self.assertRaises(InvalidArgumentError):
				create_custom_skill(f"{PFX}-mk-longdesc", "x" * 501, "body")
			# Duplicate per-owner name.
			create_custom_skill(f"{PFX}-mk-dup", "sttool desc", "body")
			with self.assertRaises(InvalidArgumentError):
				create_custom_skill(f"{PFX}-mk-dup", "sttool desc", "body")

	def test_gate_rejects_website_user(self):
		with _as(WEB):
			with self.assertRaises(PermissionDeniedError):
				create_custom_skill(f"{PFX}-mk-web", "d", "i")


class TestPushPayloadScope(SkillToolsTestCase):
	def test_personal_excluded_null_scope_pushed_as_org(self):
		_make_skill(OWNER, f"{PFX}-push-org", "sttool push org", scope="Org")
		_make_skill(OWNER, f"{PFX}-push-personal", "sttool push personal",
					scope="Personal")
		legacy = _make_skill(OWNER, f"{PFX}-push-legacy", "sttool push legacy",
							 scope="Org")
		# Simulate a pre-migration row: scope NULL in the DB (validate() can't
		# normalize what never gets saved again).
		frappe.db.set_value(SKILL, legacy.name, "scope", None,
							update_modified=False)

		slugs = {p["slug"] for p in build_push_payload(owner=OWNER)}
		self.assertIn(prefixed_slug(f"{PFX}-push-org"), slugs)
		self.assertIn(prefixed_slug(f"{PFX}-push-legacy"), slugs)
		self.assertNotIn(prefixed_slug(f"{PFX}-push-personal"), slugs)


class TestPersonalSkillClause(SkillToolsTestCase):
	def test_zero_case_returns_empty(self):
		self.assertEqual(personal_skill_clause(THIRD), "")
		self.assertEqual(personal_skill_clause("Guest"), "")

	def test_clause_reads_cache(self):
		frappe.cache().set_value(
			personal_skills_cache_key(THIRD), 7, expires_in_sec=60)
		clause = personal_skill_clause(THIRD)
		self.assertIn("7 personal skill(s)", clause)
		self.assertIn("jarvis__find_skills", clause)

	def test_row_writes_invalidate_cache(self):
		# Prime the zero-case cache, then create a Personal row: the controller
		# on_update invalidation must make the next clause see it.
		self.assertEqual(personal_skill_clause(OWNER), "")
		with _as(OWNER):
			out = create_custom_skill(
				f"{PFX}-clause-one", "sttool clause desc", "clause body")
		self.assertIn("1 personal skill(s)", personal_skill_clause(OWNER))
		# Deleting the row invalidates again (on_trash).
		frappe.delete_doc(SKILL, out["name"], force=True, ignore_permissions=True)
		self.assertEqual(personal_skill_clause(OWNER), "")

	def test_org_rows_do_not_count(self):
		_make_skill(OWNER, f"{PFX}-clause-org", "sttool clause org", scope="Org")
		self.assertEqual(personal_skill_clause(OWNER), "")


class TestRegistryAndClassification(SkillToolsTestCase):
	def test_registry_lists_and_dispatches_new_tools(self):
		from jarvis.tools.registry import dispatch, list_tools

		tools = list_tools()
		for name in ("find_skills", "get_skill", "create_custom_skill",
					 "read_wiki", "update_wiki"):
			self.assertIn(name, tools)

		with _as(OWNER):
			created = dispatch("create_custom_skill", {
				"skill_name": f"{PFX}-via-registry",
				"description": "sttool registry marker",
				"instructions": "registry body",
			})
			self.assertEqual(created["scope"], "Personal")

			found = dispatch("find_skills", {"query": "registry marker", "limit": 5})
			self.assertEqual(
				[s["skill_name"] for s in found["skills"]],
				[f"{PFX}-via-registry"])

			got = dispatch("get_skill", {"skill_name": f"{PFX}-via-registry"})
			self.assertEqual(got["instructions"], "registry body")

	def test_classification_membership(self):
		from jarvis import api as jarvis_api

		for tool in ("create_custom_skill", "update_wiki"):
			self.assertIn(tool, jarvis_api._WRITE_TOOLS)
			self.assertIn(tool, jarvis_api._GATED_WRITES)
			self.assertNotIn(tool, jarvis_api._AUTO_APPLYABLE)
			self.assertNotIn(tool, jarvis_api._PREVIEWABLE)
		for tool in ("find_skills", "get_skill", "read_wiki"):
			self.assertNotIn(tool, jarvis_api._WRITE_TOOLS)
			self.assertNotIn(tool, jarvis_api._GATED_WRITES)


class TestReceiptRefStamping(SkillToolsTestCase):
	"""persist_tool_receipt stamps ref_doctype/ref_name via
	jarvis.chat.entities.refs_from_tool (best-effort, never breaks receipts)."""

	CONV_TITLE = "sttool receipt-ref test"

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all(
			"Jarvis Conversation", filters={"title": self.CONV_TITLE},
			pluck="name",
		):
			frappe.delete_doc(
				"Jarvis Conversation", name, force=True, ignore_permissions=True)
		super().tearDown()

	def _conv(self) -> str:
		doc = frappe.get_doc({
			"doctype": "Jarvis Conversation", "title": self.CONV_TITLE})
		doc.insert(ignore_permissions=True)
		return doc.name

	def test_receipt_carries_refs_from_args(self):
		from jarvis import api as jarvis_api

		conv = self._conv()
		jarvis_api.persist_tool_receipt(
			conv, "get_doc",
			{"doctype": "User", "name": "Administrator"},
			{"ok": True, "data": {"doctype": "User", "name": "Administrator"}},
		)
		row = frappe.get_all(
			"Jarvis Chat Message",
			filters={"conversation": conv, "role": "tool"},
			fields=["ref_doctype", "ref_name", "tool_status"],
		)[0]
		self.assertEqual(row.ref_doctype, "User")
		self.assertEqual(row.ref_name, "Administrator")
		self.assertEqual(row.tool_status, "completed")

	def test_refless_call_still_persists_receipt(self):
		from jarvis import api as jarvis_api

		conv = self._conv()
		jarvis_api.persist_tool_receipt(
			conv, "run_report", {"report_name": "some-report"},
			{"ok": False, "error": {"code": "InvalidArgumentError",
									"message": "nope"}},
		)
		row = frappe.get_all(
			"Jarvis Chat Message",
			filters={"conversation": conv, "role": "tool"},
			fields=["ref_doctype", "ref_name", "tool_status"],
		)[0]
		self.assertFalse(row.ref_doctype)
		self.assertFalse(row.ref_name)
		self.assertEqual(row.tool_status, "error")
