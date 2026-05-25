"""Tests for the direct-WS chat client (jarvis.chat.openclaw_client).

The transport is a real websocket-client connection to openclaw's gateway.
Tests fake it out at the create_connection level: a scripted WS whose recv()
returns a sequence of JSON frames and whose send() captures the client's
outbound frames for assertion.

What's verified here:
- Connect handshake: receives connect.challenge, sends a v3-signed connect,
  succeeds on a positive hello-ok response.
- create_session round-trip.
- stream_agent_turn yields parsed events between agent ack and lifecycle end.
- Close is forgiving (no raise on already-closed sockets).

Pairing itself is mocked here — see test_chat_device.py for the device.py
half of the integration (keypair + admin call).
"""

from __future__ import annotations

import base64
import json
from unittest.mock import patch

import websocket
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.device import ChatDeviceCredentials
from jarvis.chat.openclaw_client import OpenclawSession
from jarvis.exceptions import OpenclawUnreachableError


# --- helpers --------------------------------------------------------------

def _b64u(raw: bytes) -> str:
	return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _make_creds() -> ChatDeviceCredentials:
	import hashlib
	priv = Ed25519PrivateKey.generate()
	pub_raw = priv.public_key().public_bytes(
		encoding=serialization.Encoding.Raw,
		format=serialization.PublicFormat.Raw,
	)
	device_id = hashlib.sha256(pub_raw).hexdigest()
	return ChatDeviceCredentials(
		device_id=device_id, public_key=_b64u(pub_raw),
		private_key=priv, device_token="tok-test",
	)


class _ScriptedWS:
	"""Stand-in for a websocket.WebSocket.

	frames_to_recv is a list of JSON-string frames OR callables that return
	a JSON-string frame at recv time. Callables let a frame respond to the
	id the client sends (which we can't know ahead of time)."""

	def __init__(self, frames_to_recv: list):
		self._frames = list(frames_to_recv)
		self.sent: list[dict] = []
		self.closed = False

	def settimeout(self, _seconds): pass

	def recv(self):
		if not self._frames:
			raise websocket.WebSocketTimeoutException("no more frames")
		item = self._frames.pop(0)
		return item() if callable(item) else item

	def send(self, raw):
		self.sent.append(json.loads(raw))

	def close(self): self.closed = True


def _frame(d: dict) -> str:
	return json.dumps(d)


def _challenge(nonce: str = "nonce-test") -> str:
	return _frame({"type": "event", "event": "connect.challenge",
				   "payload": {"nonce": nonce}})


def _build_session(creds=None) -> tuple[OpenclawSession, _ScriptedWS]:
	"""Spin up a fully-handshaken OpenclawSession with no real WS. Returns the
	session and the underlying scripted WS so tests can extend its frames
	and inspect sent frames."""
	creds = creds or _make_creds()

	def _ok():
		req_id = scripted.sent[-1]["id"]
		return _frame({"type": "res", "id": req_id, "ok": True, "payload": {
			"auth": {"scopes": ["operator.write", "operator.admin"]},
		}})

	scripted = _ScriptedWS([_challenge(), _ok])
	with patch("jarvis.chat.openclaw_client.websocket.create_connection", return_value=scripted), \
		 patch("jarvis.chat.openclaw_client.ensure_paired", return_value=creds):
		sess = OpenclawSession.connect("ws://test", "ignored-token")
	scripted.sent.clear()
	return sess, scripted


# --- TestConnect ----------------------------------------------------------

