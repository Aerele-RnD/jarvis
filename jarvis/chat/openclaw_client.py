"""Python WebSocket client for openclaw gateway operator RPC.

Translation of demo.py's embedded _NODE_SCRIPT to native Python. Lives in
the chat package because that's where it's used; could move to a shared
location if a non-chat caller appears later.

Usage:
    session = OpenclawSession.connect(gateway_url, gateway_token)
    session_key = session.create_session(label="my-chat")
    for event in session.stream_agent_turn(session_key, message, idem_key):
        # event is a dict from jarvis.chat.events.parse_event
        ...
    session.close()
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

from websocket import WebSocketException, create_connection

from jarvis.chat.events import parse_event
from jarvis.exceptions import OpenclawUnreachableError

CONNECT_TIMEOUT_SECONDS = 10
TURN_TIMEOUT_SECONDS = 180  # generous: tool calls + LLM token streaming


class OpenclawSession:
	def __init__(self, ws):
		self._ws = ws

	@classmethod
	def connect(cls, gateway_url: str, gateway_token: str) -> OpenclawSession:
		try:
			ws = create_connection(gateway_url, timeout=CONNECT_TIMEOUT_SECONDS)
		except (WebSocketException, OSError) as e:
			raise OpenclawUnreachableError(f"WS connect failed: {e}") from e

		connect_id = str(uuid.uuid4())
		ws.send(json.dumps({
			"type": "req",
			"id": connect_id,
			"method": "connect",
			"params": {
				"minProtocol": 3,
				"maxProtocol": 4,
				"role": "operator",
				"client": {
					"id": "gateway-client",
					"version": "0.1.0",
					"platform": "linux",
					"mode": "backend",
				},
				"scopes": ["operator.admin"],
				"auth": {"token": gateway_token},
			},
		}))
		_await_ack(ws, connect_id, "connect")
		return cls(ws)

	def create_session(self, label: str = "jarvis-chat") -> str:
		req_id = str(uuid.uuid4())
		self._ws.send(json.dumps({
			"type": "req",
			"id": req_id,
			"method": "sessions.create",
			"params": {"label": label},
		}))
		ack = _await_ack(self._ws, req_id, "sessions.create")
		key = ack.get("payload", {}).get("key")
		if not key:
			raise OpenclawUnreachableError("sessions.create returned no key")
		return key

	def stream_agent_turn(
		self,
		session_key: str,
		message: str,
		idempotency_key: str,
	) -> Iterator[dict[str, Any]]:
		req_id = str(uuid.uuid4())
		self._ws.send(json.dumps({
			"type": "req",
			"id": req_id,
			"method": "agent",
			"params": {
				"message": message,
				"sessionKey": session_key,
				"deliver": False,
				"idempotencyKey": idempotency_key,
			},
		}))
		ack = _await_ack(self._ws, req_id, "agent")
		run_id = ack.get("payload", {}).get("runId")
		if not run_id:
			raise OpenclawUnreachableError("agent RPC returned no runId")

		deadline = time.monotonic() + TURN_TIMEOUT_SECONDS
		while time.monotonic() < deadline:
			raw = self._ws.recv()
			if not raw:
				break
			try:
				frame = json.loads(raw)
			except json.JSONDecodeError:
				continue
			if frame.get("type") != "event":
				continue
			payload = frame.get("payload") or {}
			if payload.get("runId") != run_id:
				continue  # event from a different run
			parsed = parse_event(payload)
			if parsed is None:
				continue
			yield parsed
			if parsed["kind"] == "lifecycle" and parsed.get("phase") in ("end", "error"):
				return
		raise OpenclawUnreachableError("agent turn timed out before lifecycle end")

	def close(self) -> None:
		try:
			self._ws.close()
		except Exception:
			pass


def _await_ack(ws, req_id: str, method: str) -> dict[str, Any]:
	"""Read frames until we see the res for our req_id; raise on failure."""
	deadline = time.monotonic() + CONNECT_TIMEOUT_SECONDS
	while time.monotonic() < deadline:
		raw = ws.recv()
		if not raw:
			continue
		try:
			frame = json.loads(raw)
		except json.JSONDecodeError:
			continue
		if frame.get("type") == "res" and frame.get("id") == req_id:
			if not frame.get("ok"):
				err = frame.get("error", {})
				raise OpenclawUnreachableError(
					f"{method} rejected: {err.get('code')} {err.get('message')}"
				)
			return frame
	raise OpenclawUnreachableError(f"{method} ack timed out")
