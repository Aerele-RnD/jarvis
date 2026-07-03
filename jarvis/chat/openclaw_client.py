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

Public surface: OpenclawSession.connect / create_session / chat_send /
relay_turn_events / set_session_model / subscribe_session / get_history /
get_session_messages / is_run_active / fire_agent / stream_agent_turn /
close. The managed chat path now uses the relay pair (chat_send +
relay_turn_events): the turn is owned by openclaw after the chat.send ack,
streaming rides the broadcast agent frames, completion comes from the
run-scoped chat event, and relay_turn_events never raises after entry -
interruptions degrade to snapshot recovery instead of errors.
stream_agent_turn remains for auto-title; fire_agent for prewarm.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import websocket


_logger = logging.getLogger(__name__)

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
# Wall-clock cap on one agent turn waiting for the WS lifecycle to
# complete (final lifecycle "end" frame from openclaw). Was 180s when
# the bench + openclaw container ran on the same host (sub-ms WS
# RTT); bumped to 600s after a Frappe-Cloud-hosted bench + Hetzner-
# hosted openclaw deploy hit the 180s cap on multi-recipient
# announcement turns. Each tool call now crosses the public internet
# (~50-200ms WAN RTT depending on FC↔Hetzner region pairing); a
# typical multi-step turn with ~30 tool calls + a 26-recipient batch
# send hit ~4-8s of pure network overhead alone, then ran past the
# 180s ceiling before openclaw emitted lifecycle-end. The row-guard
# walk-back (jarvis#134) cut the tool-call count meaningfully but
# WAN latency is a structural floor; the timeout has to absorb it.
# The matching RQ envelope ``_AGENT_TURN_WORKER_TIMEOUT`` in
# jarvis/chat/api.py was bumped in lockstep so the worker has room
# for this turn + pair + WS connect overhead.
TURN_TIMEOUT_SECONDS = 600

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