class TestConnect(FrappeTestCase):
	def test_handshake_sends_v3_signed_connect(self):
		creds = _make_creds()

		def _ok():
			req_id = scripted.sent[-1]["id"]
			return _frame({"type": "res", "id": req_id, "ok": True, "payload": {}})

		scripted = _ScriptedWS([_challenge("nonce-xyz"), _ok])
		with patch("jarvis.chat.openclaw_client.websocket.create_connection", return_value=scripted), \
			 patch("jarvis.chat.openclaw_client.ensure_paired", return_value=creds):
			sess = OpenclawSession.connect("ws://t", "x")

		self.assertEqual(len(scripted.sent), 1)
		req = scripted.sent[0]
		self.assertEqual(req["type"], "req")
		self.assertEqual(req["method"], "connect")
		params = req["params"]
		self.assertEqual(params["role"], "operator")
		self.assertIn("operator.write", params["scopes"])
		self.assertEqual(params["auth"]["deviceToken"], creds.device_token)
		self.assertEqual(params["device"]["id"], creds.device_id)
		self.assertEqual(params["device"]["nonce"], "nonce-xyz")
		# Signature must be a non-empty base64url string (no padding).
		self.assertTrue(params["device"]["signature"])
		self.assertNotIn("=", params["device"]["signature"])
		import time
		self.assertGreater(params["device"]["signedAt"], int(time.time() * 1000) - 60_000)
		sess.close()

	def test_connect_rejection_raises_unreachable(self):
		creds = _make_creds()

		def _nack():
			req_id = scripted.sent[-1]["id"]
			return _frame({"type": "res", "id": req_id, "ok": False,
						   "error": {"code": "UNAUTHORIZED", "message": "bad token"}})

		scripted = _ScriptedWS([_challenge(), _nack])
		with patch("jarvis.chat.openclaw_client.websocket.create_connection", return_value=scripted), \
			 patch("jarvis.chat.openclaw_client.ensure_paired", return_value=creds):
			with self.assertRaises(OpenclawUnreachableError) as cm:
				OpenclawSession.connect("ws://t", "x")
		self.assertIn("UNAUTHORIZED", str(cm.exception))
		self.assertTrue(scripted.closed)

	def test_missing_challenge_times_out(self):
		creds = _make_creds()
		with patch("jarvis.chat.openclaw_client.CONNECT_TIMEOUT_SECONDS", 0.05), \
			 patch("jarvis.chat.openclaw_client.websocket.create_connection",
				   return_value=_ScriptedWS([])), \
			 patch("jarvis.chat.openclaw_client.ensure_paired", return_value=creds):
			with self.assertRaises(OpenclawUnreachableError):
				OpenclawSession.connect("ws://t", "x")

	def test_empty_gateway_url_raises(self):
		with patch("jarvis.chat.openclaw_client.ensure_paired", return_value=_make_creds()):
			with self.assertRaises(OpenclawUnreachableError):
				OpenclawSession.connect("", "x")


# --- TestCreateSession ----------------------------------------------------

class TestCreateSession(FrappeTestCase):
	def test_returns_key_on_ok(self):
		sess, ws = _build_session()

		def _resp():
			req_id = ws.sent[-1]["id"]
			return _frame({"type": "res", "id": req_id, "ok": True,
						   "payload": {"key": "session-abc"}})

		ws._frames.append(_resp)
		key = sess.create_session()
		self.assertEqual(key, "session-abc")

	def test_rejection_raises(self):
		sess, ws = _build_session()

		def _resp():
			req_id = ws.sent[-1]["id"]
			return _frame({"type": "res", "id": req_id, "ok": False,
						   "error": {"code": "BAD", "message": "no"}})

		ws._frames.append(_resp)
		with self.assertRaises(OpenclawUnreachableError):
			sess.create_session()


# --- TestStreamAgentTurn --------------------------------------------------

class TestStreamAgentTurn(FrappeTestCase):
	def test_completes_on_lifecycle_end(self):
		sess, ws = _build_session()

		def _ack():
			req_id = ws.sent[-1]["id"]
			return _frame({"type": "res", "id": req_id, "ok": True,
						   "payload": {"runId": "run-1"}})

		ws._frames.append(_ack)
		ws._frames.append(_frame({"type": "event", "event": "agent.event",
								  "payload": {"runId": "run-1", "stream": "lifecycle",
											  "data": {"phase": "end"}}}))
		# Streams to completion (no items required to be yielded for the
		# completion-path test — parse_event filters its own shapes).
		list(sess.stream_agent_turn("session-x", "hi", "idem-1"))

	def test_agent_rejection_raises(self):
		sess, ws = _build_session()

		def _nack():
			req_id = ws.sent[-1]["id"]
			return _frame({"type": "res", "id": req_id, "ok": False,
						   "error": {"code": "BAD_REQ", "message": "x"}})

		ws._frames.append(_nack)
		with self.assertRaises(OpenclawUnreachableError):
			list(sess.stream_agent_turn("s", "hi", "i"))

	def test_other_runs_dropped_during_streaming(self):
		sess, ws = _build_session()

		def _ack():
			req_id = ws.sent[-1]["id"]
			return _frame({"type": "res", "id": req_id, "ok": True,
						   "payload": {"runId": "run-A"}})

		ws._frames.append(_ack)
		ws._frames.append(_frame({"type": "event", "event": "agent.event",
								  "payload": {"runId": "run-B", "stream": "text",
											  "data": {"delta": "wrong run"}}}))
		ws._frames.append(_frame({"type": "event", "event": "agent.event",
								  "payload": {"runId": "run-A", "stream": "lifecycle",
											  "data": {"phase": "end"}}}))
		# Should terminate cleanly; cross-run event silently dropped.
		list(sess.stream_agent_turn("s", "hi", "i"))


# --- TestClose ------------------------------------------------------------

class TestClose(FrappeTestCase):
	def test_close_is_safe_to_call_twice(self):
		sess, ws = _build_session()
		sess.close()
		sess.close()
		self.assertTrue(ws.closed)


