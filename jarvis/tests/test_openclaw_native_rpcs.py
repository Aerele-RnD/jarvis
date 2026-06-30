"""Unit tests for the openclaw-native RPC methods on OpenclawSession.

These mirror openclaw's own UI gateway model (chat.send + chat.history +
sessions.list/get), so the bench can drive turns and reconcile from the
durable transcript instead of holding the agent RPC's request stream.

Each method is request/response, so we bypass __init__ and stub _request.
"""
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.openclaw_client import OpenclawSession


class TestOpenclawNativeRpcs(FrappeTestCase):
	def _sess(self, response):
		sess = OpenclawSession.__new__(OpenclawSession)  # bypass __init__/WS
		captured = {"response": response}

		def fake_request(method, params, *, timeout_s):
			captured["method"] = method
			captured["params"] = params
			return captured["response"]

		sess._request = fake_request
		return sess, captured

	def test_chat_send_required_params_and_returns_payload(self):
		sess, cap = self._sess(
			{"ok": True, "payload": {"runId": "r1", "status": "in_flight"}}
		)
		out = sess.chat_send("sk", "hi", "idem1", thinking="low")
		self.assertEqual(cap["method"], "chat.send")
		self.assertEqual(cap["params"]["sessionKey"], "sk")
		self.assertEqual(cap["params"]["message"], "hi")
		self.assertEqual(cap["params"]["idempotencyKey"], "idem1")
		self.assertEqual(cap["params"]["deliver"], False)
		self.assertEqual(cap["params"]["thinking"], "low")
		self.assertEqual(out, {"runId": "r1", "status": "in_flight"})

	def test_chat_send_omits_optional_when_unset(self):
		sess, cap = self._sess({"ok": True, "payload": {"runId": "r2"}})
		sess.chat_send("sk", "hi", "idem2")
		self.assertNotIn("thinking", cap["params"])
		self.assertNotIn("attachments", cap["params"])

	def test_get_history_params_and_payload(self):
		sess, cap = self._sess(
			{"ok": True, "payload": {"sessionId": "s1",
			 "messages": [{"role": "assistant"}], "thinkingLevel": "medium"}}
		)
		out = sess.get_history("sk", limit=50)
		self.assertEqual(cap["method"], "chat.history")
		self.assertEqual(cap["params"], {"sessionKey": "sk", "limit": 50, "maxChars": 4000})
		self.assertEqual(out["messages"], [{"role": "assistant"}])
		self.assertEqual(out["thinkingLevel"], "medium")

	def test_get_session_messages_returns_messages_list(self):
		sess, cap = self._sess(
			{"ok": True, "payload": {"messages": [{"role": "assistant", "content": "x"}]}}
		)
		out = sess.get_session_messages("sk")
		self.assertEqual(cap["method"], "sessions.get")
		self.assertEqual(cap["params"]["key"], "sk")
		self.assertEqual(out, [{"role": "assistant", "content": "x"}])

	def test_get_session_messages_empty(self):
		sess, _ = self._sess({"ok": True, "payload": {}})
		self.assertEqual(sess.get_session_messages("sk"), [])

	def test_is_run_active_matches_session_key(self):
		sess, cap = self._sess(
			{"ok": True, "payload": {"sessions": [
				{"key": "other", "hasActiveRun": True},
				{"key": "sk", "hasActiveRun": True},
			]}}
		)
		self.assertTrue(sess.is_run_active("sk"))

	def test_is_run_active_false_when_done_or_absent(self):
		sess, cap = self._sess(
			{"ok": True, "payload": {"sessions": [{"key": "sk", "hasActiveRun": False}]}}
		)
		self.assertFalse(sess.is_run_active("sk"))
		cap["response"] = {"ok": True, "payload": {"sessions": []}}
		self.assertFalse(sess.is_run_active("sk"))
