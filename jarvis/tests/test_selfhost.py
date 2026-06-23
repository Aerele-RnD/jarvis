"""Unit tests for jarvis.selfhost.validate_connection (the self-hosted
openclaw pre-connect checks). HTTP is mocked - no real openclaw needed.

Run: bench --site <site> run-tests --module jarvis.tests.test_selfhost
"""

import unittest
from unittest import mock

import frappe

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


class TestActiveTurnMarker(unittest.TestCase):
    """Concurrency safety of the self-host tool-card attribution marker.

    Uses the real frappe cache (Redis). Two turns for one tool user must never
    let a tool callback be attributed to the wrong conversation.
    """

    TOOL_USER = "selfhost-marker-test@example.com"

    def setUp(self):
        selfhost.clear_active_turn(self.TOOL_USER)

    def tearDown(self):
        selfhost.clear_active_turn(self.TOOL_USER)

    def test_single_turn_attributes(self):
        selfhost.set_active_turn(self.TOOL_USER, conversation="C1", owner="u1@x", run_id="r1")
        turn = selfhost.get_active_turn(self.TOOL_USER)
        self.assertIsNotNone(turn)
        self.assertEqual(turn["conversation"], "C1")
        self.assertEqual(turn["run_id"], "r1")

    def test_concurrent_turns_are_ambiguous_and_return_none(self):
        # Two overlapping turns -> no unambiguous turn -> a tool callback is
        # NOT mis-attributed (fail safe, no cross-conversation leak).
        selfhost.set_active_turn(self.TOOL_USER, conversation="C1", owner="u1@x", run_id="r1")
        selfhost.set_active_turn(self.TOOL_USER, conversation="C2", owner="u2@x", run_id="r2")
        self.assertIsNone(selfhost.get_active_turn(self.TOOL_USER))

    def test_clearing_one_leaves_the_surviving_turn_not_a_stale_slot(self):
        selfhost.set_active_turn(self.TOOL_USER, conversation="C1", owner="u1@x", run_id="r1")
        selfhost.set_active_turn(self.TOOL_USER, conversation="C2", owner="u2@x", run_id="r2")
        # r2 (last writer) finishes first; the survivor r1 must be returned -
        # a single last-writer-wins slot would have wrongly returned C2/None.
        selfhost.clear_active_turn(self.TOOL_USER, "r2")
        turn = selfhost.get_active_turn(self.TOOL_USER)
        self.assertIsNotNone(turn)
        self.assertEqual(turn["conversation"], "C1")

    def test_clear_by_run_id_does_not_wipe_concurrent_turn(self):
        selfhost.set_active_turn(self.TOOL_USER, conversation="C1", owner="u1@x", run_id="r1")
        selfhost.set_active_turn(self.TOOL_USER, conversation="C2", owner="u2@x", run_id="r2")
        selfhost.clear_active_turn(self.TOOL_USER, "r1")
        turn = selfhost.get_active_turn(self.TOOL_USER)
        self.assertIsNotNone(turn)
        self.assertEqual(turn["conversation"], "C2")

    def test_stale_run_id_pruned_when_record_expired(self):
        # Simulate a worker killed before clear ran: run id is still in the set
        # but its per-run record (TTL) is gone. It must be ignored + pruned.
        selfhost.set_active_turn(self.TOOL_USER, conversation="C1", owner="u1@x", run_id="r1")
        frappe.cache().delete_value(selfhost._turn_key("r1"))
        self.assertIsNone(selfhost.get_active_turn(self.TOOL_USER))
        # A fresh turn is then unambiguous (the stale id was pruned).
        selfhost.set_active_turn(self.TOOL_USER, conversation="C2", owner="u2@x", run_id="r2")
        turn = selfhost.get_active_turn(self.TOOL_USER)
        self.assertIsNotNone(turn)
        self.assertEqual(turn["conversation"], "C2")

    def test_empty_tool_user_is_noop(self):
        selfhost.set_active_turn("", conversation="C1", owner="u1@x", run_id="r1")
        self.assertIsNone(selfhost.get_active_turn(""))


class _FakeSettings:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def db_set(self, key, val):
        setattr(self, key, val)


class TestSaveSelfHostedToolUser(unittest.TestCase):
    """save_self_hosted tool-user defaulting + the unset warning (#2).

    Fully mocked - no Jarvis Settings writes - so it never flips the live
    bench into Self-Hosted mode.
    """

    def _save(self, *, session_user, existing_tool_user="", tool_user="", enabled=True):
        fake = _FakeSettings(selfhost_tool_user=existing_tool_user)
        validation = {"ok": True, "checks": [], "openclaw_version": None, "models": ["openclaw"]}
        with mock.patch("jarvis.selfhost.validate_connection", return_value=validation), \
                mock.patch("jarvis.selfhost.frappe") as fr:
            fr.get_single.return_value = fake
            fr.session.user = session_user
            # User.enabled lookup: 1 = exists+enabled, None = missing/disabled.
            fr.db.get_value.return_value = 1 if enabled else None
            out = selfhost.save_self_hosted("http://host:19060", "tok", tool_user=tool_user)
        return out, fake

    def test_defaults_tool_user_to_configurer(self):
        out, fake = self._save(session_user="alice@example.com")
        self.assertTrue(out["ok"])
        self.assertEqual(fake.selfhost_tool_user, "alice@example.com")
        self.assertNotIn("warning", out)

    def test_administrator_configurer_leaves_unset_and_warns(self):
        out, fake = self._save(session_user="Administrator")
        self.assertTrue(out["ok"])
        self.assertEqual((fake.selfhost_tool_user or ""), "")
        self.assertIn("warning", out)
        self.assertIn("Self-Host Tool User", out["warning"])

    def test_explicit_tool_user_used(self):
        out, fake = self._save(session_user="Administrator", tool_user="bob@example.com")
        self.assertTrue(out["ok"])
        self.assertEqual(fake.selfhost_tool_user, "bob@example.com")
        self.assertNotIn("warning", out)

    def test_explicit_admin_tool_user_rejected(self):
        out, _ = self._save(session_user="alice@example.com", tool_user="Administrator")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "invalid_tool_user")

    def test_explicit_unknown_or_disabled_user_rejected(self):
        out, _ = self._save(session_user="alice@example.com",
                            tool_user="ghost@example.com", enabled=False)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "invalid_tool_user")

    def test_existing_tool_user_preserved(self):
        out, fake = self._save(session_user="Administrator",
                              existing_tool_user="carol@example.com")
        self.assertTrue(out["ok"])
        self.assertEqual(fake.selfhost_tool_user, "carol@example.com")
        self.assertNotIn("warning", out)


if __name__ == "__main__":
    unittest.main()
