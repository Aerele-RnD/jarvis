from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import admin_client
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

	def test_default_grant_skips_administrator_and_guest(self):
		for u in ("Administrator", "Guest"):
			grant_default_support(u)
			self.assertFalse(frappe.db.exists("Has Role", {"parent": u, "role": JARVIS_SUPPORT_USER_ROLE}))


class TestAdminClientSupport(FrappeTestCase):
	def test_list_tickets_posts_to_support_path(self):
		with patch.object(admin_client, "_post", return_value={"ok": True, "data": {"tickets": []}}) as post:
			admin_client.support_list_tickets(requesting_user="u@x", scope="own")
			self.assertIn("support.api.list_tickets", post.call_args.kwargs["path"])
			self.assertEqual(post.call_args.kwargs["body"]["scope"], "own")

	def test_upload_posts_b64_via_support_path(self):
		with patch.object(
			admin_client, "_post", return_value={"ok": True, "data": {"file_url": "/f/x"}}
		) as post:
			admin_client.support_upload(
				ticket="T1", filename="x.png", content_b64="aGk=", requesting_user="u@x", scope="own"
			)
			self.assertIn("support.media.upload", post.call_args.kwargs["path"])
			self.assertEqual(post.call_args.kwargs["body"]["content_b64"], "aGk=")

	def test_authenticated_raw_remints_on_401_then_legacy(self):
		# bearer 401 -> re-mint bearer 401 -> legacy token 200 (preserves _post's ladder)
		settings = MagicMock()
		settings.get_password.side_effect = lambda f, **k: {
			"jarvis_admin_api_key": "k",
			"jarvis_admin_api_secret": "s",
		}.get(f)
		r401, r200 = MagicMock(status_code=401), MagicMock(status_code=200)
		with (
			patch("frappe.get_single", return_value=settings),
			patch.object(admin_client, "_admin_url", return_value="http://cp"),
			patch.object(admin_client, "_admin_access_token", side_effect=["tok1", "tok2"]),
			patch.object(admin_client, "requests") as rq,
		):
			rq.post.side_effect = [r401, r401, r200]
			resp = admin_client._authenticated_raw("/p", {}, timeout_s=10)
			self.assertIs(resp, r200)
			self.assertIn("token k:s", rq.post.call_args.kwargs["headers"]["Authorization"])
