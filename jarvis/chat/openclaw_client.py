"""Openclaw gateway client — wraps the WebSocket protocol through `docker compose exec`.

Why subprocess + docker exec instead of a direct host-side WS connection:
openclaw's gateway grants `operator.admin` to token-auth connections from
non-loopback sources (LAN bind) but does NOT grant `operator.write`, which
sessions.create requires. Demo.ask_one works around this by running its WS
inside the container via `docker compose exec node -e <script>`; the
connection then comes from container-local loopback, which gets full scopes.

We mirror that pattern here. The Python side spawns a Node WS script inside
the container, pipes JSON commands in, reads line-delimited events out. From
the caller's perspective the API is the same as a direct WS client.

If openclaw later adds a non-loopback grant for operator.write (or per-device
pairing produces a token with both scopes), this module can be reverted to a
direct Python WS without changing the worker.
"""

from __future__ import annotations

import json
import subprocess
import threading
import uuid
from collections.abc import Iterator
from typing import Any

import frappe

from jarvis.chat.events import parse_event
from jarvis.exceptions import OpenclawUnreachableError

CONNECT_TIMEOUT_SECONDS = 10
TURN_TIMEOUT_SECONDS = 180

# Node script that runs inside the container. It speaks a tiny line-based JSON
# protocol over stdin/stdout so the Python side can drive it:
#   stdin commands:  {"cmd":"create_session","label":...} | {"cmd":"agent","sessionKey":...,"message":...,"idempotencyKey":...} | {"cmd":"close"}
#   stdout events:   {"type":"connect","ok":bool,"error":?} | {"type":"create","ok":bool,"key":?,"error":?} | {"type":"event","payload":<openclaw frame>} | {"type":"runDone"} | {"type":"runErr","error":...}
_NODE_SCRIPT = r"""
// When stdout is piped (docker compose exec -T), Node block-buffers writes by
// default — events accumulate until the buffer fills or the process exits, so
// the Python side sees nothing until the agent turn finishes. Forcing the
// handle to blocking mode makes every write synchronous, which lets each
// `emit()` flush a single line through the pipe immediately.
if (process.stdout._handle && typeof process.stdout._handle.setBlocking === 'function') {
  process.stdout._handle.setBlocking(true);
}
if (process.stderr._handle && typeof process.stderr._handle.setBlocking === 'function') {
  process.stderr._handle.setBlocking(true);
}

const readline = require('readline');
const ws = new (require('ws'))('ws://127.0.0.1:18789');
const args = JSON.parse(process.env.JARVIS_CHAT_ARGS);
const { gatewayToken } = args;

const pending = new Map();
let activeRunId = null;

function send(method, params) {
  const id = Math.random().toString(36).slice(2);
  const p = new Promise((res, rej) => pending.set(id, { res, rej }));
  ws.send(JSON.stringify({ type: 'req', id, method, params }));
  return p;
}

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

ws.on('open', async () => {
  try {
    const connectRes = await send('connect', {
      minProtocol: 3, maxProtocol: 4, role: 'operator',
      client: { id: 'gateway-client', version: '0.1.0', platform: 'linux', mode: 'backend' },
      scopes: ['operator.admin'],
      auth: { token: gatewayToken },
    });
    if (!connectRes.ok) {
      emit({ type: 'connect', ok: false, error: JSON.stringify(connectRes.error) });
      process.exit(1);
    }
    emit({ type: 'connect', ok: true });
  } catch (err) {
    emit({ type: 'connect', ok: false, error: err.message });
    process.exit(1);
  }
});

ws.on('message', (raw) => {
  let frame;
  try { frame = JSON.parse(raw); } catch { return; }
  if (frame.type === 'res' && pending.has(frame.id)) {
    const { res } = pending.get(frame.id);
    pending.delete(frame.id);
    res(frame);
    return;
  }
  if (frame.type === 'event') {
    if (activeRunId && frame.payload && frame.payload.runId === activeRunId) {
      emit({ type: 'event', payload: frame.payload });
      const p = frame.payload;
      if (p.stream === 'lifecycle' && (p.data || {}).phase) {
        const phase = p.data.phase;
        if (phase === 'end' || phase === 'error') {
          emit({ type: 'runDone' });
          activeRunId = null;
        }
      }
    }
  }
});

ws.on('error', (err) => { emit({ type: 'wsError', error: err.message }); });
ws.on('close', () => { emit({ type: 'wsClose' }); process.exit(0); });

const rl = readline.createInterface({ input: process.stdin });
rl.on('line', async (line) => {
  let cmd;
  try { cmd = JSON.parse(line); } catch { return; }
  if (cmd.cmd === 'create_session') {
    try {
      const r = await send('sessions.create', { label: cmd.label });
      if (r.ok) {
        emit({ type: 'create', ok: true, key: r.payload.key });
      } else {
        emit({ type: 'create', ok: false, error: JSON.stringify(r.error) });
      }
    } catch (e) {
      emit({ type: 'create', ok: false, error: e.message });
    }
  } else if (cmd.cmd === 'agent') {
    try {
      const r = await send('agent', {
        message: cmd.message,
        sessionKey: cmd.sessionKey,
        deliver: false,
        idempotencyKey: cmd.idempotencyKey,
      });
      if (r.ok) {
        activeRunId = r.payload.runId;
        emit({ type: 'agentAck', runId: r.payload.runId });
      } else {
        emit({ type: 'runErr', error: JSON.stringify(r.error) });
      }
    } catch (e) {
      emit({ type: 'runErr', error: e.message });
    }
  } else if (cmd.cmd === 'close') {
    try { ws.close(); } catch (_) {}
    process.exit(0);
  }
});
"""


