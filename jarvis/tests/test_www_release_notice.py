"""The desktop + mobile www shells expose release_notice in context.boot."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.www import jarvis as www_desktop
from jarvis.www import jarvis_mobile as www_mobile

_FIELDS = (
	"release_notice_active",
	"latest_jarvis_version",
	"release_notice_title",
	"release_notice_message",
	"release_notice_url",
)


class TestWwwReleaseNotice(FrappeTestCase):
	def setUp(self):
		s = frappe.get_single("Jarvis Settings")
		self._snap = {f: s.get(f) for f in _FIELDS}
		# 99.0.0 is above any real jarvis __version__, so update_available is True.
		s.db_set("release_notice_active", 1)
		s.db_set("latest_jarvis_version", "99.0.0")
		s.db_set("release_notice_title", "Heads up")
		s.db_set("release_notice_message", "msg")
		s.db_set("release_notice_url", "https://x")
		frappe.db.commit()

	def tearDown(self):
		s = frappe.get_single("Jarvis Settings")
		for f, v in self._snap.items():
			s.db_set(f, v)
		frappe.db.commit()

	def test_desktop_boot_exposes_release_notice(self):
		ctx = frappe._dict()
		with (
			patch.object(www_desktop, "has_jarvis_access", return_value=True),
			patch.object(www_desktop, "has_jarvis_admin_access", return_value=False),
			patch.object(www_desktop, "grant_default_support", lambda: None),
			patch.object(www_desktop, "support_scope", return_value=None),
			patch.object(www_desktop, "_support_available", return_value=False),
		):
			www_desktop.get_context(ctx)
		rn = ctx.boot["release_notice"]
		self.assertTrue(rn["active"])
		self.assertTrue(rn["update_available"])
		self.assertEqual(rn["latest_version"], "99.0.0")
		self.assertEqual(rn["title"], "Heads up")

	def test_mobile_boot_exposes_release_notice(self):
		ctx = frappe._dict()
		with patch.object(www_mobile, "has_jarvis_access", return_value=True):
			www_mobile.get_context(ctx)
		rn = ctx.boot["release_notice"]
		self.assertTrue(rn["active"])
		self.assertTrue(rn["update_available"])
		self.assertEqual(rn["title"], "Heads up")
