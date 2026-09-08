"""The desktop + mobile www shells expose the announcement in context.boot."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.www import jarvis as www_desktop
from jarvis.www import jarvis_mobile as www_mobile

_FIELDS = (
	"announcement_active",
	"announcement_id",
	"announcement_title",
	"announcement_message",
)


class TestWwwAnnouncement(FrappeTestCase):
	def setUp(self):
		s = frappe.get_single("Jarvis Settings")
		self._snap = {f: s.get(f) for f in _FIELDS}
		s.db_set("announcement_active", 1)
		s.db_set("announcement_id", "ANN-00042")
		s.db_set("announcement_title", "Scheduled maintenance")
		s.db_set("announcement_message", "We update Sunday 02:00 UTC.")
		frappe.db.commit()

	def tearDown(self):
		s = frappe.get_single("Jarvis Settings")
		for f, v in self._snap.items():
			s.db_set(f, v)
		frappe.db.commit()

	def test_desktop_boot_exposes_announcement(self):
		ctx = frappe._dict()
		with (
			patch.object(www_desktop, "has_jarvis_access", return_value=True),
			patch.object(www_desktop, "has_jarvis_admin_access", return_value=False),
			patch.object(www_desktop, "support_scope", return_value=None),
			patch.object(www_desktop, "_support_state", return_value=www_desktop.SUPPORT_OFF),
		):
			www_desktop.get_context(ctx)
		ann = ctx.boot["announcement"]
		self.assertTrue(ann["active"])
		self.assertEqual(ann["id"], "ANN-00042")
		self.assertEqual(ann["title"], "Scheduled maintenance")
		self.assertEqual(ann["message"], "We update Sunday 02:00 UTC.")

	def test_mobile_boot_exposes_announcement(self):
		ctx = frappe._dict()
		with patch.object(www_mobile, "has_jarvis_access", return_value=True):
			www_mobile.get_context(ctx)
		ann = ctx.boot["announcement"]
		self.assertTrue(ann["active"])
		self.assertEqual(ann["id"], "ANN-00042")
