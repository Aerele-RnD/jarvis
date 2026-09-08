"""Stream E — bench maintenance-hold mirror + send gate (app tasks A1 + A2).

Pure toggle owned by the control plane: the bench mirrors {active, message}. An ABSENT
notice keeps the last-known state (decision 3) so the destroy+reprovision window can't
flip a live hold off. The send gate reads the mirror and refuses with reason
"maintenance". CP resolver/verb coverage lives in the jarvis_admin_v2 suite.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import maintenance_notice


class TestMaintenanceNotice(FrappeTestCase):
	def tearDown(self):
		maintenance_notice.persist({"active": False})

	def test_persist_active_and_boot(self):
		maintenance_notice.persist({"active": True, "message": "up"})
		p = maintenance_notice.boot_payload()
		self.assertTrue(p["active"])
		self.assertEqual(p["message"], "up")

	def test_present_false_clears(self):
		maintenance_notice.persist({"active": True})
		maintenance_notice.persist({"active": False})
		self.assertFalse(maintenance_notice.boot_payload()["active"])

	def test_absent_key_keeps_last_known(self):
		# The D-path unresolved-payload case: None must NOT clear a live hold.
		maintenance_notice.persist({"active": True, "message": "up"})
		maintenance_notice.persist(None)
		self.assertTrue(maintenance_notice.boot_payload()["active"])


class TestMaintenanceGate(FrappeTestCase):
	def test_gate_blocks_when_active(self):
		from jarvis.chat.policy import _maintenance_hold

		with patch("jarvis.maintenance_notice.boot_payload", return_value={"active": True}):
			self.assertTrue(_maintenance_hold())

	def test_gate_allows_when_inactive(self):
		from jarvis.chat.policy import _maintenance_hold

		with patch("jarvis.maintenance_notice.boot_payload", return_value={"active": False}):
			self.assertFalse(_maintenance_hold())

	def test_gate_fails_open(self):
		from jarvis.chat.policy import _maintenance_hold

		with patch("jarvis.maintenance_notice.boot_payload", side_effect=RuntimeError):
			self.assertFalse(_maintenance_hold())


class TestMaintenanceCheck(FrappeTestCase):
	"""check() re-pulls the connection from admin and refreshes the local mirror. It is
	de-duped by a short cache and folds the release refresh into the same round-trip; a
	failed round-trip must never drop a live hold."""

	def setUp(self):
		frappe.cache().delete_value(maintenance_notice._CHECK_CACHE_KEY)
		maintenance_notice.persist({"active": False})

	def tearDown(self):
		frappe.cache().delete_value(maintenance_notice._CHECK_CACHE_KEY)
		maintenance_notice.persist({"active": False})

	def test_check_keeps_last_known_on_admin_error(self):
		maintenance_notice.persist({"active": True, "message": "up"})
		with patch("jarvis.admin_client.get_connection", side_effect=RuntimeError("down")):
			out = maintenance_notice.check()  # must not raise
		self.assertTrue(out["active"])  # a failed poll must not clear a live hold
		self.assertTrue(maintenance_notice.boot_payload()["active"])

	def test_check_throttles_to_one_round_trip_in_window(self):
		with (
			patch(
				"jarvis.admin_client.get_connection", return_value={"maintenance": {"active": False}}
			) as gc,
			patch("jarvis.release_notice.persist"),
		):
			maintenance_notice.check()
			maintenance_notice.check()  # within the cache window -> no second call
		self.assertEqual(gc.call_count, 1)

	def test_check_refreshes_both_notices_and_applies_maintenance(self):
		conn = {
			"maintenance": {"active": True, "message": "rolling"},
			"release_notice": {"active": False},
		}
		with (
			patch("jarvis.admin_client.get_connection", return_value=conn),
			patch("jarvis.release_notice.persist") as rp,
		):
			out = maintenance_notice.check()
		rp.assert_called_once()  # one round-trip refreshes the release mirror too
		self.assertTrue(out["active"])
		self.assertEqual(out["message"], "rolling")

	def test_check_absent_maintenance_key_keeps_last_known(self):
		maintenance_notice.persist({"active": True, "message": "up"})
		conn = {"release_notice": {"active": False}}  # no "maintenance" key at all
		with (
			patch("jarvis.admin_client.get_connection", return_value=conn),
			patch("jarvis.release_notice.persist"),
		):
			out = maintenance_notice.check()
		self.assertTrue(out["active"])  # absent key = unknown -> keep last-known (decision 3)
