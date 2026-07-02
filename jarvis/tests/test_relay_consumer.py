"""Unit tests for OpenclawSession.relay_turn_events + set_session_model.

Mirror of test_openclaw_native_rpcs.py's harness: bypass __init__ via
OpenclawSession.__new__ and stub _recv (fed a scripted frame list; an
Exception instance in the list is raised) / _request.

relay_turn_events is the consumer half of the openclaw-native turn model:
token/tool streaming comes from broadcast "agent" event frames retagged
with the chat.send clientRunId == run_id; completion comes ONLY from the
run-scoped "chat" event (state final|aborted|error). agent lifecycle
frames are dropped.
"""
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.openclaw_client import OpenclawSession
from jarvis.exceptions import OpenclawUnreachableError


def _agent_frame(run_id, stream, data):
	return {"type": "event", "event": "agent", "payload": {
		"runId": run_id, "stream": stream, "data": data,
	}}


def _chat_frame(run_id, session_key, state, **extra):
	payload = {"runId": run_id, "sessionKey": session_key, "state": state}
	payload.update(extra)
	return {"type": "event", "event": "chat", "payload": payload}


class TestRelayTurnEvents(FrappeTestCase):
	def _sess(self, frames):
		sess = OpenclawSession.__new__(OpenclawSession)  # bypass __init__/WS
		queue = list(frames)

		def fake_recv(_timeout):
			frame = queue.pop(0)
			if isinstance(frame, Exception):
				raise frame
			return frame

		sess._recv = fake_recv
		return sess

	def test_assistant_and_tool_frames_then_final_joined_text(self):
		sess = self._sess([
			_agent_frame("r1", "assistant", {"text": "Hi there", "delta": "there"}),
			_agent_frame("r1", "item", {
				"kind": "tool", "phase": "start", "name": "read_file",
				"toolCallId": "tc1",
			}),
			_chat_frame("r1", "sk", "final", message={
				"content": [{"type": "text", "text": "Hi there"}],
			}),
		])
		out = list(sess.relay_turn_events("sk", "r1"))
		self.assertEqual(out[0], {"kind": "assistant", "text": "Hi there", "delta": "there"})
		self.assertEqual(out[1], {
			"kind": "tool", "phase": "start", "tool_name": "read_file", "tool_call_id": "tc1",
		})
		self.assertEqual(out[2], {"kind": "relay:final", "text": "Hi there"})
		self.assertEqual(len(out), 3)

	def test_discards_frames_for_other_run_or_session_and_non_event_frames(self):
		sess = self._sess([
			_agent_frame("other-run", "assistant", {"text": "nope", "delta": "nope"}),
			{"type": "res", "id": "x", "ok": True},  # non-event frame
			None,  # soft-timeout / non-JSON noise
			_chat_frame("r1", "other-session", "final"),  # wrong sessionKey
			_chat_frame("other-run", "sk", "final"),  # wrong runId
			_agent_frame("r1", "assistant", {"text": "ok", "delta": "ok"}),
			_chat_frame("r1", "sk", "final"),
		])
		out = list(sess.relay_turn_events("sk", "r1"))
		self.assertEqual(out, [
			{"kind": "assistant", "text": "ok", "delta": "ok"},
			{"kind": "relay:final", "text": None},
		])

	def test_agent_lifecycle_frames_never_yielded(self):
		sess = self._sess([
			_agent_frame("r1", "lifecycle", {"phase": "start"}),
			_agent_frame("r1", "lifecycle", {"phase": "end"}),
			_chat_frame("r1", "sk", "final"),
		])
		out = list(sess.relay_turn_events("sk", "r1"))
		self.assertEqual(out, [{"kind": "relay:final", "text": None}])

	def test_chat_delta_state_ignored(self):
		sess = self._sess([
			_chat_frame("r1", "sk", "delta", message={"content": "partial"}),
			_chat_frame("r1", "sk", "delta", message={"content": "partial partial"}),
			_chat_frame("r1", "sk", "final", message={"content": "done"}),
		])
		out = list(sess.relay_turn_events("sk", "r1"))
		self.assertEqual(out, [{"kind": "relay:final", "text": "done"}])

	def test_final_with_no_message_yields_text_none(self):
		sess = self._sess([_chat_frame("r1", "sk", "final")])
		out = list(sess.relay_turn_events("sk", "r1"))
		self.assertEqual(out, [{"kind": "relay:final", "text": None}])

	def test_final_with_string_content_yields_text(self):
		sess = self._sess([_chat_frame("r1", "sk", "final", message={"content": "plain text"})])
		out = list(sess.relay_turn_events("sk", "r1"))
		self.assertEqual(out, [{"kind": "relay:final", "text": "plain text"}])

	def test_chat_error_state_yields_relay_error_with_message(self):
		sess = self._sess([
			_chat_frame("r1", "sk", "error", errorMessage="provider timed out"),
		])
		out = list(sess.relay_turn_events("sk", "r1"))
		self.assertEqual(out, [
			{"kind": "relay:error", "state": "error", "error": "provider timed out"},
		])

	def test_chat_aborted_state_falls_back_to_state_string(self):
		sess = self._sess([_chat_frame("r1", "sk", "aborted")])
		out = list(sess.relay_turn_events("sk", "r1"))
		self.assertEqual(out, [
			{"kind": "relay:error", "state": "aborted", "error": "aborted"},
		])

	def test_transport_drop_yields_interrupted_transport_and_does_not_raise(self):
		sess = self._sess([OpenclawUnreachableError("ws closed mid-stream")])
		out = list(sess.relay_turn_events("sk", "r1"))
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["kind"], "relay:interrupted")
		self.assertEqual(out[0]["reason"], "transport")
		self.assertIn("ws closed mid-stream", out[0]["detail"])

	def test_deadline_yields_interrupted_deadline_on_stalling_recv(self):
		sess = OpenclawSession.__new__(OpenclawSession)

		def stalling_recv(_timeout):
			import time
			time.sleep(0.05)
			return None

		sess._recv = stalling_recv
		out = list(sess.relay_turn_events("sk", "r1", soft_deadline_s=0.01))
		self.assertEqual(out, [{"kind": "relay:interrupted", "reason": "deadline"}])


class TestSetSessionModel(FrappeTestCase):
	def test_sends_exact_sessions_patch_params(self):
		sess = OpenclawSession.__new__(OpenclawSession)
		captured = {}

		def fake_request(method, params, *, timeout_s):
			captured["method"] = method
			captured["params"] = params
			return {"ok": True, "payload": {}}

		sess._request = fake_request
		sess.set_session_model("sk", "openai/gpt-4o")
		self.assertEqual(captured["method"], "sessions.patch")
		self.assertEqual(captured["params"], {"key": "sk", "model": "openai/gpt-4o"})
