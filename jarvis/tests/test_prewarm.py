# app/jarvis/tests/test_prewarm.py
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.openclaw_client import OpenclawSession


class TestFireAgent(FrappeTestCase):
    def test_fire_agent_sends_deliver_false_and_returns_runid(self):
        sess = OpenclawSession.__new__(OpenclawSession)  # bypass __init__/WS
        captured = {}

        def fake_request(method, params, *, timeout_s):
            captured["method"], captured["params"] = method, params
            return {"ok": True, "payload": {"runId": "run123"}}

        sess._request = fake_request
        rid = sess.fire_agent("sk_1", "/think off warmup", "idem1")

        self.assertEqual(rid, "run123")
        self.assertEqual(captured["method"], "agent")
        self.assertEqual(captured["params"]["deliver"], False)
        self.assertEqual(captured["params"]["sessionKey"], "sk_1")
        self.assertEqual(captured["params"]["message"], "/think off warmup")
