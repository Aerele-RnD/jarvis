import json
import os
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

import websocket
from websocket import create_connection

from jarvis.exceptions import (
	OpenclawReloadFailedError,
	OpenclawRestartFailedError,
	OpenclawUnreachableError,
)

RELOAD_TIMEOUT_SECONDS = 10
RESTART_TIMEOUT_SECONDS = 60
HEALTHCHECK_INTERVAL_SECONDS = 1


def write_key_file(path: str, key: str) -> None:
	"""Write `key` to `path` with mode 0600. Creates parent dirs if missing."""
	target = Path(path)
	target.parent.mkdir(parents=True, exist_ok=True)
	# Write atomically: write to .tmp then rename
	tmp = target.with_suffix(target.suffix + ".tmp")
	tmp.write_text(key)
	os.chmod(tmp, 0o600)
	os.replace(tmp, target)


def reload_secrets(gateway_url: str, gateway_token: str) -> None:
	"""Open WS to openclaw, send connect handshake, then secrets.reload, await ack."""
	try:
		ws = create_connection(gateway_url, timeout=RELOAD_TIMEOUT_SECONDS)
	except (websocket.WebSocketException, OSError) as e:
		raise OpenclawUnreachableError(f"connect failed: {e}") from e

	deadline = time.monotonic() + RELOAD_TIMEOUT_SECONDS
	try:
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

		connect_res = _await_response(ws, connect_id, deadline)
		if not connect_res.get("ok"):
			err = connect_res.get("error") or {}
			raise OpenclawUnreachableError(
				f"connect rejected: {err.get('code', '?')}: {err.get('message', '')}"
			)

		reload_id = str(uuid.uuid4())
		ws.send(json.dumps({
			"type": "req",
			"id": reload_id,
			"method": "secrets.reload",
			"params": {},
		}))

		reload_res = _await_response(ws, reload_id, deadline)
		if not reload_res.get("ok"):
			err = reload_res.get("error") or {}
			raise OpenclawReloadFailedError(
				f"secrets.reload rejected: {err.get('code', '?')}: {err.get('message', '')}"
			)
	except (websocket.WebSocketTimeoutException, TimeoutError) as e:
		raise OpenclawReloadFailedError(f"timeout: {e}") from e
	except websocket.WebSocketException as e:
		raise OpenclawUnreachableError(f"ws error: {e}") from e
	finally:
		try:
			ws.close()
		except Exception:
			pass


def ping(gateway_url: str, gateway_token: str) -> None:
	"""Open WS to openclaw and complete the connect handshake only — no
	secrets.reload, no restart. Raises OpenclawUnreachableError if the
	socket can't open or the handshake is rejected. Used by the
	'Test openclaw connection' diagnostic button on Jarvis Settings."""
	try:
		ws = create_connection(gateway_url, timeout=RELOAD_TIMEOUT_SECONDS)
	except (websocket.WebSocketException, OSError) as e:
		raise OpenclawUnreachableError(f"connect failed: {e}") from e

	deadline = time.monotonic() + RELOAD_TIMEOUT_SECONDS
	try:
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
		connect_res = _await_response(ws, connect_id, deadline)
		if not connect_res.get("ok"):
			err = connect_res.get("error") or {}
			raise OpenclawUnreachableError(
				f"connect rejected: {err.get('code', '?')}: {err.get('message', '')}"
			)
	except (websocket.WebSocketTimeoutException, TimeoutError) as e:
		raise OpenclawUnreachableError(f"timeout: {e}") from e
	except websocket.WebSocketException as e:
		raise OpenclawUnreachableError(f"ws error: {e}") from e
	finally:
		try:
			ws.close()
		except Exception:
			pass


def _await_response(ws, request_id: str, deadline: float) -> dict:
	"""Read frames until a `res` frame with matching id arrives. Other frames are ignored."""
	while True:
		remaining = deadline - time.monotonic()
		if remaining <= 0:
			raise OpenclawReloadFailedError("timeout waiting for response")
		ws.settimeout(remaining)
		raw = ws.recv()
		if not raw:
			raise OpenclawUnreachableError("ws closed unexpectedly")
		try:
			frame = json.loads(raw)
		except json.JSONDecodeError:
			continue  # ignore unparseable noise
		if frame.get("type") == "res" and frame.get("id") == request_id:
			return frame
		# otherwise: event, challenge, or other frame — skip


def restart_gateway(compose_dir: str) -> None:
	"""Run `docker compose restart openclaw-gateway` then poll /healthz until ready."""
	compose_file = f"{compose_dir}/docker-compose.yml"
	env_file = f"{compose_dir}/.env"
	cmd = ["docker", "compose", "-f", compose_file]
	if os.path.exists(env_file):
		cmd.extend(["--env-file", env_file])
	cmd.extend(["restart", "openclaw-gateway"])

	try:
		subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=RESTART_TIMEOUT_SECONDS)
	except subprocess.CalledProcessError as e:
		raise OpenclawRestartFailedError(
			f"docker compose restart failed: {e.stderr or e.stdout or e}"
		) from e
	except subprocess.TimeoutExpired as e:
		raise OpenclawRestartFailedError(f"docker compose restart timed out: {e}") from e

	# Poll for healthy
	deadline = time.monotonic() + RESTART_TIMEOUT_SECONDS
	last_err = None
	while time.monotonic() < deadline:
		try:
			with urllib.request.urlopen("http://127.0.0.1:18789/healthz", timeout=2) as r:
				if 200 <= r.status < 300:
					return
				last_err = f"HTTP {r.status}"
		except Exception as e:
			last_err = str(e)
		time.sleep(HEALTHCHECK_INTERVAL_SECONDS)
	raise OpenclawRestartFailedError(f"gateway not healthy after restart: {last_err}")


def push_creds_reload(settings) -> None:
	"""Key-only-change path: write the new key to the SecretRef file, call secrets.reload."""
	key = settings.get_password("llm_api_key") or ""
	write_key_file(settings.agent_llm_key_path, key)
	reload_secrets(settings.agent_url, settings.get_password("agent_token"))


def push_creds_restart(settings, gateway_token: str) -> None:
	"""Provider/model/baseUrl-change path: re-render openclaw.json, write key file, restart container."""
	from jarvis.openclaw_config import render_config

	rendered = render_config(settings, gateway_token)
	Path(settings.agent_config_path).write_text(rendered)

	key = settings.get_password("llm_api_key") or ""
	write_key_file(settings.agent_llm_key_path, key)

	restart_gateway(settings.agent_compose_dir)
