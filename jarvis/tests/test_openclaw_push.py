import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import (
	OpenclawReloadFailedError,
	OpenclawRestartFailedError,
	OpenclawUnreachableError,
)
from jarvis.openclaw_push import (
	reload_secrets,
	restart_gateway,
	write_key_file,
)


class TestWriteKeyFile(FrappeTestCase):
	def test_writes_contents(self):
		with tempfile.TemporaryDirectory() as tmp:
			target = Path(tmp) / "llm.key"
			write_key_file(str(target), "sk-test-1234")
			self.assertEqual(target.read_text(), "sk-test-1234")

	def test_writes_with_mode_0600(self):
		with tempfile.TemporaryDirectory() as tmp:
			target = Path(tmp) / "llm.key"
			write_key_file(str(target), "sk-test")
			mode = target.stat().st_mode & 0o777
			self.assertEqual(mode, 0o600)

	def test_creates_parent_dir_if_missing(self):
		with tempfile.TemporaryDirectory() as tmp:
			target = Path(tmp) / "nested" / "dirs" / "llm.key"
			write_key_file(str(target), "k")
			self.assertTrue(target.exists())

	def test_overwrites_existing_file(self):
		with tempfile.TemporaryDirectory() as tmp:
			target = Path(tmp) / "llm.key"
			target.write_text("old")
			write_key_file(str(target), "new")
			self.assertEqual(target.read_text(), "new")


def _fake_recv_sequence(*frames):
	"""Build a side_effect for ws.recv that yields each frame in order then raises."""
	seq = list(frames)

	def _next(*args, **kwargs):
		if not seq:
			raise RuntimeError("ws.recv called more times than expected")
		return seq.pop(0)

	return _next


