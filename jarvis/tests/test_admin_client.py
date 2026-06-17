"""Tests for jarvis.admin_client - HTTPS wrapper for jarvis_admin calls.

All HTTP is mocked. Tests verify header construction, error mapping,
envelope unwrapping, and missing-config handling.
"""

from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.tests.utils import FrappeTestCase

from jarvis import admin_client
from jarvis.admin_client import (
	DEFAULT_ADMIN_URL,
	DEFAULT_TIMEOUT_S,
	AdminAuthError,
	AdminUnreachableError,
	AdminValidationError,
	post_update_llm_creds,
)


def _settings_for_admin(admin_url="https://admin.example.com",
						api_key="customer-key-123", api_secret="customer-secret-456"):
	"""Configure Jarvis Settings for the admin path. Uses db_set to bypass
	read_only on the fields."""
	settings = frappe.get_single("Jarvis Settings")
	settings.db_set("jarvis_admin_url", admin_url)
	settings.db_set("jarvis_admin_api_key", api_key)
	settings.db_set("jarvis_admin_api_secret", api_secret)
	frappe.db.commit()


def _settings_clear_admin():
	from frappe.utils.password import remove_encrypted_password
	settings = frappe.get_single("Jarvis Settings")
	settings.db_set("jarvis_admin_url", "")
	# Password fields need __Auth cleared too, not just the column.
	for f in ("jarvis_admin_api_key", "jarvis_admin_api_secret"):
		remove_encrypted_password("Jarvis Settings", "Jarvis Settings", f)
		settings.db_set(f, "")
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
		_settings_for_admin(admin_url="https://admin.example.com",
							api_key="hdr-key", api_secret="hdr-secret")

	def tearDown(self):
		_settings_clear_admin()

	def test_sends_native_token_header(self):
		captured = {}

		def _fake_post(url, json=None, headers=None, timeout=None):
			captured["url"] = url
			captured["headers"] = headers
			captured["json"] = json
			captured["timeout"] = timeout
			return _mock_response(200, json_body={"message": {"ok": True, "data": {"action": "reload"}}})

		with patch("requests.post", side_effect=_fake_post):
			post_update_llm_creds("p", "m", "b", "k")

		self.assertEqual(captured["headers"]["Authorization"], "token hdr-key:hdr-secret")
		self.assertNotIn("X-Jarvis-Site", captured["headers"])
		self.assertEqual(captured["headers"]["Content-Type"], "application/json")
		self.assertEqual(captured["timeout"], DEFAULT_TIMEOUT_S)
		self.assertEqual(captured["json"], {
			"provider": "p", "model": "m", "base_url": "b", "api_key": "k",
			"auth_mode": "api_key",
		})
		self.assertTrue(captured["url"].startswith("https://admin.example.com/api/method/"))
		self.assertIn("jarvis_admin.api.tenant.update_llm_creds", captured["url"])

	def test_raises_when_credentials_missing(self):
		from jarvis.exceptions import AdminAuthError
		_settings_clear_admin()
		with self.assertRaises(AdminAuthError):
			post_update_llm_creds("p", "m", "b", "k")

	def test_api_key_decrypted_via_get_password_not_attribute(self):
		"""Regression: jarvis_admin_api_key is a Password field. Attribute
		access on the settings doc returns Frappe's masked "*****" placeholder;
		only get_password() decrypts the real value out of __Auth. The previous
		bug read the attribute and shipped "*****" as the api_key, which admin
		rejected with 401 (see signup flow last_sync_status leakage)."""
		captured = {}

		def _fake_post(url, json=None, headers=None, timeout=None):
			captured["headers"] = headers
			return _mock_response(200, json_body={"message": {"ok": True, "data": {"action": "reload"}}})

		fake_settings = MagicMock()
		# Mimic the production load: attribute is the masked placeholder.
		fake_settings.jarvis_admin_api_key = "*****"
		fake_settings.jarvis_admin_url = "https://admin.example.com"
		# get_password returns the decrypted real value.
		def _get_password(field, raise_exception=False):
			return {"jarvis_admin_api_key": "real-key-xyz",
					"jarvis_admin_api_secret": "real-secret-abc"}.get(field, "")
		fake_settings.get_password.side_effect = _get_password

		with patch("frappe.get_single", return_value=fake_settings), \
			 patch("requests.post", side_effect=_fake_post):
			post_update_llm_creds("p", "m", "b", "k")

		self.assertEqual(captured["headers"]["Authorization"],
						 "token real-key-xyz:real-secret-abc")
		self.assertNotIn("*", captured["headers"]["Authorization"])


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

	# Sprint-3 PR-8: 4xx envelope responses route to AdminValidationError,
	# not AdminUnreachableError. Used to be one bucket; UI showed
	# "admin is unreachable" for things like NoRunningTenant or
	# downgrade-not-supported.

	def test_400_with_envelope_raises_validation_error(self):
		"""InvalidArgument / InvalidToken / InvalidBlob etc. on tenant.py
		now show up on the bench as AdminValidationError - operator-actionable
		clean text, not "admin is unreachable; try again."""
		mock_post = MagicMock(return_value=_mock_response(
			400, json_body={"message": {
				"ok": False, "error": {"code": "InvalidToken", "message": "token too short"},
			}},
		))
		with patch("requests.post", mock_post):
			with self.assertRaises(AdminValidationError) as cm:
				post_update_llm_creds("p", "m", "b", "k")
		self.assertEqual(str(cm.exception), "token too short")

	def test_409_with_envelope_raises_validation_error(self):
		"""NoRunningTenant (409) is a business-rule error, not a network
		failure - now routes to AdminValidationError so _surface() shows
		the actual reason."""
		mock_post = MagicMock(return_value=_mock_response(
			409, json_body={"message": {
				"ok": False, "error": {"code": "NoRunningTenant", "message": "no running tenant"},
			}},
		))
		with patch("requests.post", mock_post):
			with self.assertRaises(AdminValidationError) as cm:
				post_update_llm_creds("p", "m", "b", "k")
		self.assertEqual(str(cm.exception), "no running tenant")

	def test_5xx_envelope_still_raises_unreachable(self):
		"""5xx is genuinely server-side; the unreachable class is correct."""
		mock_post = MagicMock(return_value=_mock_response(
			503, json_body={"message": {
				"ok": False, "error": {"code": "ServiceUnavailable", "message": "down"},
			}},
		))
		with patch("requests.post", mock_post):
			with self.assertRaises(AdminUnreachableError):
				post_update_llm_creds("p", "m", "b", "k")

	def test_frappe_validation_error_surfaces_clean_message(self):
		"""When admin raises frappe.ValidationError inside a whitelisted endpoint
		(e.g. dev_force_signup → _reject_duplicate_email), the response body has
		Frappe's exc_type/_server_messages envelope, not the {ok, error} shape.
		We extract the user-facing message and raise AdminValidationError."""
		mock_post = MagicMock(return_value=_mock_response(
			417,
			json_body={
				"exception": "frappe.exceptions.ValidationError: An active account already exists for venkat@aerele.in",
				"exc_type": "ValidationError",
				"_server_messages": '["{\\"message\\": \\"An active account already exists for venkat@aerele.in\\", \\"indicator\\": \\"red\\"}"]',
				"exc": "[\"Traceback (most recent call last):\\n...\"]",
			},
		))
		with patch("requests.post", mock_post):
			with self.assertRaises(AdminValidationError) as cm:
				post_update_llm_creds("p", "m", "b", "k")
		self.assertEqual(str(cm.exception),
						 "An active account already exists for venkat@aerele.in")
		# No traceback dump should leak into the message.
		self.assertNotIn("Traceback", str(cm.exception))
		self.assertNotIn("frappe.exceptions.", str(cm.exception))

	def test_frappe_validation_error_falls_back_to_exception_string(self):
		"""If _server_messages is missing/empty, parse the message from the
		`exception` field by stripping the class prefix."""
		mock_post = MagicMock(return_value=_mock_response(
			417,
			json_body={
				"exception": "frappe.exceptions.DuplicateEntryError: Customer C-001 already exists",
				"exc_type": "DuplicateEntryError",
			},
		))
		with patch("requests.post", mock_post):
			with self.assertRaises(AdminValidationError) as cm:
				post_update_llm_creds("p", "m", "b", "k")
		self.assertEqual(str(cm.exception), "Customer C-001 already exists")

	def test_frappe_permission_error_routes_to_auth_error(self):
		mock_post = MagicMock(return_value=_mock_response(
			403,
			json_body={
				"exception": "frappe.exceptions.PermissionError: customer status: Suspended",
				"exc_type": "PermissionError",
			},
		))
		with patch("requests.post", mock_post):
			with self.assertRaises(AdminAuthError) as cm:
				post_update_llm_creds("p", "m", "b", "k")
		self.assertEqual(str(cm.exception), "customer status: Suspended")


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

	def test_no_credentials_raises_auth_error(self):
		"""api_key + api_secret are required; missing either raises early."""
		from jarvis.exceptions import AdminAuthError
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("jarvis_admin_url", "https://admin.example.com")
		settings.db_set("jarvis_admin_api_key", "")
		settings.db_set("jarvis_admin_api_secret", "")
		frappe.db.commit()
		try:
			with self.assertRaises(AdminAuthError):
				post_update_llm_creds("p", "m", "b", "k")
		finally:
			_settings_clear_admin()

	def test_no_secret_raises_auth_error(self):
		from jarvis.exceptions import AdminAuthError
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("jarvis_admin_url", "https://admin.example.com")
		settings.db_set("jarvis_admin_api_key", "some-key")
		settings.db_set("jarvis_admin_api_secret", "")
		frappe.db.commit()
		try:
			with self.assertRaises(AdminAuthError):
				post_update_llm_creds("p", "m", "b", "k")
		finally:
			_settings_clear_admin()


