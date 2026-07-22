import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.permissions import (
	JARVIS_SUPPORT_ADMIN_ROLE,
	JARVIS_SUPPORT_USER_ROLE,
	JARVIS_USER_ROLE,
	ensure_support_roles,
	grant_default_support,
	support_scope,
)


def _user(roles):
	u = frappe.get_doc(
		{
			"doctype": "User",
			"email": f"{frappe.generate_hash(length=8)}@sup.test",
			"first_name": "S",
			"send_welcome_email": 0,
		}
	)
	for r in roles:
		u.append("roles", {"role": r})
	return u.insert(ignore_permissions=True).name


class TestSupportScope(FrappeTestCase):
	def setUp(self):
		ensure_support_roles()

	def test_none_without_role(self):
		self.assertIsNone(support_scope(_user([])))

	def test_own_for_support_user(self):
		self.assertEqual(support_scope(_user([JARVIS_SUPPORT_USER_ROLE])), "own")

	def test_all_for_support_admin(self):
		self.assertEqual(support_scope(_user([JARVIS_SUPPORT_ADMIN_ROLE])), "all")

	def test_default_grant_gives_own_to_jarvis_user(self):
		u = _user([JARVIS_USER_ROLE])
		self.assertIsNone(support_scope(u))
		grant_default_support(u)
		self.assertEqual(support_scope(u), "own")
