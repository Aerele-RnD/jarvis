"""Openclaw gateway client - direct WebSocket with device-paired auth.

Previously this module shelled out to `docker compose exec ... node -e <script>`
so the WS connection would appear as loopback inside the container - openclaw
strips self-declared `operator.write` scopes from non-loopback token-only
clients, and the chat worker needed write scope for sessions.create.

Now we do it the way openclaw was designed for: pair the customer bench as
a device once (via jarvis.chat.device.ensure_paired → admin → fleet-agent),
and present an Ed25519-signed v3 device-auth envelope at every connect.
openclaw verifies the signature against the registered public key, grants
the requested scopes, and the rest of the protocol (sessions.create, agent,
event streaming) is identical to what the Node script used to do - only the
transport changed from subprocess-pipes to direct WS frames.

The public surface (OpenclawSession.connect / create_session /
stream_agent_turn / close) is unchanged. worker.py and api.py don't notice.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import websocket

from jarvis.chat.device import (
	ChatDeviceCredentials, build_payload_v3, clear_credentials,
	ensure_paired, sign_payload,
)
from jarvis.chat.events import parse_event


# Openclaw gateway's WS frame format. Looks JSON-RPC-shaped but has its
# own type discriminator (``"type": "req"|"res"|"event"``) rather than
# JSON-RPC 2.0's ``"jsonrpc": "2.0"`` field, so a generic JSON-RPC
# library doesn't fit. The frame builders here are the (small,
# explicit) protocol seam between the bench and openclaw's WS;
# centralised so the next time we need to add a frame field (e.g.
# trace IDs, span context) it lands in one place rather than at every
# ws.send site. Punch-list item "JSON-RPC framing reinvented" from
# the 2026-06-16 review.

def _build_request_frame(method: str, params: dict, *, req_id: str | None = None) -> tuple[str, str]:
	"""Build a serialised openclaw request frame.

	Returns (json_payload, req_id) - caller passes json_payload to
	ws.send and uses req_id to match the response frame.
	"""
	rid = req_id or uuid.uuid4().hex
	return json.dumps({
		"type": "req", "id": rid, "method": method, "params": params,
	}), rid


def _is_response_frame(frame: dict, req_id: str) -> bool:
	"""True when ``frame`` is the response to the request that issued
	``req_id``. Encapsulates the (type, id) discrimination so the two
	caller sites don't open-code it independently."""
	return frame.get("type") == "res" and frame.get("id") == req_id
from jarvis.exceptions import OpenclawUnreachableError

CONNECT_TIMEOUT_SECONDS = 10
TURN_TIMEOUT_SECONDS = 180

# Scopes the chat path needs: operator.write for sessions.create + agent;
# operator.admin so the same connection can also read state (status snapshots,
# etc.) without re-pairing.
_REQUESTED_SCOPES = ["operator.write", "operator.admin"]
_CLIENT_ID = "gateway-client"
_CLIENT_MODE = "backend"
_ROLE = "operator"
_PLATFORM = "linux"  # informational; only affects the v3 signature payload

# openclaw rejection codes that indicate the customer's stored pairing
# is stale for the CURRENT container (typically because admin re-provisioned
# the tenant and the new container has no record of this deviceId). On
# any of these we wipe + re-pair once. OTHER rejection codes
# (signature-invalid, scope-mismatch, etc.) are programming bugs / config
# errors and must NOT trigger a retry - that'd hide the bug behind silent
# re-pair attempts that destroy valid credentials.
#
# Sprint-3 (2026-06-16 review): we used to substring-match on
# ``str(err).lower()`` which would false-positive any future error
# embedding one of these tokens in its message text (think log lines,
# diagnostic dumps, partial-match codes like ``device-not-paired-yet``).
# The classifier now reads the structured ``.code`` attribute populated
# at the raise site from openclaw's response envelope.
_STALE_PAIRING_CODES = frozenset({
	"device-not-paired",
	"token-mismatch",
	"token-revoked",
	"device-id-mismatch",
})


def _is_stale_pairing(err: Exception) -> bool:
	"""Return True iff ``err`` is an OpenclawUnreachableError whose
	openclaw error.code is in the stale-pairing set.

	Strictly typed: an error WITHOUT a ``.code`` attribute (network-level
	failure, programmer bug) never triggers the repair path. The previous
	substring check would have caught these falsely if their message
	happened to contain one of the marker strings.
	"""
	code = getattr(err, "code", None)
	return code in _STALE_PAIRING_CODES


