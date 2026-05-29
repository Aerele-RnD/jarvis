"""Demo command for Phase 2.2.a end-to-end verification.

Opens an openclaw session as a specific Frappe user, sends a chat message,
waits for the agent loop to complete, and prints a structured trace showing
session id, tool calls, identity propagation, and the final response.

The WS interaction runs inside the openclaw Docker container via ``docker exec``
so that it connects to the gateway as a loopback client (required for the
gateway-client scope bypass that token-mode auth needs when no device identity
is present).

Identity flow (Path A v2, 2026-05-18):
  1. sessions.create → returns sessionKey
  2. Frappe inserts a Jarvis Chat Session row (sessionKey → user) here in Python
  3. Agent run starts; tool calls fire through the plugin's registered tools
  4. Plugin POSTs to jarvis.api.call_tool with X-Jarvis-Token + X-Jarvis-Session
  5. Frappe resolves the user from the Chat Session row and dispatches under it

Invocation:
    bench --site <site> execute jarvis.demo.ask_one \\
      --kwargs '{"user": "Administrator", "message": "list 5 customers"}'
"""

import json
import subprocess
from pathlib import Path

import frappe
import frappe.utils

DEFAULT_TIMEOUT = 120  # seconds for the whole exchange

# Inline Node.js script that runs inside the openclaw container.
# It connects to 127.0.0.1:18789 (loopback inside the container) with the
# gateway token, creates a session, sends the agent message, and streams
# lifecycle / tool / assistant events until the run ends. Output is
# line-delimited JSON so Python can parse it.
#
# The sessions.pluginPatch step has been removed — identity is now propagated
# via the Frappe database (Jarvis Chat Session row) + HTTP lookup in the plugin.
_NODE_SCRIPT = r"""
const ws = new (require('ws'))('ws://127.0.0.1:18789');
const args = JSON.parse(process.env.JARVIS_DEMO_ARGS);
const { gatewayToken, user, message, timeoutMs } = args;

const pending = new Map();
let settled = false;
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

function finish(code) {
  if (!settled) {
    settled = true;
    clearTimeout(timer);
    ws.close();
    // Give ws.close() a tick to flush, then exit
    setImmediate(() => process.exit(code));
  }
}

const timer = setTimeout(() => {
  if (!settled) {
    emit({ type: 'error', message: 'timeout after ' + timeoutMs + 'ms' });
    finish(1);
  }
}, timeoutMs);

ws.on('open', async () => {
  try {
    const connectRes = await send('connect', {
      minProtocol: 3, maxProtocol: 4, role: 'operator',
      client: { id: 'gateway-client', version: '0.1.0', platform: 'linux', mode: 'backend' },
      scopes: ['operator.admin'],
      auth: { token: gatewayToken },
    });
    if (!connectRes.ok) throw new Error('connect failed: ' + JSON.stringify(connectRes.error));

    const createRes = await send('sessions.create', { label: 'jarvis-demo-' + user + '-' + Date.now() });
    if (!createRes.ok) throw new Error('sessions.create failed: ' + JSON.stringify(createRes.error));
    const sessionKey = createRes.payload.key;
    emit({ type: 'session', sessionKey });

    // Identity is propagated via Frappe's Jarvis Chat Session table (B1 approach).
    // Python inserts the row before starting the Node script. No pluginPatch needed.

    const agentRes = await send('agent', {
      message,
      sessionKey,
      deliver: false,
      idempotencyKey: Math.random().toString(36).slice(2),
    });
    if (!agentRes.ok) throw new Error('agent failed: ' + JSON.stringify(agentRes.error));
    const runId = agentRes.payload.runId;
    activeRunId = runId;
    emit({ type: 'run', runId });
  } catch (err) {
    emit({ type: 'error', message: err.message });
    finish(1);
  }
});

ws.on('message', (raw) => {
  let frame;
  try { frame = JSON.parse(raw); } catch { return; }

  // Route response frames to pending promises
  if (frame.type === 'res' && pending.has(frame.id)) {
    const { res } = pending.get(frame.id);
    pending.delete(frame.id);
    res(frame);
    return;
  }

  // Route event frames
  if (frame.type === 'event') {
    emit({ type: 'event', payload: frame.payload });
    // Detect run completion: lifecycle end/error for our run
    const p = frame.payload;
    if (activeRunId && p && p.stream === 'lifecycle' && p.runId === activeRunId) {
      const phase = (p.data || {}).phase;
      if (phase === 'end' || phase === 'error') {
        finish(0);
      }
    }
  }
});

ws.on('close', () => {
  if (!settled) {
    emit({ type: 'error', message: 'ws closed unexpectedly' });
    finish(1);
  }
});

ws.on('error', (err) => {
  emit({ type: 'error', message: 'ws error: ' + err.message });
  finish(1);
});
"""


def _insert_chat_session(session_key: str, user: str) -> None:
	"""Insert a Jarvis Chat Session row mapping sessionKey → user.

	jarvis.api.call_tool reads this table (keyed by X-Jarvis-Session) to
	resolve the user a tool call should dispatch as. frappe.db.commit()
	makes the row visible to the next HTTP request from the plugin.
	"""
	frappe.get_doc({
		"doctype": "Jarvis Chat Session",
		"session_key": session_key,
		"user": user,
	}).insert(ignore_permissions=True)
	frappe.db.commit()


