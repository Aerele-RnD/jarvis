"""Tests for jarvis.release_notice: persist + boot payload. The control plane
decides which notice applies (per host); the bench mirrors and renders it."""

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
