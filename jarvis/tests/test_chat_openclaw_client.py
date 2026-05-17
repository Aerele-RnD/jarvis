"""Tests for the Python openclaw WebSocket client.

Translates demo.py's _NODE_SCRIPT to native Python. Connects, performs the
operator handshake, creates a session, and streams agent-turn events as
parsed dicts. Tests use a mocked websocket-client connection.
"""

import json
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from jarvis.chat.openclaw_client import OpenclawSession
from jarvis.exceptions import OpenclawUnreachableError


def _make_mock_ws(frames: list[dict]) -> MagicMock:
	"""Build a mock WS that returns the given frames as JSON strings on recv()."""
	mock_ws = MagicMock()
	queue = [json.dumps(f) for f in frames]
	mock_ws.recv.side_effect = queue
	return mock_ws


def _last_sent(mock_ws: MagicMock, idx: int = -1) -> dict:
	"""Parse the JSON body of the idx-th send() call on the mocked socket."""
	return json.loads(mock_ws.send.call_args_list[idx].args[0])


class TestConnect(FrappeTestCase):
	def test_connect_sends_handshake_with_gateway_client_id(self):
		recv_frames = [
			# We need the recv to match by id, so we read the id from the send
			# and craft the ack. The simpler approach: any-id ack — the impl
			# loops until matching id, so we keep the queue small.
		]
		# Use a side-effect that constructs an ack matching whatever id was sent
		mock_ws = MagicMock()

		def recv_responder():
			last_send = json.loads(mock_ws.send.call_args.args[0])
			return json.dumps({"type": "res", "id": last_send["id"], "ok": True, "payload": {}})

		mock_ws.recv.side_effect = recv_responder
		with patch("jarvis.chat.openclaw_client.create_connection", return_value=mock_ws):
			OpenclawSession.connect("ws://127.0.0.1:18789", "tok-123")
		sent = _last_sent(mock_ws, 0)
		self.assertEqual(sent["method"], "connect")
		self.assertEqual(sent["params"]["client"]["id"], "gateway-client")
		self.assertEqual(sent["params"]["client"]["mode"], "backend")
		self.assertEqual(sent["params"]["scopes"], ["operator.admin"])
		self.assertEqual(sent["params"]["auth"]["token"], "tok-123")

	def test_connect_failure_translates_to_unreachable_error(self):
		with patch(
			"jarvis.chat.openclaw_client.create_connection",
			side_effect=OSError("connection refused"),
		):
			with self.assertRaises(OpenclawUnreachableError):
				OpenclawSession.connect("ws://127.0.0.1:18789", "tok-123")


class TestCreateSession(FrappeTestCase):
	def _make_responder_ws(self, payloads_by_method: dict):
		"""Build a mock that replies to each send() with the corresponding payload.

		payloads_by_method maps method name -> {ok: bool, payload: dict, error: dict}.
		"""
		mock_ws = MagicMock()

		def recv_responder():
			last_send = json.loads(mock_ws.send.call_args.args[0])
			method = last_send["method"]
			cfg = payloads_by_method[method]
			frame = {"type": "res", "id": last_send["id"], "ok": cfg.get("ok", True)}
			if cfg.get("ok", True):
				frame["payload"] = cfg.get("payload", {})
			else:
				frame["error"] = cfg.get("error", {})
			return json.dumps(frame)

		mock_ws.recv.side_effect = recv_responder
		return mock_ws

	def test_create_session_returns_session_key(self):
		mock_ws = self._make_responder_ws({
			"connect": {"ok": True, "payload": {}},
			"sessions.create": {"ok": True, "payload": {"key": "agent:main:abc"}},
		})
		with patch("jarvis.chat.openclaw_client.create_connection", return_value=mock_ws):
			sess = OpenclawSession.connect("ws://127.0.0.1:18789", "tok-123")
			key = sess.create_session(label="lbl")
		self.assertEqual(key, "agent:main:abc")

	def test_create_session_failure_raises(self):
		mock_ws = self._make_responder_ws({
			"connect": {"ok": True, "payload": {}},
			"sessions.create": {"ok": False, "error": {"code": "X", "message": "y"}},
		})
		with patch("jarvis.chat.openclaw_client.create_connection", return_value=mock_ws):
			sess = OpenclawSession.connect("ws://127.0.0.1:18789", "tok-123")
			with self.assertRaises(OpenclawUnreachableError):
				sess.create_session()


