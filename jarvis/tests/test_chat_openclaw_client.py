"""Tests for the openclaw subprocess client.

The client wraps `docker compose exec node -e <script>` to drive an
openclaw WS connection from inside the container (where loopback grants
full operator scopes). These tests mock subprocess.Popen and verify the
JSON-line protocol between Python and the Node script.
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.openclaw_client import OpenclawSession
from jarvis.exceptions import OpenclawUnreachableError


def _settings_with_compose_dir():
	"""Ensure Jarvis Settings has openclaw_compose_dir set for connect()."""
	s = frappe.get_single("Jarvis Settings")
	if not s.openclaw_compose_dir:
		s.db_set("openclaw_compose_dir", "/tmp/fake-openclaw")
		frappe.db.commit()


class _FakeStdout:
	"""Provides line-by-line readline() from a queue of events."""

	def __init__(self, lines: list[str]):
		self._iter = iter(lines)
		self.closed = False

	def readline(self) -> str:
		try:
			return next(self._iter)
		except StopIteration:
			return ""


def _make_proc(stdout_lines: list[str]) -> MagicMock:
	proc = MagicMock(spec=subprocess.Popen)
	proc.stdout = _FakeStdout(stdout_lines)
	proc.stdin = MagicMock()
	proc.stdin.closed = False
	proc.stderr = MagicMock()
	return proc


def _make_select_always_ready(*args, **kwargs):
	"""Stub for select.select that says stdout is always readable."""
	return ([args[0][0]] if args[0] else []), [], []


class TestConnect(FrappeTestCase):
	def setUp(self):
		_settings_with_compose_dir()

	def test_connect_success(self):
		proc = _make_proc([json.dumps({"type": "connect", "ok": True}) + "\n"])
		with patch("subprocess.Popen", return_value=proc):
			with patch("select.select", side_effect=_make_select_always_ready):
				sess = OpenclawSession.connect("ws://ignored", "tok-123")
		self.assertIs(sess._proc, proc)

	def test_connect_failure_raises(self):
		proc = _make_proc([
			json.dumps({"type": "connect", "ok": False, "error": "bad token"}) + "\n",
		])
		with patch("subprocess.Popen", return_value=proc):
			with patch("select.select", side_effect=_make_select_always_ready):
				with self.assertRaises(OpenclawUnreachableError):
					OpenclawSession.connect("ws://ignored", "tok-123")

	def test_connect_docker_missing_raises(self):
		with patch("subprocess.Popen", side_effect=FileNotFoundError("no docker")):
			with self.assertRaises(OpenclawUnreachableError):
				OpenclawSession.connect("ws://ignored", "tok-123")


class TestCreateSession(FrappeTestCase):
	def setUp(self):
		_settings_with_compose_dir()

	def test_create_session_returns_key(self):
		proc = _make_proc([
			json.dumps({"type": "connect", "ok": True}) + "\n",
			json.dumps({"type": "create", "ok": True, "key": "agent:main:abc"}) + "\n",
		])
		with patch("subprocess.Popen", return_value=proc):
			with patch("select.select", side_effect=_make_select_always_ready):
				sess = OpenclawSession.connect("ws://ignored", "tok-123")
				key = sess.create_session(label="test")
		self.assertEqual(key, "agent:main:abc")
		# Verify create_session command was written to stdin
		written = [c.args[0] for c in proc.stdin.write.call_args_list]
		cmds = [json.loads(w.strip()) for w in written if w.strip()]
		create_cmds = [c for c in cmds if c.get("cmd") == "create_session"]
		self.assertEqual(len(create_cmds), 1)
		self.assertEqual(create_cmds[0]["label"], "test")

	def test_create_session_rejected(self):
		proc = _make_proc([
			json.dumps({"type": "connect", "ok": True}) + "\n",
			json.dumps({"type": "create", "ok": False, "error": "denied"}) + "\n",
		])
		with patch("subprocess.Popen", return_value=proc):
			with patch("select.select", side_effect=_make_select_always_ready):
				sess = OpenclawSession.connect("ws://ignored", "tok-123")
				with self.assertRaises(OpenclawUnreachableError):
					sess.create_session()


class TestStreamAgentTurn(FrappeTestCase):
	def setUp(self):
		_settings_with_compose_dir()

	def test_streams_and_terminates_on_runDone(self):
		proc = _make_proc([
			json.dumps({"type": "connect", "ok": True}) + "\n",
			json.dumps({"type": "agentAck", "runId": "r1"}) + "\n",
			json.dumps({"type": "event", "payload": {
				"runId": "r1", "stream": "lifecycle", "data": {"phase": "start"}
			}}) + "\n",
			json.dumps({"type": "event", "payload": {
				"runId": "r1", "stream": "assistant",
				"data": {"text": "Hi", "delta": "Hi"}
			}}) + "\n",
			json.dumps({"type": "event", "payload": {
				"runId": "r1", "stream": "lifecycle", "data": {"phase": "end"}
			}}) + "\n",
			json.dumps({"type": "runDone"}) + "\n",
		])
		with patch("subprocess.Popen", return_value=proc):
			with patch("select.select", side_effect=_make_select_always_ready):
				sess = OpenclawSession.connect("ws://ignored", "tok-123")
				events = list(sess.stream_agent_turn("agent:x", "hi", "idem"))
		kinds = [e["kind"] for e in events]
		self.assertEqual(kinds, ["lifecycle", "assistant", "lifecycle"])

	def test_run_error_raises(self):
		proc = _make_proc([
			json.dumps({"type": "connect", "ok": True}) + "\n",
			json.dumps({"type": "runErr", "error": "agent failed"}) + "\n",
		])
		with patch("subprocess.Popen", return_value=proc):
			with patch("select.select", side_effect=_make_select_always_ready):
				sess = OpenclawSession.connect("ws://ignored", "tok-123")
				with self.assertRaises(OpenclawUnreachableError):
					list(sess.stream_agent_turn("agent:x", "hi", "idem"))


class TestClose(FrappeTestCase):
	def setUp(self):
		_settings_with_compose_dir()

	def test_close_sends_close_cmd_and_terminates(self):
		proc = _make_proc([json.dumps({"type": "connect", "ok": True}) + "\n"])
		with patch("subprocess.Popen", return_value=proc):
			with patch("select.select", side_effect=_make_select_always_ready):
				sess = OpenclawSession.connect("ws://ignored", "tok-123")
				sess.close()
		# A close command was written
		written = [c.args[0] for c in proc.stdin.write.call_args_list]
		cmds = [json.loads(w.strip()) for w in written if w.strip()]
		self.assertTrue(any(c.get("cmd") == "close" for c in cmds))
		proc.terminate.assert_called_once()
