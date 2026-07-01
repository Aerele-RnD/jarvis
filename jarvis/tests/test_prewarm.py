# app/jarvis/tests/test_prewarm.py
from unittest.mock import MagicMock, patch

import frappe
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


class TestWarmPrefix(FrappeTestCase):
    def _settings_stub(self):
        s = MagicMock()
        s.agent_url = "https://gw.example"
        s.get_password.return_value = "tok"
        return s

    def test_warm_prefix_throwaway_session_no_rows_best_effort(self):
        from jarvis.chat import prewarm

        frappe.cache().delete_value(prewarm._warm_cooldown_key())
        fake_sess = MagicMock()
        fake_sess.create_session.return_value = "sk_throwaway"
        before = frappe.db.count("Jarvis Chat Message")

        with patch("jarvis.chat.prewarm.OpenclawSession") as OC, \
             patch("jarvis.chat.prewarm.selfhost.is_self_hosted", return_value=False), \
             patch("jarvis.chat.prewarm.frappe.get_single", return_value=self._settings_stub()):
            OC.connect.return_value = fake_sess
            fired = prewarm.warm_prefix()

        self.assertTrue(fired)
        fake_sess.create_session.assert_called_once()
        msg = fake_sess.fire_agent.call_args.args[1]
        self.assertIn("/think off", msg)
        fake_sess.close.assert_called_once()
        self.assertEqual(frappe.db.count("Jarvis Chat Message"), before)

    def test_warm_prefix_debounced_second_call_is_noop(self):
        from jarvis.chat import prewarm

        frappe.cache().delete_value(prewarm._warm_cooldown_key())
        with patch("jarvis.chat.prewarm.OpenclawSession") as OC, \
             patch("jarvis.chat.prewarm.selfhost.is_self_hosted", return_value=False), \
             patch("jarvis.chat.prewarm.frappe.get_single", return_value=self._settings_stub()):
            OC.connect.return_value = MagicMock(create_session=MagicMock(return_value="sk"))
            self.assertTrue(prewarm.warm_prefix())
            self.assertFalse(prewarm.warm_prefix())  # within cooldown

    def test_warm_prefix_swallows_errors(self):
        from jarvis.chat import prewarm

        frappe.cache().delete_value(prewarm._warm_cooldown_key())
        with patch("jarvis.chat.prewarm.selfhost.is_self_hosted", return_value=False), \
             patch("jarvis.chat.prewarm.frappe.get_single", side_effect=RuntimeError("boom")):
            self.assertFalse(prewarm.warm_prefix())  # no raise


class TestKeepWarm(FrappeTestCase):
    def test_keep_warm_warms_when_recent_activity(self):
        from jarvis.chat import prewarm

        with patch("jarvis.chat.prewarm.selfhost.is_self_hosted", return_value=False), \
             patch("jarvis.chat.prewarm.frappe.db.exists", return_value="MSG-1"), \
             patch("jarvis.chat.prewarm.warm_prefix") as wp:
            prewarm.keep_warm_if_active()
        wp.assert_called_once()

    def test_keep_warm_noop_when_idle(self):
        from jarvis.chat import prewarm

        with patch("jarvis.chat.prewarm.selfhost.is_self_hosted", return_value=False), \
             patch("jarvis.chat.prewarm.frappe.db.exists", return_value=None), \
             patch("jarvis.chat.prewarm.warm_prefix") as wp:
            prewarm.keep_warm_if_active()
        wp.assert_not_called()
