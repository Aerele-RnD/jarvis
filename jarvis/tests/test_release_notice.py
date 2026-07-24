"""Tests for jarvis.release_notice: persist + boot payload (fleet-wide switch,
no version comparison)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import release_notice

_FIELDS = (
	"release_notice_active",
	"latest_jarvis_version",
	"release_notice_title",
	"release_notice_message",
	"release_notice_url",
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
			release_notice_title="Heads up",
			release_notice_message="msg",
			release_notice_url="https://x",
		)
		p = release_notice.boot_payload()
		self.assertTrue(p["active"])
		self.assertEqual(p["title"], "Heads up")
		self.assertEqual(p["message"], "msg")
		self.assertEqual(p["latest_version"], "0.0.2")
		# Version comparison is gone — boot never computes these.
		self.assertNotIn("update_available", p)
		self.assertNotIn("current_version", p)

	def test_inactive_notice(self):
		self._set(release_notice_active=0, release_notice_title="t")
		self.assertFalse(release_notice.boot_payload()["active"])

	def test_version_is_optional(self):
		self._set(release_notice_active=1, latest_jarvis_version="", release_notice_title="t")
		p = release_notice.boot_payload()
		self.assertTrue(p["active"])
		self.assertEqual(p["latest_version"], "")

	def test_persist_then_clear_round_trip(self):
		release_notice.persist(
			{"active": True, "latest_version": "0.0.2", "title": "T", "message": "M", "url": "U"}
		)
		p = release_notice.boot_payload()
		self.assertTrue(p["active"])
		self.assertEqual(p["title"], "T")
		self.assertEqual(p["latest_version"], "0.0.2")
		# Empty dict clears every field.
		release_notice.persist({})
		p = release_notice.boot_payload()
		self.assertFalse(p["active"])
		self.assertEqual(p["title"], "")
		self.assertEqual(p["latest_version"], "")
