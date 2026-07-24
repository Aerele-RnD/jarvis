"""Tests for jarvis.release_notice: persist, boot payload and the gate's refresh."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import release_notice

_FIELDS = (
	"release_notice_active",
	"latest_jarvis_version",
	"release_notice_message",
)


def _snapshot() -> dict:
	s = frappe.get_single("Jarvis Settings")
	return {f: s.get(f) for f in _FIELDS}


def _restore(snap: dict) -> None:
	s = frappe.get_single("Jarvis Settings")
	for f, v in snap.items():
		s.db_set(f, v)
	frappe.db.commit()


class TestBootPayload(FrappeTestCase):
	def setUp(self):
		self._snap = _snapshot()

	def tearDown(self):
		_restore(self._snap)

	def _set(self, **kw):
		s = frappe.get_single("Jarvis Settings")
		for k, v in kw.items():
			s.db_set(k, v)
		frappe.db.commit()

	def test_active_notice_shape(self):
		self._set(
			release_notice_active=1,
			latest_jarvis_version="0.0.2",
			release_notice_message="New dashboards.",
		)
		p = release_notice.boot_payload()
		self.assertTrue(p["active"])
		self.assertEqual(p["version"], "0.0.2")
		self.assertEqual(p["message"], "New dashboards.")
		# No authored title/url travel — the SPA composes the heading.
		self.assertNotIn("title", p)
		self.assertNotIn("url", p)

	def test_inactive_notice(self):
		self._set(release_notice_active=0, release_notice_message="m")
		self.assertFalse(release_notice.boot_payload()["active"])

	def test_check_refreshes_from_admin_and_returns_payload(self):
		self._set(release_notice_active=1, latest_jarvis_version="0.0.2", release_notice_message="old")
		fresh = {"active": True, "version": "0.0.3", "message": "new"}
		with patch("jarvis.admin_client.get_connection", return_value={"release_notice": fresh}) as gc:
			out = release_notice.check()
		gc.assert_called_once_with(timeout_s=8)
		self.assertEqual(out["version"], "0.0.3")
		self.assertEqual(out["message"], "new")

	def test_check_clears_when_admin_sends_none(self):
		# The gate polls this; a cleared notice is what lets an updated tenant back in.
		self._set(release_notice_active=1, latest_jarvis_version="0.0.2", release_notice_message="m")
		with patch("jarvis.admin_client.get_connection", return_value={}):
			out = release_notice.check()
		self.assertFalse(out["active"])

	def test_check_keeps_mirror_when_admin_unreachable(self):
		self._set(release_notice_active=1, latest_jarvis_version="0.0.2", release_notice_message="m")
		with patch("jarvis.admin_client.get_connection", side_effect=RuntimeError("boom")):
			out = release_notice.check()
		self.assertTrue(out["active"])

	def test_persist_then_clear_round_trip(self):
		release_notice.persist({"active": True, "version": "0.0.2", "message": "M"})
		p = release_notice.boot_payload()
		self.assertTrue(p["active"])
		self.assertEqual(p["version"], "0.0.2")
		self.assertEqual(p["message"], "M")
		# Empty dict clears every field.
		release_notice.persist({})
		p = release_notice.boot_payload()
		self.assertFalse(p["active"])
		self.assertEqual(p["version"], "")
		self.assertEqual(p["message"], "")
