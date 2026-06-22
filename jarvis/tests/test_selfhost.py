"""Unit tests for jarvis.selfhost.validate_connection (the self-hosted
openclaw pre-connect checks). HTTP is mocked - no real openclaw needed.

Run: bench --site <site> run-tests --module jarvis.tests.test_selfhost
"""

import unittest
from unittest import mock

from jarvis import selfhost


def _resp(status, json_data=None, text=""):
    m = mock.Mock()
    m.status_code = status
    m.json.return_value = json_data if json_data is not None else {}
    m.text = text
    return m


class TestValidateConnection(unittest.TestCase):
    def _checks(self, result):
        return {c["check"]: c["ok"] for c in result["checks"]}

    def test_bad_url_shape_fails_fast(self):
        r = selfhost.validate_connection("not-a-url", "tok")
        self.assertFalse(r["ok"])
        self.assertFalse(self._checks(r)["url_shape"])

    def test_ws_url_is_normalized_to_http(self):
        # ws:// should be accepted (converted to http for the HTTP checks).
        with mock.patch("jarvis.selfhost.requests") as rq:
            rq.RequestException = Exception
            rq.get.side_effect = [
                _resp(200),  # /healthz
                _resp(200, {"data": [{"id": "openclaw"}]}),  # /v1/models
            ]
            r = selfhost.validate_connection("ws://host:19060", "tok")
        self.assertTrue(r["ok"])
        self.assertTrue(self._checks(r)["url_shape"])

    def test_unreachable_fails(self):
        with mock.patch("jarvis.selfhost.requests") as rq:
            rq.RequestException = Exception
            rq.get.side_effect = Exception("connection refused")
            r = selfhost.validate_connection("http://host:19099", "tok")
        self.assertFalse(r["ok"])
        self.assertFalse(self._checks(r)["reachable"])

    def test_bad_token_fails_auth(self):
        with mock.patch("jarvis.selfhost.requests") as rq:
            rq.RequestException = Exception
            rq.get.side_effect = [_resp(200), _resp(401)]  # healthz ok, models 401
            r = selfhost.validate_connection("http://host:19060", "wrong")
        self.assertFalse(r["ok"])
        checks = self._checks(r)
        self.assertTrue(checks["reachable"])
        self.assertFalse(checks["auth"])

    def test_no_models_fails_llm_ready(self):
        with mock.patch("jarvis.selfhost.requests") as rq:
            rq.RequestException = Exception
            rq.get.side_effect = [_resp(200), _resp(200, {"data": []})]
            r = selfhost.validate_connection("http://host:19060", "tok")
        self.assertFalse(r["ok"])
        checks = self._checks(r)
        self.assertTrue(checks["auth"])
        self.assertFalse(checks["llm_ready"])

    def test_happy_path_all_green(self):
        with mock.patch("jarvis.selfhost.requests") as rq:
            rq.RequestException = Exception
            rq.get.side_effect = [
                _resp(200),
                _resp(200, {"data": [{"id": "openclaw"}, {"id": "openclaw/main"}]}),
            ]
            r = selfhost.validate_connection("http://host:19060", "tok")
        self.assertTrue(r["ok"])
        self.assertEqual(self._checks(r),
                         {"url_shape": True, "reachable": True, "auth": True, "llm_ready": True})
        self.assertEqual(r["models"], ["openclaw", "openclaw/main"])

    def test_deep_chat_ping(self):
        with mock.patch("jarvis.selfhost.requests") as rq:
            rq.RequestException = Exception
            rq.get.side_effect = [_resp(200), _resp(200, {"data": [{"id": "openclaw"}]})]
            rq.post.return_value = _resp(200, {
                "choices": [{"message": {"content": "pong"}}]})
            r = selfhost.validate_connection("http://host:19060", "tok", deep=True)
        self.assertTrue(r["ok"])
        self.assertTrue(self._checks(r)["deep_chat"])


if __name__ == "__main__":
    unittest.main()