# --- TestSelfHeal ---------------------------------------------------------

class TestSelfHealOnStalePairing(FrappeTestCase):
	"""When admin re-provisions a tenant, the new container has no record of
	the customer's existing chat_device_*. The first WS connect fails with
	one of openclaw's pairing-stale errors. openclaw_client should detect
	that, clear local creds, re-pair via ensure_paired, and retry the WS
	once. A second stale signal is a real failure (no infinite loop)."""

	def _build_two_ws(self, first_reject_marker: str, second_ok: bool):
		"""Return two scripted WS instances: first one rejects connect with
		`first_reject_marker` in the error message; second one accepts."""
		first_sent: list = []
		second_sent: list = []

		def _first_nack():
			req_id = first.sent[-1]["id"]
			return _frame({"type": "res", "id": req_id, "ok": False,
						   "error": {"code": "UNAUTHORIZED", "message": first_reject_marker}})

		def _second_ok():
			req_id = second.sent[-1]["id"]
			return _frame({"type": "res", "id": req_id, "ok": True, "payload": {}})

		def _second_nack():
			req_id = second.sent[-1]["id"]
			return _frame({"type": "res", "id": req_id, "ok": False,
						   "error": {"code": "UNAUTHORIZED", "message": first_reject_marker}})

		first = _ScriptedWS([_challenge(), _first_nack])
		second_response = _second_ok if second_ok else _second_nack
		second = _ScriptedWS([_challenge(), second_response])
		return first, second

	def _connect_with_two_ws(self, first_ws, second_ws):
		ws_iter = iter([first_ws, second_ws])
		clear_called: list = []

		def _fake_clear():
			clear_called.append(True)

		creds = _make_creds()
		ensure_paired_calls: list = []

		def _fake_ensure_paired():
			ensure_paired_calls.append(True)
			return creds

		with patch("jarvis.chat.openclaw_client.websocket.create_connection",
				   side_effect=lambda *a, **kw: next(ws_iter)), \
			 patch("jarvis.chat.openclaw_client.ensure_paired",
				   side_effect=_fake_ensure_paired), \
			 patch("jarvis.chat.openclaw_client.clear_credentials",
				   side_effect=_fake_clear):
			result = OpenclawSession.connect("ws://t", "x")
		return result, clear_called, ensure_paired_calls

	def test_device_not_paired_triggers_repair_and_retry_succeeds(self):
		first_ws, second_ws = self._build_two_ws("device-not-paired", second_ok=True)
		sess, clears, ensure_calls = self._connect_with_two_ws(first_ws, second_ws)
		# clear_credentials was called once between the two attempts.
		self.assertEqual(len(clears), 1)
		# ensure_paired was called twice (once per attempt).
		self.assertEqual(len(ensure_calls), 2)
		self.assertTrue(first_ws.closed)
		self.assertFalse(second_ws.closed)
		sess.close()

	def test_token_revoked_also_triggers_repair(self):
		first_ws, second_ws = self._build_two_ws("token-revoked", second_ok=True)
		sess, clears, _ = self._connect_with_two_ws(first_ws, second_ws)
		self.assertEqual(len(clears), 1)
		sess.close()

	def test_second_failure_does_not_loop(self):
		"""After one repair attempt, a second stale-pairing signal must
		propagate as a real failure — not a third retry."""
		first_ws, second_ws = self._build_two_ws("device-not-paired", second_ok=False)
		with self.assertRaises(OpenclawUnreachableError):
			self._connect_with_two_ws(first_ws, second_ws)

	def test_signature_invalid_does_not_trigger_repair(self):
		"""A signing bug must surface, not get masked by a silent re-pair.
		signature-invalid means our client code is broken; clearing creds
		won't help and the operator needs to see the original error."""
		creds = _make_creds()

		def _nack():
			req_id = first_ws.sent[-1]["id"]
			return _frame({"type": "res", "id": req_id, "ok": False,
						   "error": {"code": "UNAUTHORIZED", "message": "device-signature-invalid"}})

		first_ws = _ScriptedWS([_challenge(), _nack])
		clear_called: list = []
		with patch("jarvis.chat.openclaw_client.websocket.create_connection",
				   return_value=first_ws), \
			 patch("jarvis.chat.openclaw_client.ensure_paired", return_value=creds), \
			 patch("jarvis.chat.openclaw_client.clear_credentials",
				   side_effect=lambda: clear_called.append(True)):
			with self.assertRaises(OpenclawUnreachableError) as cm:
				OpenclawSession.connect("ws://t", "x")
		self.assertFalse(clear_called, "should not clear creds for signing bugs")
		self.assertIn("signature-invalid", str(cm.exception))