class TestOnboardingClient(FrappeTestCase):
	def tearDown(self):
		_settings_clear_admin()

	def test_signup_unwraps_data_and_uses_default_url_when_unset(self):
		_settings_clear_admin()  # no jarvis_admin_url → DEFAULT_ADMIN_URL
		captured = {}

		def _fake_post(url, json=None, headers=None, timeout=None):
			captured["url"] = url
			captured["json"] = json
			return _mock_response(200, json_body={"message": {"ok": True, "data": {
				"api_key": "k", "api_secret": "s", "razorpay_key_id": "rzp"}}})

		with patch("requests.post", side_effect=_fake_post):
			out = admin_client.signup("e@x.com", "Co", "Annual Plan")
		self.assertEqual(out["api_key"], "k")
		self.assertEqual(out["api_secret"], "s")
		self.assertTrue(captured["url"].startswith(DEFAULT_ADMIN_URL))
		self.assertIn("billing.signup.signup", captured["url"])
		self.assertEqual(captured["json"]["email"], "e@x.com")

	def test_get_plans_returns_list(self):
		_settings_for_admin()
		with patch("requests.post", return_value=_mock_response(
				200, json_body={"message": {"ok": True, "data": [{"name": "p1", "plan_name": "P1"}]}})):
			out = admin_client.get_plans()
		self.assertEqual(out[0]["name"], "p1")

	def test_get_connection_unwraps_data(self):
		_settings_for_admin()
		with patch("requests.post", return_value=_mock_response(
				200, json_body={"message": {"ok": True, "data": {"agent_url": "ws://localhost:19000", "tenant_status": "running"}}})):
			out = admin_client.get_connection()
		self.assertEqual(out["agent_url"], "ws://localhost:19000")

	def test_dev_signup_returns_flat_dict(self):
		_settings_for_admin()
		with patch("requests.post", return_value=_mock_response(
				200, json_body={"message": {"customer": "C1", "api_key": "k", "api_secret": "s",
				"agent_url": "ws://localhost:19000", "agent_token": "k"}})):
			out = admin_client.dev_signup("e@x.com", "Co", "Annual Plan")
		self.assertEqual(out["api_key"], "k")
		self.assertEqual(out["api_secret"], "s")
		self.assertEqual(out["agent_url"], "ws://localhost:19000")

	def test_renew_posts_to_renew_and_unwraps_order(self):
		_settings_for_admin(api_key="renew-key", api_secret="renew-secret")
		captured = {}

		def _fake_post(url, json=None, headers=None, timeout=None):
			captured["url"] = url
			captured["headers"] = headers
			return _mock_response(200, json_body={"message": {"ok": True, "data": {
				"razorpay_order_id": "order_R", "razorpay_key_id": "rzp", "amount_inr": 1500}}})

		with patch("requests.post", side_effect=_fake_post):
			out = admin_client.renew()
		self.assertEqual(out["razorpay_order_id"], "order_R")
		self.assertIn("jarvis_admin.api.tenant.renew", captured["url"])
		self.assertEqual(captured["headers"]["Authorization"], "token renew-key:renew-secret")

	def test_guest_call_omits_authorization_header(self):
		# get_plans is a guest endpoint - no auth header is sent.
		_settings_clear_admin()
		captured = {}

		def _fake_post(url, json=None, headers=None, timeout=None):
			captured["headers"] = headers
			return _mock_response(200, json_body={"message": {"ok": True, "data": []}})

		with patch("requests.post", side_effect=_fake_post):
			admin_client.get_plans()
		self.assertNotIn("Authorization", captured["headers"])


