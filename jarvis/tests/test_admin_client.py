"""Tests for jarvis.admin_client — HTTPS wrapper for jarvis_admin calls.

All HTTP is mocked. Tests verify header construction, error mapping,
envelope unwrapping, and missing-config handling.
"""

from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.tests.utils import FrappeTestCase

from jarvis.admin_client import (
	DEFAULT_TIMEOUT_S,
	AdminAuthError,
	AdminUnreachableError,
	post_update_llm_creds,
)


def _settings_for_admin(admin_url="https://admin.example.com", token="customer-token-123"):
	"""Configure Jarvis Settings for the admin path. Uses db_set to bypass
	read_only on the fields."""
	settings = frappe.get_single("Jarvis Settings")
	settings.db_set("jarvis_admin_url", admin_url)
	settings.db_set("jarvis_admin_api_key", token)
	frappe.db.commit()


def _settings_clear_admin():
	settings = frappe.get_single("Jarvis Settings")
	settings.db_set("jarvis_admin_url", "")
	settings.db_set("jarvis_admin_api_key", "")
	frappe.db.commit()


def _mock_response(status_code: int, json_body=None, text: str = ""):
	resp = MagicMock(spec=requests.Response)
	resp.status_code = status_code
	if json_body is None:
		resp.json.side_effect = ValueError("no json")
		resp.text = text
	else:
		resp.json.return_value = json_body
		resp.text = text or ""
	return resp


class TestHappyPath(FrappeTestCase):
	def setUp(self):
		_settings_for_admin()

	def tearDown(self):
		_settings_clear_admin()

	def test_reload_returns_unwrapped_data(self):
		mock_post = MagicMock(return_value=_mock_response(
			200, json_body={"message": {"ok": True, "data": {"action": "reload", "result": "ok"}}},
		))
		with patch("requests.post", mock_post):
			result = post_update_llm_creds(
				provider="Anthropic", model="claude-sonnet-4-6",
				base_url="https://api.anthropic.com", api_key="sk-new",
			)
		self.assertEqual(result, {"action": "reload", "result": "ok"})

	def test_restart_returns_unwrapped_data(self):
		mock_post = MagicMock(return_value=_mock_response(
			200, json_body={"message": {"ok": True, "data": {"action": "restart", "result": "ok"}}},
		))
		with patch("requests.post", mock_post):
			result = post_update_llm_creds("OpenAI", "gpt-4o", "https://api.openai.com", "sk-new")
		self.assertEqual(result["action"], "restart")


class TestHeaders(FrappeTestCase):
	def setUp(self):
		_settings_for_admin(admin_url="https://admin.example.com", token="tkn-headers-test")

	def tearDown(self):
		_settings_clear_admin()

	def test_sends_bearer_and_site_headers(self):
		captured = {}

		def _fake_post(url, json=None, headers=None, timeout=None):
			captured["url"] = url
			captured["headers"] = headers
			captured["json"] = json
			captured["timeout"] = timeout
			return _mock_response(200, json_body={"message": {"ok": True, "data": {"action": "reload"}}})

		with patch("requests.post", side_effect=_fake_post):
			post_update_llm_creds("p", "m", "b", "k")

		self.assertEqual(captured["headers"]["Authorization"], "Bearer tkn-headers-test")
		self.assertIn("X-Jarvis-Site", captured["headers"])
		self.assertEqual(captured["headers"]["Content-Type"], "application/json")
		self.assertEqual(captured["timeout"], DEFAULT_TIMEOUT_S)
		self.assertEqual(captured["json"], {
			"provider": "p", "model": "m", "base_url": "b", "api_key": "k",
		})
		self.assertTrue(captured["url"].startswith("https://admin.example.com/api/method/"))
		self.assertIn("jarvis_admin.api.tenant.update_llm_creds", captured["url"])


class TestNetworkErrors(FrappeTestCase):
	def setUp(self):
		_settings_for_admin()

	def tearDown(self):
		_settings_clear_admin()

	def test_connection_error_raises_unreachable(self):
		with patch("requests.post", side_effect=requests.ConnectionError("refused")):
			with self.assertRaises(AdminUnreachableError):
				post_update_llm_creds("p", "m", "b", "k")

	def test_timeout_raises_unreachable(self):
		with patch("requests.post", side_effect=requests.Timeout("read timeout")):
			with self.assertRaises(AdminUnreachableError):
				post_update_llm_creds("p", "m", "b", "k")


class TestAdminErrorResponses(FrappeTestCase):
	def setUp(self):
		_settings_for_admin()

	def tearDown(self):
		_settings_clear_admin()

	def test_401_raises_auth_error(self):
		mock_post = MagicMock(return_value=_mock_response(
			401, json_body={"message": {"ok": False, "error": {"code": "AuthenticationError", "message": "bad token"}}},
		))
		with patch("requests.post", mock_post):
			with self.assertRaises(AdminAuthError) as cm:
				post_update_llm_creds("p", "m", "b", "k")
		self.assertIn("bad token", str(cm.exception))

	def test_403_raises_auth_error(self):
		mock_post = MagicMock(return_value=_mock_response(
			403, json_body={"message": {"ok": False, "error": {"code": "AuthenticationError", "message": "suspended"}}},
		))
		with patch("requests.post", mock_post):
			with self.assertRaises(AdminAuthError):
				post_update_llm_creds("p", "m", "b", "k")

	def test_500_raises_unreachable(self):
		mock_post = MagicMock(return_value=_mock_response(
			500, json_body={"message": {"ok": False, "error": {"code": "ServerError", "message": "boom"}}},
		))
		with patch("requests.post", mock_post):
			with self.assertRaises(AdminUnreachableError):
				post_update_llm_creds("p", "m", "b", "k")

	def test_200_with_ok_false_raises_unreachable(self):
		mock_post = MagicMock(return_value=_mock_response(
			200, json_body={"message": {"ok": False, "error": {"code": "NoRunningTenant", "message": "no tenant"}}},
		))
		with patch("requests.post", mock_post):
			with self.assertRaises(AdminUnreachableError) as cm:
				post_update_llm_creds("p", "m", "b", "k")
		self.assertIn("NoRunningTenant", str(cm.exception))


class TestNonJsonResponse(FrappeTestCase):
	def setUp(self):
		_settings_for_admin()

	def tearDown(self):
		_settings_clear_admin()

	def test_html_error_page_raises_unreachable(self):
		mock_post = MagicMock(return_value=_mock_response(
			500, json_body=None, text="<html>Internal Server Error</html>",
		))
		with patch("requests.post", mock_post):
			with self.assertRaises(AdminUnreachableError) as cm:
				post_update_llm_creds("p", "m", "b", "k")
		self.assertIn("non-JSON", str(cm.exception))


class TestMissingConfig(FrappeTestCase):
	def setUp(self):
		_settings_clear_admin()

	def test_no_admin_url_raises_unreachable(self):
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("jarvis_admin_url", "")
		settings.db_set("jarvis_admin_api_key", "some-token")
		frappe.db.commit()
		try:
			with self.assertRaises(AdminUnreachableError):
				post_update_llm_creds("p", "m", "b", "k")
		finally:
			_settings_clear_admin()

	def test_no_token_raises_unreachable(self):
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("jarvis_admin_url", "https://admin.example.com")
		settings.db_set("jarvis_admin_api_key", "")
		frappe.db.commit()
		try:
			with self.assertRaises(AdminUnreachableError):
				post_update_llm_creds("p", "m", "b", "k")
		finally:
			_settings_clear_admin()
