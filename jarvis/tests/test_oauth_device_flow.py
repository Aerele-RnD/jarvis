import unittest
from unittest.mock import MagicMock, patch

import requests

from jarvis.exceptions import InvalidArgumentError
from jarvis.oauth import device_flow


def _mock_response(status_code: int, json_body: dict | None = None):
	resp = MagicMock(spec=requests.Response)
	resp.status_code = status_code
	resp.json.return_value = json_body or {}
	resp.ok = 200 <= status_code < 300
	return resp


class TestDeviceFlowStart(unittest.TestCase):
	@patch("jarvis.oauth.device_flow.requests.post")
	def test_start_happy_path(self, mock_post):
		mock_post.return_value = _mock_response(200, {
			"device_code": "DC-abc",
			"user_code": "JARV-9X3K",
			"verification_uri": "https://chatgpt.com/auth/device",
			"interval": 5,
			"expires_in": 600,
		})
		envelope = device_flow.start("OpenAI", client_id="CLIENT_ID_OPENAI")
		self.assertEqual(envelope["user_code"], "JARV-9X3K")
		self.assertEqual(envelope["device_code"], "DC-abc")
		self.assertEqual(envelope["interval"], 5)
		mock_post.assert_called_once()
		called_url = mock_post.call_args.args[0]
		self.assertEqual(called_url, "https://auth.openai.com/oauth/device/code")

	@patch("jarvis.oauth.device_flow.requests.post")
	def test_start_unknown_provider_raises(self, mock_post):
		with self.assertRaises(InvalidArgumentError):
			device_flow.start("Anthropic", client_id="x")
		mock_post.assert_not_called()

	@patch("jarvis.oauth.device_flow.requests.post")
	def test_start_5xx_raises_provider_error(self, mock_post):
		mock_post.return_value = _mock_response(503)
		with self.assertRaises(device_flow.ProviderUnavailable):
			device_flow.start("OpenAI", client_id="x")


class TestDeviceFlowPoll(unittest.TestCase):
	@patch("jarvis.oauth.device_flow.requests.post")
	def test_poll_pending_returns_pending_sentinel(self, mock_post):
		mock_post.return_value = _mock_response(400, {"error": "authorization_pending"})
		result = device_flow.poll("OpenAI", device_code="DC-abc", client_id="x")
		self.assertIs(result, device_flow.PENDING)

	@patch("jarvis.oauth.device_flow.requests.post")
	def test_poll_slow_down_returns_slow_down_sentinel(self, mock_post):
		mock_post.return_value = _mock_response(400, {"error": "slow_down"})
		result = device_flow.poll("OpenAI", device_code="DC-abc", client_id="x")
		self.assertIs(result, device_flow.SLOW_DOWN)

	@patch("jarvis.oauth.device_flow.requests.post")
	def test_poll_access_denied_raises(self, mock_post):
		mock_post.return_value = _mock_response(400, {"error": "access_denied"})
		with self.assertRaises(device_flow.AccessDenied):
			device_flow.poll("OpenAI", device_code="DC-abc", client_id="x")

	@patch("jarvis.oauth.device_flow.requests.post")
	def test_poll_expired_raises(self, mock_post):
		mock_post.return_value = _mock_response(400, {"error": "expired_token"})
		with self.assertRaises(device_flow.CodeExpired):
			device_flow.poll("OpenAI", device_code="DC-abc", client_id="x")

	@patch("jarvis.oauth.device_flow.requests.post")
	def test_poll_invalid_grant_raises(self, mock_post):
		mock_post.return_value = _mock_response(400, {"error": "invalid_grant"})
		with self.assertRaises(device_flow.InvalidGrant):
			device_flow.poll("OpenAI", device_code="DC-abc", client_id="x")

	@patch("jarvis.oauth.device_flow.requests.get")
	@patch("jarvis.oauth.device_flow.requests.post")
	def test_poll_happy_returns_tokens_plus_email(self, mock_post, mock_get):
		mock_post.return_value = _mock_response(200, {
			"access_token": "AT-1",
			"refresh_token": "RT-1",
			"expires_in": 3600,
		})
		mock_get.return_value = _mock_response(200, {"email": "manager@acme.com"})
		result = device_flow.poll("OpenAI", device_code="DC-abc", client_id="x")
		self.assertEqual(result["access_token"], "AT-1")
		self.assertEqual(result["refresh_token"], "RT-1")
		self.assertEqual(result["account_email"], "manager@acme.com")
		self.assertEqual(result["expires_in"], 3600)


class TestDeviceFlowRefresh(unittest.TestCase):
	@patch("jarvis.oauth.device_flow.requests.post")
	def test_refresh_happy(self, mock_post):
		mock_post.return_value = _mock_response(200, {
			"access_token": "AT-2",
			"expires_in": 3600,
		})
		out = device_flow.refresh("OpenAI", refresh_token="RT-1", client_id="x")
		self.assertEqual(out["access_token"], "AT-2")
		self.assertEqual(out["expires_in"], 3600)
		self.assertIsNone(out["refresh_token"])  # provider didn't rotate

	@patch("jarvis.oauth.device_flow.requests.post")
	def test_refresh_rotates_refresh_token(self, mock_post):
		mock_post.return_value = _mock_response(200, {
			"access_token": "AT-2",
			"refresh_token": "RT-2",
			"expires_in": 3600,
		})
		out = device_flow.refresh("OpenAI", refresh_token="RT-1", client_id="x")
		self.assertEqual(out["refresh_token"], "RT-2")

	@patch("jarvis.oauth.device_flow.requests.post")
	def test_refresh_invalid_grant_raises(self, mock_post):
		mock_post.return_value = _mock_response(400, {"error": "invalid_grant"})
		with self.assertRaises(device_flow.InvalidGrant):
			device_flow.refresh("OpenAI", refresh_token="RT-1", client_id="x")

	@patch("jarvis.oauth.device_flow.requests.post")
	def test_refresh_5xx_raises_provider_error(self, mock_post):
		mock_post.return_value = _mock_response(503)
		with self.assertRaises(device_flow.ProviderUnavailable):
			device_flow.refresh("OpenAI", refresh_token="RT-1", client_id="x")