class TestStreamAgentTurn(FrappeTestCase):
	def _setup_ws_with_events(self, agent_run_id: str, events: list[dict]):
		"""Build a mock that handles connect + agent + then streams events."""
		mock_ws = MagicMock()
		state = {"streaming": False, "event_iter": iter(events)}

		def recv_responder():
			if state["streaming"]:
				try:
					return json.dumps(next(state["event_iter"]))
				except StopIteration:
					return ""
			last_send = json.loads(mock_ws.send.call_args.args[0])
			method = last_send["method"]
			if method == "connect":
				return json.dumps({"type": "res", "id": last_send["id"], "ok": True, "payload": {}})
			if method == "agent":
				state["streaming"] = True
				return json.dumps({
					"type": "res", "id": last_send["id"], "ok": True,
					"payload": {"runId": agent_run_id},
				})
			raise AssertionError(f"unexpected method: {method}")

		mock_ws.recv.side_effect = recv_responder
		return mock_ws

	def test_yields_lifecycle_tool_and_assistant_events_then_ends(self):
		events = [
			{"type": "event", "payload": {"runId": "r1", "stream": "lifecycle",
				"data": {"phase": "start"}}},
			{"type": "event", "payload": {"runId": "r1", "stream": "item",
				"data": {"kind": "tool", "phase": "start", "name": "jarvis__get_list",
				"toolCallId": "tc-1"}}},
			{"type": "event", "payload": {"runId": "r1", "stream": "item",
				"data": {"kind": "tool", "phase": "end", "name": "jarvis__get_list",
				"toolCallId": "tc-1", "status": "completed"}}},
			{"type": "event", "payload": {"runId": "r1", "stream": "assistant",
				"data": {"text": "Hello", "delta": "Hello"}}},
			{"type": "event", "payload": {"runId": "r1", "stream": "lifecycle",
				"data": {"phase": "end"}}},
		]
		mock_ws = self._setup_ws_with_events("r1", events)
		with patch("jarvis.chat.openclaw_client.create_connection", return_value=mock_ws):
			sess = OpenclawSession.connect("ws://127.0.0.1:18789", "tok-123")
			parsed = list(sess.stream_agent_turn("agent:main:abc", "hi", "idk-1"))
		kinds = [e["kind"] for e in parsed]
		self.assertEqual(kinds, ["lifecycle", "tool", "tool", "assistant", "lifecycle"])
		self.assertEqual(parsed[-1]["phase"], "end")

	def test_filters_events_from_other_runs(self):
		events = [
			# Event for a DIFFERENT runId — must be filtered out
			{"type": "event", "payload": {"runId": "OTHER", "stream": "assistant",
				"data": {"text": "stale", "delta": "stale"}}},
			{"type": "event", "payload": {"runId": "r1", "stream": "lifecycle",
				"data": {"phase": "end"}}},
		]
		mock_ws = self._setup_ws_with_events("r1", events)
		with patch("jarvis.chat.openclaw_client.create_connection", return_value=mock_ws):
			sess = OpenclawSession.connect("ws://127.0.0.1:18789", "tok-123")
			parsed = list(sess.stream_agent_turn("agent:main:abc", "hi", "idk-1"))
		# Only the lifecycle:end (our run) should make it through
		self.assertEqual(len(parsed), 1)
		self.assertEqual(parsed[0]["kind"], "lifecycle")
		self.assertEqual(parsed[0]["phase"], "end")
