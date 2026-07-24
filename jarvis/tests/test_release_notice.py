"""Tests for jarvis.release_notice: version compare + boot payload."""

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


class TestUpdateAvailable(FrappeTestCase):
	def test_truth_table(self):
		ua = release_notice.update_available
		# behind -> update available
		self.assertTrue(ua("0.0.1", "0.0.2"))
		self.assertTrue(ua("1.2", "1.2.1"))
		# up-to-date or ahead -> not available
		self.assertFalse(ua("1.0.0", "1.0.0"))
		self.assertFalse(ua("0.1.0", "0.0.9"))
		self.assertFalse(ua("0.0.3", "0.0.2"))
		# fail-open on blank / unparseable (never a spurious gate)
		self.assertFalse(ua("", "0.0.2"))
		self.assertFalse(ua("0.0.1", ""))
		self.assertFalse(ua("abc", "0.0.2"))
		self.assertFalse(ua("0.0.1", "x.y.z"))


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

	def test_update_available_when_behind(self):
		# 99.0.0 is deliberately above any real jarvis __version__.
		self._set(
			release_notice_active=1,
			latest_jarvis_version="99.0.0",
			release_notice_title="Upgrade time",
			release_notice_message="notes",
			release_notice_url="https://x",
		)
		p = release_notice.boot_payload()
		self.assertTrue(p["active"])
		self.assertTrue(p["update_available"])
		self.assertEqual(p["latest_version"], "99.0.0")
		self.assertEqual(p["title"], "Upgrade time")
		self.assertEqual(p["current_version"], release_notice.INSTALLED_VERSION)

	def test_not_available_when_current(self):
		self._set(
			release_notice_active=1,
			latest_jarvis_version=release_notice.INSTALLED_VERSION,
			release_notice_title="t",
		)
		self.assertFalse(release_notice.boot_payload()["update_available"])

	def test_not_available_when_latest_blank(self):
		self._set(release_notice_active=1, latest_jarvis_version="", release_notice_title="t")
		self.assertFalse(release_notice.boot_payload()["update_available"])

	def test_persist_then_clear_round_trip(self):
		release_notice.persist(
			{"active": True, "latest_version": "99.0.0", "title": "T", "message": "M", "url": "U"}
		)
		p = release_notice.boot_payload()
		self.assertTrue(p["active"])
		self.assertEqual(p["title"], "T")
		# Empty dict clears every field.
		release_notice.persist({})
		p = release_notice.boot_payload()
		self.assertFalse(p["active"])
		self.assertEqual(p["title"], "")
		self.assertEqual(p["latest_version"], "")