def _chat_final_text(payload: dict) -> str | None:
	"""Authoritative final text from a chat final event: joined text blocks
	of payload.message.content; None for silent finals."""
	msg = payload.get("message")
	if not isinstance(msg, dict):
		return None
	c = msg.get("content")
	if isinstance(c, str):
		return c or None
	if isinstance(c, list):
		parts = [
			b.get("text", "") for b in c
			if isinstance(b, dict) and b.get("type") == "text"
			and isinstance(b.get("text"), str)
		]
		joined = "\n".join(p for p in parts if p.strip())
		return joined or None
	return None


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
		# Timing breakdown logged so the connection pool's win is
		# measurable in production. Three phases:
		#   - ensure_paired (cache hit on a paired bench, real I/O on
		#     first run or after repair)
		#   - WS open (DNS + TCP + TLS + WS upgrade)
		#   - _handshake (3-phase signed connect over an open WS)
		# The pool reuses connections, so we only pay this on pool
		# miss / stale eviction / first turn in a worker process.
		t_pair_start = time.monotonic()
		creds = ensure_paired()
		t_pair_done = time.monotonic()
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
		t_ws_done = time.monotonic()

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
		t_handshake_done = time.monotonic()
		_logger.info(
			"OpenclawSession.connect: pair_ms=%d ws_open_ms=%d handshake_ms=%d total_ms=%d gateway=%s",
			int((t_pair_done - t_pair_start) * 1000),
			int((t_ws_done - t_pair_done) * 1000),
			int((t_handshake_done - t_ws_done) * 1000),
			int((t_handshake_done - t_pair_start) * 1000),
			gateway_url,
		)
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

	# -- openclaw-native turn model (chat.send + chat.history + sessions.*) --
	# Mirrors openclaw's own UI gateway client so the bench can drive a turn
	# and reconcile from the durable transcript instead of holding the agent
	# RPC's request stream. Each method below is a plain request/response.

	def chat_send(
		self, session_key: str, message: str, idempotency_key: str,
		*, thinking: str | None = None, deliver: bool = False,
		attachments: list[dict] | None = None,
		timeout_s: float = CONNECT_TIMEOUT_SECONDS,
	) -> dict:
		"""Start an agent turn via chat.send (openclaw's UI turn-start RPC).

		Returns the ack payload, e.g. {"runId": ..., "status": "in_flight"}.
		The turn's output is delivered as session-scoped "chat" events (consume
		them via the relay after subscribe_session), NOT on this response.
		deliver=False keeps the result session-only (no external channel
		delivery), matching the current chat path."""
		params: dict = {
			"sessionKey": session_key,
			"message": message,
			"idempotencyKey": idempotency_key,
			"deliver": deliver,
		}
		if thinking:
			params["thinking"] = thinking
		if attachments:
			params["attachments"] = attachments
		res = self._request("chat.send", params, timeout_s=timeout_s)
		return res.get("payload") or {}

	def subscribe_session(
		self, session_key: str, *, timeout_s: float = CONNECT_TIMEOUT_SECONDS,
	) -> dict:
		"""Subscribe THIS connection to a session's message events via
		sessions.messages.subscribe. After this the WS receives the session's
		message event frames going forward. openclaw keeps no per-run delta
		buffer, so this yields only FUTURE events - catch up via get_history /
		get_session_messages on (re)connect."""
		res = self._request(
			"sessions.messages.subscribe", {"key": session_key}, timeout_s=timeout_s,
		)
		return res.get("payload") or {}

	def get_history(
		self, session_key: str, *, limit: int = 100, max_chars: int = 4000,
		timeout_s: float = CONNECT_TIMEOUT_SECONDS,
	) -> dict:
		"""Snapshot the session's DISPLAY transcript via chat.history. Returns
		{"sessionId", "messages", "thinkingLevel"} - the same projected display
		messages openclaw's UI renders. The authoritative source of truth used
		to reconcile after a timeout / reconnect."""
		res = self._request(
			"chat.history",
			{"sessionKey": session_key, "limit": limit, "maxChars": max_chars},
			timeout_s=timeout_s,
		)
		return res.get("payload") or {}

	def get_session_messages(
		self, session_key: str, *, limit: int = 50,
		timeout_s: float = CONNECT_TIMEOUT_SECONDS,
	) -> list:
		"""Raw recent transcript tail via sessions.get. Returns the messages
		list (each: role, content, __openclaw:{seq,id}); [] for an unknown or
		empty session."""
		res = self._request(
			"sessions.get", {"key": session_key, "limit": limit}, timeout_s=timeout_s,
		)
		return (res.get("payload") or {}).get("messages") or []

	def is_run_active(
		self, session_key: str, *, timeout_s: float = CONNECT_TIMEOUT_SECONDS,
	) -> bool:
		"""Non-destructive done-signal: True iff the gateway is tracking an
		in-flight run for session_key. Reads sessions.list and matches
		hasActiveRun on the row whose key == session_key. (Do NOT use
		sessions.abort for this - it kills the run.)"""
		res = self._request("sessions.list", {}, timeout_s=timeout_s)
		sessions = (res.get("payload") or {}).get("sessions") or []
		for s in sessions:
			if s.get("key") == session_key:
				return bool(s.get("hasActiveRun"))
		return False

	def set_session_model(
		self, session_key: str, model_ref: str,
		*, timeout_s: float = CONNECT_TIMEOUT_SECONDS,
	) -> None:
		"""Point the session at ``model_ref`` (``"<provider>/<model>"`` or
		bare ``"<model>"``) via ``sessions.patch``. chat.send has no per-turn
		model param, so per-conversation overrides are applied to the session
		before the send."""
		self._request(
			"sessions.patch", {"key": session_key, "model": model_ref},
			timeout_s=timeout_s,
		)

	def relay_turn_events(
		self, session_key: str, run_id: str,
		*, soft_deadline_s: float = TURN_TIMEOUT_SECONDS,
	) -> Iterator[dict[str, Any]]:
		"""Consume broadcast events for a chat.send run until a terminal
		``chat`` event, the soft deadline, or a transport drop.

		Mirror of openclaw's own UI model: token/tool streaming comes from
		the broadcast ``agent`` frames (retagged with the chat.send
		clientRunId == run_id); completion comes ONLY from the run-scoped
		``chat`` event (state final|aborted|error). agent ``lifecycle``
		frames are dropped so there is a single terminal path.

		NEVER raises after entry. Terminal yields:
		  {"kind": "relay:final", "text": str|None}
		  {"kind": "relay:error", "state": "error"|"aborted", "error": str}
		  {"kind": "relay:interrupted", "reason": "transport"|"deadline", ...}
		"""
		deadline = time.monotonic() + soft_deadline_s
		while True:
			remaining = deadline - time.monotonic()
			if remaining <= 0:
				yield {"kind": "relay:interrupted", "reason": "deadline"}
				return
			try:
				frame = self._recv(remaining)
			except OpenclawUnreachableError as e:
				# Close the dead WS before yielding: this generator swallows
				# the exception by design, so the pool's discard-on-exception
				# contract never fires. Closing flips the connected flag the
				# pool healthcheck reads, so the corpse is not handed to the
				# next turn (which would fail pre-ack as a false run:error).
				try:
					self.close()
				except Exception:
					pass
				yield {"kind": "relay:interrupted", "reason": "transport", "detail": str(e)}
				return
			if frame is None or frame.get("type") != "event":
				continue
			payload = frame.get("payload") or {}
			if frame.get("event") == "chat":
				if payload.get("runId") != run_id or payload.get("sessionKey") != session_key:
					continue
				state = payload.get("state")
				if state == "final":
					yield {"kind": "relay:final", "text": _chat_final_text(payload)}
					return
				if state in ("error", "aborted"):
					yield {
						"kind": "relay:error", "state": state,
						"error": payload.get("errorMessage") or state,
					}
					return
				continue  # delta (150ms cumulative mirror) and unknown states: ignore
			if payload.get("runId") != run_id:
				continue
			parsed = parse_event(payload)
			if parsed is None or parsed.get("kind") == "lifecycle":
				continue
			yield parsed

	def fire_agent(self, session_key: str, message: str, idempotency_key: str,
	               *, model: str | None = None, provider: str | None = None) -> str:
		"""Send one agent turn and return its runId after the ack, WITHOUT
		consuming the event stream. openclaw keeps running the turn server
		side after we close (the run lane survives client disconnect), so this
		is enough to warm the provider prompt cache. ``deliver`` is False so
		the result stays session-only. ``_request`` drops the interleaved
		event frames and returns the agent ack response."""
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
		res = self._request("agent", params, timeout_s=CONNECT_TIMEOUT_SECONDS)
		return (res.get("payload") or {}).get("runId") or ""

	def stream_agent_turn(
		self, session_key: str, message: str, idempotency_key: str,
		*,
		model: str | None = None,
		provider: str | None = None,
		attachments: list[dict] | None = None,
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
		if attachments:
			# Native vision input. openclaw's `agent` handler reads these and
			# normalizes them to the active provider's image blocks; the flat
			# {type:"image", mimeType, fileName, content:<base64>} shape is what
			# its gateway normalizer accepts.
			params["attachments"] = attachments
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
		# The run has started (we have the ack); a WS drop from here is
		# RECOVERABLE - openclaw keeps running and persists the result - so tag
		# it code="turn-timeout" to park for recovery, never a false error (#4).
		while time.monotonic() < deadline:
			try:
				frame = self._recv(deadline - time.monotonic())
			except OpenclawUnreachableError as e:
				if getattr(e, "code", None):
					raise
				raise OpenclawUnreachableError(str(e), code="turn-timeout") from e
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
		raise OpenclawUnreachableError(
			"agent turn timed out before lifecycle end", code="turn-timeout",
		)

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