def ask_one(user: str, message: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
	"""Run one chat turn against openclaw as the given user. Returns a result dict."""
	settings = frappe.get_single("Jarvis Settings")
	gateway_token = settings.get_password("agent_token", raise_exception=False) or ""
	if not gateway_token:
		raise RuntimeError(
			"openclaw not configured. Run `bench execute "
			"jarvis_admin.host_setup.bootstrap_host` to seed the local fleet, "
			"start the fleet-agent uvicorn process, then `bench execute "
			"jarvis.onboarding.dev_onboard` to assign a tenant."
		)
	if not frappe.db.exists("User", user):
		raise RuntimeError(f"unknown Frappe user: {user}")

	print(f"\n[demo] starting openclaw session as user={user!r}\n")

	demo_args = json.dumps({
		"gatewayToken": gateway_token,
		"user": user,
		"message": message,
		"timeoutMs": timeout * 1000,
	})

	compose_file = str(Path(compose_dir) / "docker-compose.yml")

	cmd = [
		"docker", "compose",
		"-f", compose_file,
		"exec",
		"-e", f"JARVIS_DEMO_ARGS={demo_args}",
		"openclaw-gateway",
		"node", "-e", _NODE_SCRIPT,
	]

	proc = subprocess.Popen(
		cmd,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		text=True,
	)

	final_text_parts: list[str] = []
	tool_calls: list[dict] = []
	run_id: str | None = None
	session_key: str | None = None

	try:
		for line in proc.stdout:  # type: ignore[union-attr]
			line = line.rstrip()
			if not line:
				continue
			try:
				msg = json.loads(line)
			except json.JSONDecodeError:
				continue

			msg_type = msg.get("type")

			if msg_type == "session":
				session_key = msg.get("sessionKey")
				print(f"[session created] key={session_key}\n")
				# Insert Chat Session row so the plugin can look up the user.
				# This must happen synchronously before the agent run starts.
				if session_key:
					_insert_chat_session(session_key, user)
					print(f"[chat session row created] sessionKey={session_key} user={user!r}\n")

			elif msg_type == "run":
				run_id = msg.get("runId")
				print(f"[run accepted] runId={run_id}\n")
				print(f"[user→agent] {message!r}\n")

			elif msg_type == "error":
				raise RuntimeError(msg.get("message", "unknown error from node script"))

			elif msg_type == "event":
				payload = msg.get("payload") or {}
				if run_id and payload.get("runId") != run_id:
					continue
				stream = payload.get("stream")
				data = payload.get("data") or {}

				# Debug: enable with JARVIS_DEMO_DEBUG=1 to dump every event raw.
				import os as _os
				if _os.environ.get("JARVIS_DEMO_DEBUG"):
					print(f"[raw event] stream={stream!r} payload={json.dumps(payload)}")

				if stream == "lifecycle":
					phase = data.get("phase")
					if phase == "start":
						print(f"[lifecycle] run started\n")
					elif phase == "end":
						print(f"\n[lifecycle] run ended cleanly")
					elif phase == "error":
						print(f"\n[lifecycle] run errored: {data.get('error')}")

				elif stream == "item":
					# openclaw's unified item stream — kind discriminates between
					# tool calls, model messages, etc.
					kind = data.get("kind")
					phase = data.get("phase")
					if kind == "tool":
						tool_name = data.get("name")
						if phase == "start":
							args = data.get("args") or data.get("arguments") or {}
							print(f"[tool→start] {tool_name}({json.dumps(args)[:200]})")
							tool_calls.append({"tool": tool_name, "args": args, "result": None, "isError": False})
						elif phase == "end":
							status = data.get("status")
							result = data.get("result") or data.get("output")
							is_error = status == "error" or data.get("isError", False)
							if is_error:
								print(f"[tool→error] {tool_name} → {result}")
							else:
								print(f"[tool→ok] {tool_name} status={status}")
							for tc in reversed(tool_calls):
								if tc["tool"] == tool_name and tc["result"] is None:
									tc["result"] = result
									tc["isError"] = is_error
									break
					elif kind == "message":
						text = data.get("text") or data.get("content") or ""
						if text:
							print(text, end="", flush=True)
							final_text_parts.append(text)
					elif kind:
						summary = json.dumps(data)[:160]
						print(f"[item/{kind}/{phase}] {summary}")

				elif stream == "assistant":
					# openclaw streams assistant deltas as {text: <cumulative>, delta: <incremental>}
					# with no phase field. Print each delta inline; keep the latest
					# cumulative `text` as the canonical final reply.
					delta = data.get("delta") or ""
					full_text = data.get("text")
					if delta:
						print(delta, end="", flush=True)
					if isinstance(full_text, str):
						# Replace, not append — `text` is cumulative across deltas.
						final_text_parts.clear()
						final_text_parts.append(full_text)

				elif stream is None:
					# Empty / heartbeat frames — silent.
					continue

				else:
					# Surface any stream we don't recognize, so the operator can
					# update the demo when openclaw's event vocabulary evolves.
					summary = json.dumps(data)[:160]
					print(f"[event/{stream}] {summary}")

		proc.wait(timeout=10)
	except Exception:
		proc.kill()
		proc.wait()
		raise

	stderr_output = proc.stderr.read() if proc.stderr else ""
	if proc.returncode != 0:
		raise RuntimeError(
			f"node script exited with code {proc.returncode}. stderr: {stderr_output[:500]}"
		)

	return {
		"ok": True,
		"runId": run_id,
		"sessionKey": session_key,
		"text": "".join(final_text_parts),
		"tool_calls": tool_calls,
	}