class OpenclawSession:
	"""Thin wrapper over a `docker compose exec` Node WS subprocess.

	Public surface matches what the chat worker calls:
	  OpenclawSession.connect(gateway_url, gateway_token) -> session
	  session.create_session(label=...) -> session_key
	  session.stream_agent_turn(session_key, message, idem) -> iter of parsed events
	  session.close()
	"""

	def __init__(self, proc: subprocess.Popen, compose_dir: str):
		self._proc = proc
		self._compose_dir = compose_dir
		self._lock = threading.Lock()  # serialize stdin writes

	@classmethod
	def connect(cls, gateway_url: str, gateway_token: str) -> OpenclawSession:
		# gateway_url is ignored: we always connect to the container's
		# loopback. Kept in the signature for backwards compat with the
		# worker call site and tests.
		_ = gateway_url

		settings = frappe.get_single("Jarvis Settings")
		compose_dir = settings.openclaw_compose_dir
		if not compose_dir:
			raise OpenclawUnreachableError("openclaw_compose_dir not set on Jarvis Settings")

		args = json.dumps({"gatewayToken": gateway_token})
		cmd = [
			"docker", "compose",
			"-f", f"{compose_dir}/docker-compose.yml",
			"exec", "-T",  # -T: no TTY (we want clean pipes)
			"-e", f"JARVIS_CHAT_ARGS={args}",
			"openclaw-gateway",
			"node", "-e", _NODE_SCRIPT,
		]
		try:
			proc = subprocess.Popen(
				cmd,
				stdin=subprocess.PIPE,
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				text=True,
				bufsize=1,  # line-buffered
			)
		except FileNotFoundError as e:
			raise OpenclawUnreachableError(f"docker not on PATH: {e}") from e

		# Wait for the "connect" event
		first = _read_event(proc, timeout=CONNECT_TIMEOUT_SECONDS)
		if not first or first.get("type") != "connect" or not first.get("ok"):
			err = (first or {}).get("error", "no response")
			proc.kill()
			raise OpenclawUnreachableError(f"connect failed: {err}")

		return cls(proc, compose_dir)

	def create_session(self, label: str = "jarvis-chat") -> str:
		self._send_cmd({"cmd": "create_session", "label": label})
		ev = _read_event(self._proc, timeout=CONNECT_TIMEOUT_SECONDS)
		if not ev or ev.get("type") != "create":
			raise OpenclawUnreachableError(f"unexpected reply to create_session: {ev}")
		if not ev.get("ok"):
			raise OpenclawUnreachableError(f"sessions.create rejected: {ev.get('error')}")
		key = ev.get("key")
		if not key:
			raise OpenclawUnreachableError("sessions.create returned no key")
		return key

	def stream_agent_turn(
		self,
		session_key: str,
		message: str,
		idempotency_key: str,
	) -> Iterator[dict[str, Any]]:
		self._send_cmd({
			"cmd": "agent",
			"sessionKey": session_key,
			"message": message,
			"idempotencyKey": idempotency_key,
		})
		# Expect agentAck first, then event/event/.../runDone
		import time
		deadline = time.monotonic() + TURN_TIMEOUT_SECONDS
		got_ack = False
		while time.monotonic() < deadline:
			ev = _read_event(self._proc, timeout=TURN_TIMEOUT_SECONDS)
			if ev is None:
				break
			t = ev.get("type")
			if t == "agentAck":
				got_ack = True
				continue
			if t == "runErr":
				raise OpenclawUnreachableError(f"agent run errored: {ev.get('error')}")
			if t == "event":
				parsed = parse_event(ev.get("payload") or {})
				if parsed is not None:
					yield parsed
				continue
			if t == "runDone":
				return
			if t == "wsError" or t == "wsClose":
				raise OpenclawUnreachableError(f"openclaw WS lost: {ev}")
		if not got_ack:
			raise OpenclawUnreachableError("agent RPC never acknowledged")
		raise OpenclawUnreachableError("agent turn timed out before lifecycle end")

	def close(self) -> None:
		try:
			self._send_cmd({"cmd": "close"})
		except Exception:
			pass
		try:
			self._proc.terminate()
			self._proc.wait(timeout=5)
		except Exception:
			try:
				self._proc.kill()
			except Exception:
				pass

	def _send_cmd(self, cmd: dict) -> None:
		with self._lock:
			if self._proc.stdin is None or self._proc.stdin.closed:
				raise OpenclawUnreachableError("subprocess stdin closed")
			self._proc.stdin.write(json.dumps(cmd) + "\n")
			self._proc.stdin.flush()


def _read_event(proc: subprocess.Popen, timeout: float) -> dict | None:
	"""Read a single line-delimited JSON event from the subprocess stdout."""
	import select
	if proc.stdout is None:
		return None
	# Wait for stdout readability
	r, _, _ = select.select([proc.stdout], [], [], timeout)
	if not r:
		return None
	line = proc.stdout.readline()
	if not line:
		return None
	try:
		return json.loads(line.strip())
	except json.JSONDecodeError:
		return None