class TestPostUpdateLlmCredsAuthMode(FrappeTestCase):
	def setUp(self):
		_settings_for_admin()

	def tearDown(self):
		_settings_clear_admin()

	def test_default_auth_mode_is_api_key(self):
		captured = {}

		def _fake_post(url, json=None, **_kw):
			captured["body"] = json
			return _mock_response(200, json_body={"message": {"ok": True, "data": {"action": "restart"}}})

		with patch("requests.post", side_effect=_fake_post):
			post_update_llm_creds(provider="OpenAI", model="gpt-4o", base_url="", api_key="sk-1")
		self.assertEqual(captured["body"]["auth_mode"], "api_key")

	def test_explicit_subscription_auth_mode(self):
		captured = {}

		def _fake_post(url, json=None, **_kw):
			captured["body"] = json
			return _mock_response(200, json_body={"message": {"ok": True, "data": {"action": "restart"}}})

		with patch("requests.post", side_effect=_fake_post):
			post_update_llm_creds(
				provider="OpenAI", model="", base_url="",
				api_key="AT-1", auth_mode="subscription",
			)
		self.assertEqual(captured["body"]["auth_mode"], "subscription")
		self.assertEqual(captured["body"]["api_key"], "AT-1")


class TestPostRotateLlmSecret(FrappeTestCase):
	def setUp(self):
		_settings_for_admin()

	def tearDown(self):
		_settings_clear_admin()

	def test_happy_path(self):
		captured = {}

		def _fake_post(url, json=None, **_kw):
			captured["url"] = url
			captured["body"] = json
			return _mock_response(200, json_body={"message": {"ok": True, "data": {"action": "reload"}}})

		with patch("requests.post", side_effect=_fake_post):
			result = admin_client.post_rotate_llm_secret(secret="AT-rotated")
		self.assertEqual(result.get("action"), "reload")
		self.assertIn("rotate_llm_secret", captured["url"])
		self.assertEqual(captured["body"], {"secret": "AT-rotated"})

	def test_429_raises_AdminRateLimitedError(self):
		from jarvis.exceptions import AdminRateLimitedError
		mock_post = MagicMock(return_value=_mock_response(
			429,
			json_body={"message": {"ok": False, "error": {
				"code": "RateLimitExceeded",
				"message": "rotation rate limit hit",
				"retry_after_seconds": 1200,
			}}},
		))
		with patch("requests.post", mock_post):
			with self.assertRaises(AdminRateLimitedError) as ctx:
				admin_client.post_rotate_llm_secret(secret="AT-x")
		self.assertEqual(ctx.exception.retry_after_seconds, 1200)


