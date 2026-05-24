"""Tests for jarvis.diagnostics — the three Jarvis Settings buttons."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import diagnostics


class TestPingAdmin(FrappeTestCase):
	def setUp(self):
		s = frappe.get_single("Jarvis Settings")
		self._orig = s.get_password("jarvis_admin_api_key", raise_exception=False) or ""

	def tearDown(self):
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "jarvis_admin_api_key", self._orig)
		frappe.db.commit()

	def test_no_key_returns_config_error(self):
		with patch.object(
			frappe.get_single("Jarvis Settings").__class__, "get_password", return_value=""
		):
			out = diagnostics.ping_admin()
		self.assertFalse(out["ok"])
		self.assertEqual(out["kind"], "config")

	def test_happy_path(self):
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "jarvis_admin_api_key", "test-token")
		frappe.db.commit()
		with patch("jarvis.admin_client.get_connection",
				   return_value={"status": "active", "agent_url": "ws://localhost:19200"}):
			out = diagnostics.ping_admin()
		self.assertTrue(out["ok"])
		self.assertEqual(out["connection"]["status"], "active")

	def test_auth_failure_returns_kind_auth(self):
		from jarvis.exceptions import AdminAuthError
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "jarvis_admin_api_key", "bad-token")
		frappe.db.commit()
		with patch("jarvis.admin_client.get_connection", side_effect=AdminAuthError("admin returned 401")):
			out = diagnostics.ping_admin()
		self.assertFalse(out["ok"])
		self.assertEqual(out["kind"], "auth")
		self.assertIn("401", out["error"])

	def test_unreachable_returns_kind_unreachable(self):
		from jarvis.exceptions import AdminUnreachableError
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "jarvis_admin_api_key", "tok")
		frappe.db.commit()
		with patch("jarvis.admin_client.get_connection",
				   side_effect=AdminUnreachableError("connection refused")):
			out = diagnostics.ping_admin()
		self.assertFalse(out["ok"])
		self.assertEqual(out["kind"], "unreachable")


class TestPingOpenclaw(FrappeTestCase):
	def setUp(self):
		s = frappe.get_single("Jarvis Settings")
		self._orig_url = s.get("agent_url") or ""
		self._orig_tok = s.get_password("agent_token", raise_exception=False) or ""

	def tearDown(self):
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "agent_url", self._orig_url)
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "agent_token", self._orig_tok)
		frappe.db.commit()

	def test_missing_url_returns_config_error(self):
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "agent_url", "")
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "agent_token", "t")
		frappe.db.commit()
		out = diagnostics.ping_openclaw()
		self.assertFalse(out["ok"])
		self.assertEqual(out["kind"], "config")
		self.assertIn("agent_url", out["error"])

	def test_missing_token_returns_config_error(self):
		# Password fields ignore empty db_set; patch get_password to simulate
		# the "operator hasn't onboarded yet" state.
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "agent_url", "ws://h:1")
		frappe.db.commit()
		with patch.object(
			frappe.get_single("Jarvis Settings").__class__, "get_password", return_value=""
		):
			out = diagnostics.ping_openclaw()
		self.assertFalse(out["ok"])
		self.assertEqual(out["kind"], "config")
		self.assertIn("agent_token", out["error"])

	def test_happy_path(self):
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "agent_url", "ws://h:1")
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "agent_token", "t")
		frappe.db.commit()
		with patch("jarvis.openclaw_push.ping") as p:
			out = diagnostics.ping_openclaw()
		p.assert_called_once_with("ws://h:1", "t")
		self.assertTrue(out["ok"])

	def test_unreachable(self):
		from jarvis.exceptions import OpenclawUnreachableError
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "agent_url", "ws://h:1")
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "agent_token", "t")
		frappe.db.commit()
		with patch("jarvis.openclaw_push.ping", side_effect=OpenclawUnreachableError("refused")):
			out = diagnostics.ping_openclaw()
		self.assertFalse(out["ok"])
		self.assertEqual(out["kind"], "unreachable")


class TestForceResync(FrappeTestCase):
	def test_rejects_invalid_action(self):
		with self.assertRaises(frappe.ValidationError):
			diagnostics.force_resync(action="blowup")

	def test_admin_path_when_admin_key_set(self):
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "jarvis_admin_api_key", "tok")
		frappe.db.commit()
		try:
			with patch.object(
				frappe.get_single("Jarvis Settings").__class__, "_sync_via_admin"
			) as sa, patch.object(
				frappe.get_single("Jarvis Settings").__class__, "_sync_via_local_openclaw"
			) as sl:
				diagnostics.force_resync(action="reload")
			sa.assert_called_once_with("reload")
			sl.assert_not_called()
		finally:
			frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "jarvis_admin_api_key", "")
			frappe.db.commit()

	def test_local_path_when_no_admin_key(self):
		cls = frappe.get_single("Jarvis Settings").__class__
		with patch.object(cls, "get_password", return_value=""), \
			 patch.object(cls, "_sync_via_admin") as sa, \
			 patch.object(cls, "_sync_via_local_openclaw") as sl:
			diagnostics.force_resync(action="restart")
		sl.assert_called_once_with("restart")
		sa.assert_not_called()
