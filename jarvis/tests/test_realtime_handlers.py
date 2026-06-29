"""Tests for jarvis.realtime.handlers (Path B chat subscriber).

The module's job is to spawn a gevent greenlet at import time iff
``socketio_backend == "python"`` is set in common_site_config.json. The
greenlet subscribes to ``jarvis:chat:send:<site>`` on Redis pub/sub and
dispatches each message to ``jarvis.chat.turn_handler.handle_chat_send``
in its own greenlet (so many concurrent turns share one realtime process).

Tests cover:
- spawning is gated correctly on the backend config
- maybe_start_chat_subscriber is idempotent (a second call is a no-op)
- the per-message dispatch decodes JSON, calls the shared handler, and
  swallows exceptions instead of taking down the loop
- the channel name format matches dispatch.publish_chat_send
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.realtime import handlers


class _FakeConf:
	"""Minimal stand-in for frappe.conf in tests. The handler only reads
	via ``frappe.conf.get(key)``, so we just need a .get implementation."""

	def __init__(self, mapping):
		self._d = dict(mapping)

	def get(self, key, default=None):
		return self._d.get(key, default)


class TestMaybeStartChatSubscriber(FrappeTestCase):
	"""maybe_start_chat_subscriber is the gate; every other behaviour
	flows from whether it spawns or not."""

	def setUp(self):
		# Each test exercises a fresh start state.
		handlers._SUBSCRIBER_SPAWNED = False

	def test_no_spawn_when_socketio_backend_unset(self):
		with patch.object(frappe, "conf", _FakeConf({})), \
		     patch("gevent.spawn") as spawn:
			spawned = handlers.maybe_start_chat_subscriber()
		self.assertFalse(spawned)
		spawn.assert_not_called()
		self.assertFalse(handlers._SUBSCRIBER_SPAWNED)

	def test_no_spawn_when_socketio_backend_is_node(self):
		with patch.object(frappe, "conf", _FakeConf({"socketio_backend": "node"})), \
		     patch("gevent.spawn") as spawn:
			spawned = handlers.maybe_start_chat_subscriber()
		self.assertFalse(spawned)
		spawn.assert_not_called()
		self.assertFalse(handlers._SUBSCRIBER_SPAWNED)

	def test_spawn_when_socketio_backend_is_python(self):
		with patch.object(frappe, "conf", _FakeConf({"socketio_backend": "python"})), \
		     patch("gevent.spawn") as spawn:
			spawned = handlers.maybe_start_chat_subscriber()
		self.assertTrue(spawned)
		spawn.assert_called_once_with(handlers._watchdog_loop)
		self.assertTrue(handlers._SUBSCRIBER_SPAWNED)

	def test_python_backend_match_is_case_insensitive(self):
		"""Operators may type 'Python' or 'PYTHON' in the config; the
		gate normalises before comparing."""
		with patch.object(frappe, "conf", _FakeConf({"socketio_backend": "PYTHON"})), \
		     patch("gevent.spawn") as spawn:
			spawned = handlers.maybe_start_chat_subscriber()
		self.assertTrue(spawned)
		spawn.assert_called_once()

	def test_second_call_is_noop(self):
		"""Idempotent: once the watchdog is running, a second call must
		not spawn a duplicate greenlet (which would double-subscribe to
		Redis and cause every chat turn to run twice)."""
		with patch.object(frappe, "conf", _FakeConf({"socketio_backend": "python"})), \
		     patch("gevent.spawn") as spawn:
			first = handlers.maybe_start_chat_subscriber()
			second = handlers.maybe_start_chat_subscriber()
		self.assertTrue(first)
		self.assertFalse(second)
		spawn.assert_called_once()


class TestRunOne(FrappeTestCase):
	"""_run_one is the per-message dispatcher: it decodes the JSON
	payload, calls handle_chat_send, and swallows any exception so one
	bad turn doesn't kill the loop."""

	def test_dispatches_decoded_payload_to_handle_chat_send(self):
		payload = {"conversation_id": "c1", "message_id": "m1", "run_id": "r1"}
		raw = json.dumps(payload).encode("utf-8")
		with patch("jarvis.chat.turn_handler.handle_chat_send") as mock_handle:
			handlers._run_one(raw)
		mock_handle.assert_called_once_with(payload)

	def test_accepts_str_payload_as_well_as_bytes(self):
		"""Redis usually returns bytes but some configurations decode
		strings; accept both."""
		payload = {"conversation_id": "c2", "message_id": "m2", "run_id": "r2"}
		raw = json.dumps(payload)
		with patch("jarvis.chat.turn_handler.handle_chat_send") as mock_handle:
			handlers._run_one(raw)
		mock_handle.assert_called_once_with(payload)

	def test_swallows_handler_exception(self):
		"""A crashed turn must not propagate out of _run_one - else the
		watchdog would restart the loop and we'd lose pending messages.
		The exception is logged via frappe.log_error instead."""
		payload = {"conversation_id": "c", "message_id": "m", "run_id": "r"}
		raw = json.dumps(payload).encode("utf-8")
		with patch("jarvis.chat.turn_handler.handle_chat_send",
		           side_effect=RuntimeError("boom")), \
		     patch("frappe.log_error") as mock_log:
			handlers._run_one(raw)  # must not raise
		mock_log.assert_called_once()

	def test_swallows_invalid_json(self):
		"""A malformed payload (corrupt publish, schema drift) must not
		take down the loop. Log and move on."""
		with patch("jarvis.chat.turn_handler.handle_chat_send") as mock_handle, \
		     patch("frappe.log_error") as mock_log:
			handlers._run_one(b"not-json")  # must not raise
		mock_handle.assert_not_called()
		mock_log.assert_called_once()

	def test_swallows_non_dict_payload(self):
		"""Defensive: a JSON value that isn't an object can't be a turn
		payload. Reject + log."""
		with patch("jarvis.chat.turn_handler.handle_chat_send") as mock_handle, \
		     patch("frappe.log_error") as mock_log:
			handlers._run_one(b'["not", "a", "dict"]')
		mock_handle.assert_not_called()
		mock_log.assert_called_once()


class TestChannelFormat(FrappeTestCase):
	"""The publisher (jarvis.chat.dispatch) and subscriber (this module)
	must agree on the channel name verbatim, else messages drop on the
	floor with no error. Pin the format here."""

	def test_subscriber_and_publisher_use_same_channel(self):
		from jarvis.chat import dispatch

		self.assertEqual(
			handlers._CHANNEL_TEMPLATE.format(site="site.example.com"),
			dispatch._channel("site.example.com"),
		)