def _persisted_device_id() -> str:
	"""Cheap unauthenticated read of Jarvis Settings.chat_device_id.

	Used by the repair convoy-collapse path to detect "someone else
	already re-paired" without re-running the whole ensure_paired flow.
	Returns "" if Settings is unreadable for any reason (the caller
	treats empty as "no winner yet, proceed").
	"""
	import frappe
	try:
		return (frappe.db.get_single_value("Jarvis Settings", "chat_device_id") or "").strip()
	except Exception:
		return ""


class OpenclawSession:
	"""Direct WebSocket session to one tenant's openclaw gateway.

	Public surface:
	  OpenclawSession.connect(gateway_url) -> session
	  session.create_session(label=...) -> session_key
	  session.stream_agent_turn(session_key, message, idem) -> iter of parsed events
	  session.close()

	Authentication is via device pairing - the chat device's deviceToken
	from `jarvis.chat.device.ensure_paired()` is the credential. The
	legacy shared bearer-token path is gone.
	"""

	def __init__(self, ws: websocket.WebSocket, creds: ChatDeviceCredentials):
		self._ws = ws
		self._creds = creds
		self._lock = threading.Lock()  # serialize concurrent sends on same WS

	# -- lifecycle --------------------------------------------------------

	@classmethod
	def connect(cls, gateway_url: str) -> OpenclawSession:
		if not gateway_url:
			raise OpenclawUnreachableError("agent_url not set on Jarvis Settings")

		# Two-shot self-heal for tenant re-provisioning: on the first attempt
		# we use whatever paired creds the customer has; if openclaw rejects
		# with a "your pairing is stale" marker (typical when admin replaced
		# the container under us - new container has empty pairing state),
		# we wipe + re-pair once and try again. A second stale signal is a
		# real failure, not a retry candidate.
		return cls._attempt_connect(gateway_url, allow_repair=True)

	@classmethod
	def _attempt_connect(cls, gateway_url: str, *, allow_repair: bool) -> OpenclawSession:
		creds = ensure_paired()
		try:
			ws = websocket.create_connection(
				gateway_url, timeout=CONNECT_TIMEOUT_SECONDS,
				# Origin must be a valid http(s)://… URL; openclaw's controlUi
				# allowedOrigins is "*" in our rendered config, but the
				# Origin-parse path rejects empty/malformed values outright.
				origin="http://localhost",
			)
		except (websocket.WebSocketException, OSError) as e:
			raise OpenclawUnreachableError(f"WS open failed: {e}") from e

		try:
			cls._handshake(ws, creds)
		except OpenclawUnreachableError as e:
			try: ws.close()
			except Exception: pass
			if allow_repair and _is_stale_pairing(e):
				cls._repair_and_reconnect(gateway_url, stale_device_id=creds.device_id)
				return cls._attempt_connect(gateway_url, allow_repair=False)
			raise
		except Exception:
			try: ws.close()
			except Exception: pass
			raise
		return cls(ws, creds)

	@classmethod
	def _repair_and_reconnect(cls, gateway_url: str, *, stale_device_id: str) -> None:
		"""Serialize the clear+re-pair window after a stale-pairing rejection.

		Sprint-2 (2026-06-16 review): with N concurrent chat workers
		racing after a tenant re-provision, every one observes the same
		"stale pairing" error, every one called ``clear_credentials() +
		ensure_paired()``, every one generated a different Ed25519
		keypair, and only the last writer's keypair survived in Jarvis
		Settings - the other N-1 workers held in-memory creds the admin
		side didn't know about, then EACH of them re-paired again,
		flapping admin/openclaw state. The Redis lock collapses the
		convoy: one worker re-pairs, the rest wait, then read the fresh
		keypair from Settings.

		``stale_device_id`` is the device_id we just observed as stale.
		If by the time we acquire the lock the persisted device_id no
		longer matches, the winning worker already re-paired - we skip
		the wipe entirely and the caller's next ``ensure_paired`` reads
		the new creds.
		"""
		from jarvis._redis_lock import redis_lock

		with redis_lock(
			"chat_device_pair_repair", timeout_s=120, blocking_timeout_s=60.0,
		) as acquired:
			# Even if we lost the lock race, we still want to retry the
			# connect once with fresh creds - the holder may have already
			# repaired. Let the caller re-read on its next attempt.
			if not acquired:
				return
			current = _persisted_device_id()
			if current and current != stale_device_id:
				# Another worker already re-paired while we waited. Don't
				# wipe their work; let the caller re-read.
				return
			clear_credentials()
			# Don't prime ensure_paired() here: the caller's next
			# _attempt_connect(allow_repair=False) calls ensure_paired
			# on its own which is what generates+persists the new
			# keypair under our lock. Late convoy followers also call
			# ensure_paired on their own next attempt and see the
			# newly-persisted creds without re-pairing.

	def close(self) -> None:
		try: self._ws.close()
		except Exception: pass

	# -- protocol methods -------------------------------------------------

	def create_session(self, label: str = "jarvis-chat") -> str:
		res = self._request("sessions.create", {"label": label},
							timeout_s=CONNECT_TIMEOUT_SECONDS)
		key = (res.get("payload") or {}).get("key")
		if not key:
			raise OpenclawUnreachableError(f"sessions.create returned no key: {res}")
		return key

	def stream_agent_turn(
		self, session_key: str, message: str, idempotency_key: str,
		*,
		model: str | None = None,
		provider: str | None = None,
	) -> Iterator[dict[str, Any]]:
		"""Send an `agent` request, then yield parsed events until lifecycle.end.

		`model` / `provider` are optional per-turn overrides. When set, they
		flow into openclaw's agent RPC params; the gateway honours them via
		the operator.admin-scope-gated modelOverride path (our connect already
		declares that scope). When omitted, openclaw falls back to
		agents.defaults.model.primary from openclaw.json.

		Yields the same parsed-event shape the worker used to consume from
		the subprocess. Raises OpenclawUnreachableError on WS drop, agent
		errors, or timeout - all the failure modes worker.py already maps to
		assistant-message error rows."""
		params = {
			"message": message,
			"sessionKey": session_key,
			"deliver": False,
			"idempotencyKey": idempotency_key,
		}
		if model:
			params["model"] = model
		if provider:
			params["provider"] = provider
		agent_id = self._send("agent", params)
		deadline = time.monotonic() + TURN_TIMEOUT_SECONDS

		# 1. Drain frames until we see the agent ack OR an error/event for our run.
		active_run_id: str | None = None
		got_ack = False
		while time.monotonic() < deadline:
			frame = self._recv(deadline - time.monotonic())
			if frame is None:
				continue
			ftype = frame.get("type")
			if ftype == "res" and frame.get("id") == agent_id:
				if not frame.get("ok"):
					err = frame.get("error") or {}
					raise OpenclawUnreachableError(
						f"agent rejected: {err.get('code', '?')}: {err.get('message', '')}",
						code=err.get("code"),
					)
				active_run_id = (frame.get("payload") or {}).get("runId")
				got_ack = True
				break
			# Pre-ack events can arrive; pass them through if they belong to us
			# by lifecycle (no runId yet at this point, drop unrelated noise).
		if not got_ack:
			raise OpenclawUnreachableError("agent RPC never acknowledged")

		# 2. Stream events for this run until lifecycle.end / .error.
		while time.monotonic() < deadline:
			frame = self._recv(deadline - time.monotonic())
			if frame is None:
				continue
			ftype = frame.get("type")
			if ftype != "event":
				continue
			payload = frame.get("payload") or {}
			if active_run_id is not None and payload.get("runId") != active_run_id:
				continue
			parsed = parse_event(payload)
			if parsed is not None:
				yield parsed
			# Same lifecycle-phase detection the Node script used.
			if payload.get("stream") == "lifecycle":
				phase = (payload.get("data") or {}).get("phase")
				if phase in ("end", "error"):
					return
		raise OpenclawUnreachableError("agent turn timed out before lifecycle end")

	# -- internals --------------------------------------------------------

	@classmethod
	def _handshake(cls, ws: websocket.WebSocket, creds: ChatDeviceCredentials) -> None:
		"""Receive connect.challenge → sign v3 payload → send connect → expect hello-ok."""
		deadline = time.monotonic() + CONNECT_TIMEOUT_SECONDS

		# 1. Wait for the challenge event.
		nonce: str | None = None
		while time.monotonic() < deadline:
			frame = _recv_with_timeout(ws, deadline - time.monotonic())
			if frame is None:
				continue
			if frame.get("type") == "event" and frame.get("event") == "connect.challenge":
				nonce = (frame.get("payload") or {}).get("nonce")
				break
		if not nonce:
			raise OpenclawUnreachableError("did not receive connect.challenge before timeout")

		# 2. Sign + send the connect frame.
		signed_at_ms = int(time.time() * 1000)
		payload = build_payload_v3(
			device_id=creds.device_id, client_id=_CLIENT_ID, client_mode=_CLIENT_MODE,
			role=_ROLE, scopes=_REQUESTED_SCOPES, signed_at_ms=signed_at_ms,
			device_token=creds.device_token, nonce=nonce,
			platform=_PLATFORM, device_family="",
		)
		signature_b64u = sign_payload(creds.private_key, payload)
		connect_id = uuid.uuid4().hex
		connect_params = {
			"minProtocol": 4,
			"maxProtocol": 4,
			"client": {
				"id": _CLIENT_ID, "version": "0.1.0",
				"platform": _PLATFORM, "mode": _CLIENT_MODE,
			},
			"role": _ROLE,
			"scopes": _REQUESTED_SCOPES,
			"auth": {"deviceToken": creds.device_token},
			"device": {
				"id": creds.device_id,
				"publicKey": creds.public_key,
				"signature": signature_b64u,
				"signedAt": signed_at_ms,
				"nonce": nonce,
			},
		}
		connect_payload, _ = _build_request_frame("connect", connect_params, req_id=connect_id)
		ws.send(connect_payload)

		# 3. Wait for the connect response.
		while time.monotonic() < deadline:
			frame = _recv_with_timeout(ws, deadline - time.monotonic())
			if frame is None:
				continue
			if _is_response_frame(frame, connect_id):
				if not frame.get("ok"):
					err = frame.get("error") or {}
					raise OpenclawUnreachableError(
						f"connect rejected: {err.get('code', '?')}: {err.get('message', '')}",
						code=err.get("code"),
					)
				return
		raise OpenclawUnreachableError("no connect response before timeout")

	def _send(self, method: str, params: dict) -> str:
		"""Send a request frame; return the generated request id."""
		payload, req_id = _build_request_frame(method, params)
		with self._lock:
			self._ws.send(payload)
		return req_id

	def _request(self, method: str, params: dict, *, timeout_s: float) -> dict:
		"""Send a request and wait for the matching response frame.

		Drops out-of-order event frames silently - the caller is RPC-style
		and doesn't need them. stream_agent_turn handles its own framing."""
		req_id = self._send(method, params)
		deadline = time.monotonic() + timeout_s
		while time.monotonic() < deadline:
			frame = self._recv(deadline - time.monotonic())
			if frame is None:
				continue
			if _is_response_frame(frame, req_id):
				if not frame.get("ok"):
					err = frame.get("error") or {}
					raise OpenclawUnreachableError(
						f"{method} rejected: {err.get('code', '?')}: {err.get('message', '')}",
						code=err.get("code"),
					)
				return frame
		raise OpenclawUnreachableError(f"{method} timed out")

	def _recv(self, timeout_s: float) -> dict | None:
		"""Read one frame from the WS, parse JSON, or return None on a soft
		timeout / non-JSON noise. Raises OpenclawUnreachableError on hard
		close so the caller can wrap into an assistant-message error row."""
		return _recv_with_timeout(self._ws, timeout_s)


def _recv_with_timeout(ws: websocket.WebSocket, timeout_s: float) -> dict | None:
	if timeout_s <= 0:
		return None
	ws.settimeout(timeout_s)
	try:
		raw = ws.recv()
	except websocket.WebSocketTimeoutException:
		return None
	except websocket.WebSocketConnectionClosedException as e:
		raise OpenclawUnreachableError(f"openclaw WS closed: {e}") from e
	except websocket.WebSocketException as e:
		raise OpenclawUnreachableError(f"openclaw WS error: {e}") from e
	if not raw:
		return None
	try:
		return json.loads(raw)
	except json.JSONDecodeError:
		return None