class TestReloadSecrets(FrappeTestCase):
	def _patched_create_connection(self):
		# Patches websocket.create_connection within the openclaw_push module
		return patch("jarvis.openclaw_push.create_connection")

	def test_sends_connect_then_reload_and_succeeds(self):
		sent = []
		ws = MagicMock()
		ws.send.side_effect = lambda payload: sent.append(json.loads(payload))

		# Plan responses: connect res ok, then reload res ok
		ws.recv.side_effect = _fake_recv_sequence(
			json.dumps({"type": "event", "name": "connect.challenge", "nonce": "abc"}),  # ignored
			json.dumps({"type": "res", "id": "PLACEHOLDER_CONNECT", "ok": True, "payload": {}}),
			json.dumps({"type": "res", "id": "PLACEHOLDER_RELOAD", "ok": True, "payload": {"ok": True, "warningCount": 0}}),
		)

		# The implementation generates UUIDs we don't know up front. After send is called,
		# patch the recv stream to use the actual ids in order.
		def _patch_recv_ids():
			# First two frames sent are connect + reload; pull their ids
			if len(sent) >= 1:
				ws.recv.side_effect = _fake_recv_sequence(
					json.dumps({"type": "event", "name": "connect.challenge"}),
					json.dumps({"type": "res", "id": sent[0]["id"], "ok": True}),
					json.dumps({"type": "res", "id": "TBD-RELOAD", "ok": True, "payload": {"ok": True}}),
				)

		# Easier approach: just match any frame with type=res to advance — but the
		# implementation should match by id. We'll let it work with id matching by
		# having the recv side_effect echo the most-recently-sent id back.

		# Reset: just use a stateful side_effect that responds to the latest sent id.
		ws.send.reset_mock()
		ws.send.side_effect = lambda payload: sent.append(json.loads(payload))
		responses = []

		def _recv_side_effect(*args, **kwargs):
			# If unread, deliver next event/res; we keep two "res" frames queued
			# keyed by the order of sends
			if not responses:
				# First time recv is called, build the queue based on what's been sent
				if len(sent) >= 1:
					responses.append(json.dumps({"type": "event", "name": "noise"}))
					responses.append(json.dumps({"type": "res", "id": sent[0]["id"], "ok": True, "payload": {}}))
				if len(sent) >= 2:
					responses.append(json.dumps({"type": "res", "id": sent[1]["id"], "ok": True, "payload": {"ok": True}}))
			return responses.pop(0) if responses else (_ for _ in ()).throw(RuntimeError("no more responses"))

		ws.recv.side_effect = _recv_side_effect

		with self._patched_create_connection() as mock_create:
			mock_create.return_value = ws
			reload_secrets("ws://127.0.0.1:18789", "test-token")

		# Verify the wire frames
		self.assertEqual(len(sent), 2, f"expected 2 frames sent, got {len(sent)}: {sent}")

		connect_frame = sent[0]
		self.assertEqual(connect_frame["type"], "req")
		self.assertEqual(connect_frame["method"], "connect")
		self.assertEqual(connect_frame["params"]["role"], "operator")
		self.assertEqual(connect_frame["params"]["auth"]["token"], "test-token")
		self.assertEqual(connect_frame["params"]["minProtocol"], 3)
		self.assertEqual(connect_frame["params"]["maxProtocol"], 4)
		client = connect_frame["params"]["client"]
		self.assertEqual(client["id"], "gateway-client")
		self.assertEqual(client["mode"], "backend")
		self.assertIn("version", client)
		self.assertIn("platform", client)

		reload_frame = sent[1]
		self.assertEqual(reload_frame["method"], "secrets.reload")
		self.assertEqual(reload_frame["params"], {})

		ws.close.assert_called_once()

	def test_connect_failure_raises_unreachable(self):
		ws = MagicMock()
		sent = []
		ws.send.side_effect = lambda payload: sent.append(json.loads(payload))

		responses = []

		def _recv_side_effect(*args, **kwargs):
			if not responses and len(sent) >= 1:
				responses.append(json.dumps({"type": "res", "id": sent[0]["id"], "ok": False, "error": {"code": "UNAUTHORIZED", "message": "bad token"}}))
			return responses.pop(0)

		ws.recv.side_effect = _recv_side_effect

		with self._patched_create_connection() as mock_create:
			mock_create.return_value = ws
			with self.assertRaises(OpenclawUnreachableError):
				reload_secrets("ws://127.0.0.1:18789", "wrong-token")

	def test_reload_failure_raises_reload_failed(self):
		ws = MagicMock()
		sent = []
		ws.send.side_effect = lambda payload: sent.append(json.loads(payload))

		responses = []

		def _recv_side_effect(*args, **kwargs):
			if not responses:
				if len(sent) >= 1:
					responses.append(json.dumps({"type": "res", "id": sent[0]["id"], "ok": True}))
				if len(sent) >= 2:
					responses.append(json.dumps({"type": "res", "id": sent[1]["id"], "ok": False, "error": {"code": "UNAVAILABLE", "message": "reload broken"}}))
			return responses.pop(0)

		ws.recv.side_effect = _recv_side_effect

		with self._patched_create_connection() as mock_create:
			mock_create.return_value = ws
			with self.assertRaises(OpenclawReloadFailedError):
				reload_secrets("ws://127.0.0.1:18789", "test-token")

	def test_connection_error_raises_unreachable(self):
		with self._patched_create_connection() as mock_create:
			import websocket as _ws_module

			mock_create.side_effect = _ws_module.WebSocketException("connection refused")
			with self.assertRaises(OpenclawUnreachableError):
				reload_secrets("ws://127.0.0.1:18789", "token")


class TestRestartGateway(FrappeTestCase):
	def test_invokes_docker_compose_restart_then_polls_health(self):
		with patch("jarvis.openclaw_push.subprocess.run") as mock_run, patch("jarvis.openclaw_push.urllib.request.urlopen") as mock_open:
			mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
			# Health check returns 200
			mock_open.return_value.__enter__ = MagicMock(return_value=MagicMock(status=200))
			mock_open.return_value.__exit__ = MagicMock(return_value=False)

			restart_gateway("/path/to/compose")

			args, _ = mock_run.call_args
			cmd = args[0]
			self.assertEqual(cmd[0], "docker")
			self.assertEqual(cmd[1], "compose")
			self.assertIn("-f", cmd)
			self.assertIn("/path/to/compose/docker-compose.yml", cmd)
			self.assertIn("restart", cmd)
			self.assertIn("openclaw-gateway", cmd)

	def test_docker_failure_raises_restart_failed(self):
		with patch("jarvis.openclaw_push.subprocess.run") as mock_run:
			mock_run.side_effect = subprocess.CalledProcessError(1, "docker compose")
			with self.assertRaises(OpenclawRestartFailedError):
				restart_gateway("/path/to/compose")
