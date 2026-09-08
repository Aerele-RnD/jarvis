"""Tests for jarvis.announcement: persist + boot_payload for the soft banner.

The announcement mirror has no gate, no version self-clear and no on-demand
re-check (unlike release_notice) - the only server logic is the persist/clear
round-trip and a TOTAL boot_payload whose only computed bit is the strict expiry
boundary. These pin the hardening points H1-H4/H2 folded in at /plan-check.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import announcement

_FIELDS = announcement._FIELDS

# A fixed "now" for the expiry-boundary tests: pinning now_datetime makes the
# strict `now < expires_on` boundary deterministic (no clock race).
_NOW = "2030-06-01 12:00:00"


def _snapshot() -> dict:
	s = frappe.get_single("Jarvis Settings")
	return {f: s.get(f) for f in _FIELDS}


def _restore(snap: dict) -> None:
	s = frappe.get_single("Jarvis Settings")
	for f, v in snap.items():
		s.db_set(f, v)
	frappe.db.commit()


class TestAnnouncementBoot(FrappeTestCase):
	def setUp(self):
		self._snap = _snapshot()

	def tearDown(self):
		_restore(self._snap)

	def _set(self, **kw):
		s = frappe.get_single("Jarvis Settings")
		for k, v in kw.items():
			s.db_set(k, v)
		frappe.db.commit()

	# -- shape ----------------------------------------------------------------

	def test_active_announcement_shape(self):
		announcement.persist(
			{
				"active": True,
				"id": "ANN-00001",
				"title": "Scheduled maintenance",
				"message": "We update Sunday 02:00 UTC.",
				"severity": "Warning",
				"link_url": "https://status.example.com",
				"link_label": "Status page",
				"interval_days": 3,
			}
		)
		p = announcement.boot_payload()
		self.assertTrue(p["active"])
		self.assertEqual(p["id"], "ANN-00001")
		self.assertEqual(p["title"], "Scheduled maintenance")
		self.assertEqual(p["message"], "We update Sunday 02:00 UTC.")
		self.assertEqual(p["severity"], "Warning")
		self.assertEqual(p["link_url"], "https://status.example.com")
		self.assertEqual(p["link_label"], "Status page")
		self.assertEqual(p["interval_days"], 3)

	def test_inactive_announcement(self):
		announcement.persist({"active": False, "id": "ANN-1", "message": "m"})
		self.assertFalse(announcement.boot_payload()["active"])

	def test_empty_dict_clears(self):
		announcement.persist({"active": True, "id": "ANN-1", "title": "t", "message": "m"})
		self.assertTrue(announcement.boot_payload()["active"])
		announcement.persist({})
		p = announcement.boot_payload()
		self.assertFalse(p["active"])
		self.assertEqual(p["id"], "")
		self.assertEqual(p["title"], "")
		self.assertEqual(p["message"], "")

	def test_persist_then_clear_round_trip(self):
		announcement.persist(
			{"active": True, "id": "ANN-7", "title": "T", "message": "M", "severity": "Info"}
		)
		p = announcement.boot_payload()
		self.assertTrue(p["active"])
		self.assertEqual(p["id"], "ANN-7")
		announcement.persist({})
		p = announcement.boot_payload()
		self.assertFalse(p["active"])
		self.assertEqual(p["id"], "")
		self.assertEqual(p["severity"], "")

	# -- no-op-skip (H3) ------------------------------------------------------

	def test_persist_skips_write_when_unchanged(self):
		ann = {"active": True, "id": "ANN-2", "title": "t", "message": "m", "interval_days": 5}
		announcement.persist(ann)
		before = frappe.db.get_value("Jarvis Settings", "Jarvis Settings", "modified")
		announcement.persist(ann)
		self.assertEqual(frappe.db.get_value("Jarvis Settings", "Jarvis Settings", "modified"), before)

	def test_persist_skips_write_when_unchanged_with_expiry(self):
		# H3: a SET expiry must normalize both sides so an unchanged announcement
		# with an expiry doesn't force a write every persist (write-amplification on
		# the hot gate path). The DB reads back a datetime; the wire sends a string.
		ann = {"active": True, "id": "ANN-3", "message": "m", "expires_on": "2031-01-01 09:30:00"}
		announcement.persist(ann)
		before = frappe.db.get_value("Jarvis Settings", "Jarvis Settings", "modified")
		announcement.persist(ann)
		self.assertEqual(frappe.db.get_value("Jarvis Settings", "Jarvis Settings", "modified"), before)

	# -- expires_on storage (H2) ----------------------------------------------

	def test_absent_expiry_stored_as_null(self):
		# H2: a Datetime column rejects "" - an absent expiry must land as NULL, or
		# persist raises and swallows, silently killing the channel.
		announcement.persist({"active": True, "id": "ANN-4", "message": "m"})
		stored = frappe.db.get_value("Jarvis Settings", "Jarvis Settings", "announcement_expires_on")
		self.assertIsNone(stored)

	def test_blank_expiry_stored_as_null(self):
		announcement.persist({"active": True, "id": "ANN-4b", "message": "m", "expires_on": ""})
		stored = frappe.db.get_value("Jarvis Settings", "Jarvis Settings", "announcement_expires_on")
		self.assertIsNone(stored)

	# -- expiry boundary (H4), strict now < expires_on ------------------------

	def test_active_when_expiry_in_future(self):
		self._set(
			announcement_active=1,
			announcement_id="ANN-5",
			announcement_expires_on="2030-06-01 12:00:01",
		)
		with patch.object(announcement, "now_datetime", return_value=announcement.get_datetime(_NOW)):
			self.assertTrue(announcement.boot_payload()["active"])

	def test_inactive_when_expiry_in_past(self):
		self._set(
			announcement_active=1,
			announcement_id="ANN-5",
			announcement_expires_on="2030-06-01 11:59:59",
		)
		with patch.object(announcement, "now_datetime", return_value=announcement.get_datetime(_NOW)):
			self.assertFalse(announcement.boot_payload()["active"])

	def test_inactive_when_expiry_exactly_now(self):
		# Strict boundary: at the instant of expiry the banner is already OFF.
		self._set(announcement_active=1, announcement_id="ANN-5", announcement_expires_on=_NOW)
		with patch.object(announcement, "now_datetime", return_value=announcement.get_datetime(_NOW)):
			self.assertFalse(announcement.boot_payload()["active"])

	def test_active_with_no_expiry_never_gates(self):
		self._set(announcement_active=1, announcement_id="ANN-6", announcement_expires_on=None)
		self.assertTrue(announcement.boot_payload()["active"])

	# -- TOTAL boot_payload (H1) ----------------------------------------------

	def test_boot_payload_never_raises_on_garbage_expiry(self):
		# H1: a bad expires_on that get_datetime can't parse must NOT 500 the bare
		# boot call - it falls back to the stored active (fail toward showing).
		row = {f: "" for f in _FIELDS}
		row["announcement_active"] = 1
		row["announcement_id"] = "ANN-9"
		row["announcement_expires_on"] = "not-a-date"
		with patch("frappe.get_cached_value", return_value=row):
			p = announcement.boot_payload()
		self.assertTrue(p["active"])
		self.assertEqual(p["id"], "ANN-9")


class TestAnnouncementWiring(FrappeTestCase):
	"""The daily sync forwards the announcement to persist, and a reset clears the
	mirror (H6). The chat-gate persist site is covered in test_account's
	TestAdminChatGate, beside the release-notice precedent."""

	def test_sync_connection_forwards_announcement_to_persist(self):
		# The recurring scheduled sync must forward the backend-sent announcement to
		# announcement.persist (co-located with the release_notice.persist precedent).
		from jarvis import onboarding

		conn = {
			"announcement": {"active": True, "id": "ANN-1"},
			"release_notice": {},
			"redaction_patterns": [],
			"agent_url": "",
		}
		with (
			patch("jarvis.onboarding.require_jarvis_admin"),
			patch("jarvis.onboarding.frappe.get_single") as gs,
			patch("jarvis.onboarding.admin_client.get_connection", return_value=conn),
			patch("jarvis.onboarding.release_notice.persist"),
			patch("jarvis.onboarding.announcement.persist") as persist,
			patch("jarvis.chat.egress_rules.persist"),
		):
			gs.return_value.get_password.return_value = "x"  # api key/secret present
			onboarding.sync_connection()
		persist.assert_called_once_with({"active": True, "id": "ANN-1"})

	def test_settings_reset_clears_announcement_mirror(self):
		# H6: a reset must clear the previous tenancy's announcement mirror. The
		# string fields blank, the scalars zero, and the Datetime NULLs.
		from jarvis import settings_reset

		for f in (
			"announcement_id",
			"announcement_title",
			"announcement_message",
			"announcement_severity",
			"announcement_link_url",
			"announcement_link_label",
		):
			self.assertIn(f, settings_reset.CONNECTION.blank)
		self.assertIn("announcement_active", settings_reset.CONNECTION.zero)
		self.assertIn("announcement_interval_days", settings_reset.CONNECTION.zero)
		self.assertIn("announcement_expires_on", settings_reset.CONNECTION.null)
		# FULL composes CONNECTION | LLM, so the parity carries into the CLI reset too.
		self.assertIn("announcement_active", settings_reset.FULL.zero)
		self.assertIn("announcement_expires_on", settings_reset.FULL.null)