class TestPostPushOauthBlob(FrappeTestCase):
	def setUp(self):
		_settings_for_admin()

	def tearDown(self):
		_settings_clear_admin()

	def test_happy_path_posts_blob(self):
		captured = {}
		blob = {"type": "oauth", "provider": "openai-codex",
				"access": "AT-fresh", "refresh": "RT-fresh", "expires": 1735689600}

		def _fake_post(url, json=None, timeout=None, **_kw):
			captured["url"] = url
			captured["body"] = json
			captured["timeout"] = timeout
			return _mock_response(200, json_body={"message": {"ok": True, "data": {"ok": True}}})

		with patch("requests.post", side_effect=_fake_post):
			result = admin_client.post_push_oauth_blob("openai-codex", blob)
		self.assertEqual(result, {"ok": True})
		self.assertIn("push_oauth_blob", captured["url"])
		self.assertEqual(captured["body"], {"provider": "openai-codex", "blob": blob})
		# Timeout must exceed admin's own put_auth_profile bound (150s) so
		# bench doesn't time out before admin can return. Lower bound
		# locked at 180s; raise this and admin's bound together if either
		# bumps. Doctor + restart + healthz easily fits inside 150s on a
		# healthy host.
		self.assertGreaterEqual(captured["timeout"], 180,
			"post_push_oauth_blob timeout must accommodate fleet-agent's "
			"doctor + restart + healthz chain (~120s typical, 150s cap)")


class TestPostSubscriptionDisconnect(FrappeTestCase):
	def setUp(self):
		_settings_for_admin()

	def tearDown(self):
		_settings_clear_admin()

	def test_happy_path(self):
		captured = {}

		def _fake_post(url, json=None, **_kw):
			captured["url"] = url
			captured["body"] = json
			return _mock_response(200, json_body={"message": {"ok": True, "data": {"ok": True}}})

		with patch("requests.post", side_effect=_fake_post):
			result = admin_client.post_subscription_disconnect()
		self.assertEqual(result, {"ok": True})
		self.assertIn("subscription_disconnect", captured["url"])
		self.assertEqual(captured["body"], {})
