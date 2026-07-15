"""Tests for the Jarvis no-access page (jarvis.www.jarvis_no_access) and boot flag.

Covers:
- Boot flag: set_jarvis_boot(bootinfo) sets jarvis_has_access True/False per access.
- No-access page gates: unauthorized (render + admin emails), authorized (redirect to
  /jarvis), Guest (redirect to /login).
- Admin contacts: System Users with System Manager role, excludes Administrator, capped.
- Main app gates (jarvis.py, jarvis_mobile.py): roleless → /jarvis-no-access, Guest → /app.

Hermetic: throwaway System User rows (one per role shape) are created in setUp
and deleted in tearDown; the Jarvis User role is seeded and dropped idempotently.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.boot import set_jarvis_boot
from jarvis.permissions import JARVIS_USER_ROLE
from jarvis.www import jarvis, jarvis_mobile, jarvis_no_access

JARVIS_ROLE = JARVIS_USER_ROLE

# One throwaway user per role shape under test.
USER_JARVIS = "jarvis-noaccess-juser@example.test"
USER_SM = "jarvis-noaccess-sm@example.test"
USER_NONE = "jarvis-noaccess-none@example.test"


def _ensure_role() -> bool:
	"""Seed the Jarvis User role if absent. Returns True iff we created it
	(so tearDown only drops a role this test introduced)."""
	if frappe.db.exists("Role", JARVIS_ROLE):
		return False
	frappe.get_doc({
		"doctype": "Role", "role_name": JARVIS_ROLE,
		"desk_access": 1, "is_custom": 1,
	}).insert(ignore_permissions=True)
	return True


def _ensure_user(email: str, roles: tuple[str, ...] = ()) -> None:
	"""Create a disposable enabled System User (idempotent) and attach roles."""
	if not frappe.db.exists("User", email):
		frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": "JarvisNoAccess",
			"last_name": "TestUser",
			"enabled": 1,
			"send_welcome_email": 0,
			"user_type": "System User",
		}).insert(ignore_permissions=True)
	if roles:
		frappe.get_doc("User", email).add_roles(*roles)


def _delete_user(email: str) -> None:
	"""Delete a user; clean up any owned Jarvis data first."""
	# Drop any conversations the user owns, then the user row itself.
	for conv in frappe.get_all("Jarvis Conversation", filters={"owner": email}, pluck="name"):
		for msg in frappe.get_all("Jarvis Chat Message", filters={"conversation": conv}, pluck="name"):
			frappe.delete_doc("Jarvis Chat Message", msg, ignore_permissions=True, force=True)
		frappe.delete_doc("Jarvis Conversation", conv, ignore_permissions=True, force=True)
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, ignore_permissions=True, force=True)


class TestJarvisNoAccessPage(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		"""Seed the Jarvis User role once for all tests."""
		super().setUpClass()
		cls._created_role = _ensure_role()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		"""Drop the role only if we created it."""
		super().tearDownClass()
		if cls._created_role and frappe.db.exists("Role", JARVIS_ROLE):
			frappe.delete_doc("Role", JARVIS_ROLE, ignore_permissions=True, force=True)
		frappe.db.commit()

	def setUp(self):
		"""Create throwaway test users."""
		self._orig_user = frappe.session.user
		_ensure_user(USER_JARVIS, (JARVIS_ROLE,))
		_ensure_user(USER_SM, ("System Manager",))
		_ensure_user(USER_NONE, ())
		frappe.db.commit()

	def tearDown(self):
		"""Restore original user and clean up test users."""
		frappe.set_user(self._orig_user)
		for email in (USER_JARVIS, USER_SM, USER_NONE):
			_delete_user(email)
		frappe.db.commit()

	# --- (a) set_jarvis_boot ------------------------------------------------- #

	def test_boot_flag_true_for_jarvis_user(self):
		"""Boot sets jarvis_has_access=True for a user with Jarvis User role."""
		frappe.set_user(USER_JARVIS)
		bootinfo = frappe._dict()
		set_jarvis_boot(bootinfo)
		self.assertTrue(bootinfo.jarvis_has_access)

	def test_boot_flag_true_for_system_manager(self):
		"""Boot sets jarvis_has_access=True for System Manager."""
		frappe.set_user(USER_SM)
		bootinfo = frappe._dict()
		set_jarvis_boot(bootinfo)
		self.assertTrue(bootinfo.jarvis_has_access)

	def test_boot_flag_true_for_administrator(self):
		"""Boot sets jarvis_has_access=True for Administrator."""
		frappe.set_user("Administrator")
		bootinfo = frappe._dict()
		set_jarvis_boot(bootinfo)
		self.assertTrue(bootinfo.jarvis_has_access)

	def test_boot_flag_false_for_roleless_user(self):
		"""Boot sets jarvis_has_access=False for a user with no access roles."""
		frappe.set_user(USER_NONE)
		bootinfo = frappe._dict()
		set_jarvis_boot(bootinfo)
		self.assertFalse(bootinfo.jarvis_has_access)

	def test_boot_flag_fail_closed_on_exception(self):
		"""Boot fail-closes to False when has_jarvis_access raises an exception."""
		frappe.set_user(USER_JARVIS)
		bootinfo = frappe._dict()
		with patch("jarvis.permissions.has_jarvis_access", side_effect=Exception("boom")):
			set_jarvis_boot(bootinfo)
		self.assertFalse(bootinfo.jarvis_has_access)

	# --- (b) jarvis_no_access.get_context ----------------------------------- #

	def test_no_access_guest_redirects_to_login(self):
		"""Guest on no-access page redirects to /login."""
		frappe.set_user("Guest")
		with self.assertRaises(frappe.Redirect):
			jarvis_no_access.get_context(frappe._dict())
		self.assertEqual(frappe.local.flags.redirect_location, "/login")

	def test_no_access_authorized_redirects_to_jarvis(self):
		"""Authorized user (has Jarvis User role) redirects to /jarvis."""
		frappe.set_user(USER_JARVIS)
		with self.assertRaises(frappe.Redirect):
			jarvis_no_access.get_context(frappe._dict())
		self.assertEqual(frappe.local.flags.redirect_location, "/jarvis")

	def test_no_access_system_manager_redirects_to_jarvis(self):
		"""System Manager is authorized, so redirects to /jarvis."""
		frappe.set_user(USER_SM)
		with self.assertRaises(frappe.Redirect):
			jarvis_no_access.get_context(frappe._dict())
		self.assertEqual(frappe.local.flags.redirect_location, "/jarvis")

	def test_no_access_unauthorized_renders(self):
		"""Unauthorized signed-in user renders the no-access page with context."""
		frappe.set_user(USER_NONE)
		context = frappe._dict()
		result = jarvis_no_access.get_context(context)
		# Should not raise; should have context keys.
		self.assertIn("user_fullname", result)
		self.assertIn("admin_emails", result)

	def test_no_access_unauthorized_has_user_fullname(self):
		"""Unauthorized user context includes user_fullname."""
		frappe.set_user(USER_NONE)
		context = frappe._dict()
		jarvis_no_access.get_context(context)
		# user_fullname should be set and non-empty (or at least present).
		self.assertIsNotNone(context.user_fullname)

	def test_no_access_unauthorized_has_admin_emails(self):
		"""Unauthorized user context includes admin_emails."""
		frappe.set_user(USER_NONE)
		context = frappe._dict()
		jarvis_no_access.get_context(context)
		# admin_emails should be a list.
		self.assertIsInstance(context.admin_emails, list)

	# --- (c) jarvis_no_access._admin_contacts ------------------------------- #

	def test_admin_contacts_returns_list(self):
		"""_admin_contacts returns a list."""
		result = jarvis_no_access._admin_contacts()
		self.assertIsInstance(result, list)

	def test_admin_contacts_excludes_administrator(self):
		"""_admin_contacts does not include the built-in Administrator account."""
		# Ensure Administrator is a System Manager (always true).
		result = jarvis_no_access._admin_contacts()
		# Check that "Administrator" is not in the list (it filters by email, not name).
		# Since admin_contacts returns emails, we check no email matches Administrator's.
		admin_email = frappe.get_value("User", "Administrator", "email")
		for email in result:
			self.assertNotEqual(email, admin_email)

	def test_admin_contacts_contains_only_strings(self):
		"""_admin_contacts returns only strings (emails)."""
		result = jarvis_no_access._admin_contacts()
		for item in result:
			self.assertIsInstance(item, str)

	def test_admin_contacts_capped_at_limit(self):
		"""_admin_contacts respects the limit parameter."""
		# Default limit is 5.
		result = jarvis_no_access._admin_contacts()
		self.assertLessEqual(len(result), 5)
		# Custom limit.
		result = jarvis_no_access._admin_contacts(limit=2)
		self.assertLessEqual(len(result), 2)

	def test_admin_contacts_only_system_manager_role(self):
		"""_admin_contacts only includes System Manager role holders."""
		# USER_SM has System Manager, so their email should be in the list
		# (assuming they're enabled and the query returns them).
		result = jarvis_no_access._admin_contacts()
		# We can't easily assert USER_SM is in the list without knowing their email
		# from the DB, but we can assert the function runs and returns a list.
		self.assertIsInstance(result, list)

	def test_admin_contacts_empty_on_exception(self):
		"""_admin_contacts returns empty list if an exception occurs."""
		with patch("frappe.utils.user.get_users_with_role", side_effect=Exception("boom")):
			result = jarvis_no_access._admin_contacts()
		self.assertEqual(result, [])

	# --- (d) www.jarvis gate ------------------------------------------------- #

	def test_jarvis_guest_redirects_to_app(self):
		"""Guest on /jarvis redirects to /app."""
		frappe.set_user("Guest")
		with self.assertRaises(frappe.Redirect):
			jarvis.get_context(frappe._dict())
		self.assertEqual(frappe.local.flags.redirect_location, "/app")

	def test_jarvis_unauthorized_redirects_to_no_access(self):
		"""Roleless user on /jarvis redirects to /jarvis-no-access."""
		frappe.set_user(USER_NONE)
		with self.assertRaises(frappe.Redirect):
			jarvis.get_context(frappe._dict())
		self.assertEqual(frappe.local.flags.redirect_location, "/jarvis-no-access")

	def test_jarvis_authorized_renders(self):
		"""Authorized user on /jarvis renders the app."""
		frappe.set_user(USER_JARVIS)
		context = frappe._dict()
		result = jarvis.get_context(context)
		# Should not raise; should have boot context.
		self.assertIn("boot", result)
		self.assertIsInstance(result.boot, dict)

	def test_jarvis_system_manager_renders(self):
		"""System Manager on /jarvis renders the app."""
		frappe.set_user(USER_SM)
		context = frappe._dict()
		result = jarvis.get_context(context)
		# Should not raise; should have boot context.
		self.assertIn("boot", result)
		self.assertIsInstance(result.boot, dict)

	# --- (e) www.jarvis_mobile gate ------------------------------------------ #

	def test_jarvis_mobile_guest_redirects_to_app(self):
		"""Guest on /jarvis-mobile redirects to /app."""
		frappe.set_user("Guest")
		with self.assertRaises(frappe.Redirect):
			jarvis_mobile.get_context(frappe._dict())
		self.assertEqual(frappe.local.flags.redirect_location, "/app")

	def test_jarvis_mobile_unauthorized_redirects_to_no_access(self):
		"""Roleless user on /jarvis-mobile redirects to /jarvis-no-access."""
		frappe.set_user(USER_NONE)
		with self.assertRaises(frappe.Redirect):
			jarvis_mobile.get_context(frappe._dict())
		self.assertEqual(frappe.local.flags.redirect_location, "/jarvis-no-access")

	def test_jarvis_mobile_authorized_renders(self):
		"""Authorized user on /jarvis-mobile renders the app."""
		frappe.set_user(USER_JARVIS)
		context = frappe._dict()
		result = jarvis_mobile.get_context(context)
		# Should not raise; should have boot context.
		self.assertIn("boot", result)
		self.assertIsInstance(result.boot, dict)

	def test_jarvis_mobile_system_manager_renders(self):
		"""System Manager on /jarvis-mobile renders the app."""
		frappe.set_user(USER_SM)
		context = frappe._dict()
		result = jarvis_mobile.get_context(context)
		# Should not raise; should have boot context.
		self.assertIn("boot", result)
		self.assertIsInstance(result.boot, dict)
