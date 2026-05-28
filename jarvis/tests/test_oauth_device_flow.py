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
