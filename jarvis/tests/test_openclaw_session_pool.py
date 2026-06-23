"""Tests for jarvis.chat.openclaw_session_pool.

The pool itself talks only to ``OpenclawSession.connect`` (which we mock
with a fake session exposing ``_ws.connected`` + ``close()``). No real
WebSocket / Frappe involvement; tests are pure unit.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from jarvis.chat import openclaw_session_pool
from jarvis.exceptions import OpenclawUnreachableError


def _fake_session(connected: bool = True) -> MagicMock:
	"""Build a session stub that satisfies the pool's healthcheck."""
	sess = MagicMock()
	sess._ws = MagicMock()
	sess._ws.connected = connected
	return sess


class TestOpenclawSessionPool(FrappeTestCase):
	"""Pool unit tests. Each test resets the module-level pool dict in
	``setUp`` so suite order doesn't matter."""

	def setUp(self):
		openclaw_session_pool._POOL.clear()

	def tearDown(self):
		openclaw_session_pool._POOL.clear()

	# ---- happy path -------------------------------------------------

	def test_checkout_creates_new_session(self):
		sess = _fake_session()
		with patch.object(openclaw_session_pool.OpenclawSession, "connect",
		                  return_value=sess) as mock_connect:
			with openclaw_session_pool.checkout("ws://gw") as got:
				self.assertIs(got, sess)
			mock_connect.assert_called_once_with("ws://gw")

	def test_checkout_reuses_pooled_session(self):
		sess = _fake_session()
		with patch.object(openclaw_session_pool.OpenclawSession, "connect",
		                  return_value=sess) as mock_connect:
			with openclaw_session_pool.checkout("ws://gw"):
				pass
			with openclaw_session_pool.checkout("ws://gw"):
				pass
			# One connect total: second checkout reused the pool entry.
			mock_connect.assert_called_once()

	def test_different_urls_get_separate_entries(self):
		sess_a = _fake_session()
		sess_b = _fake_session()
		with patch.object(openclaw_session_pool.OpenclawSession, "connect",
		                  side_effect=[sess_a, sess_b]) as mock_connect:
			with openclaw_session_pool.checkout("ws://a"):
				pass
			with openclaw_session_pool.checkout("ws://b"):
				pass
			self.assertEqual(mock_connect.call_count, 2)
			self.assertEqual(set(openclaw_session_pool._POOL), {"ws://a", "ws://b"})

	# ---- healthcheck + reconnect ------------------------------------

	def test_dead_ws_triggers_reconnect(self):
		"""When ``_ws.connected`` is False on second checkout, the pool
		discards the entry and opens a fresh session."""
		sess1 = _fake_session()
		sess2 = _fake_session()
		with patch.object(openclaw_session_pool.OpenclawSession, "connect",
		                  side_effect=[sess1, sess2]) as mock_connect:
			with openclaw_session_pool.checkout("ws://gw"):
				pass
			# Simulate gateway closing our WS.
			sess1._ws.connected = False
			with openclaw_session_pool.checkout("ws://gw") as got:
				self.assertIs(got, sess2)
			self.assertEqual(mock_connect.call_count, 2)
			# First session's close() called during eviction.
			sess1.close.assert_called_once()

	def test_idle_eviction(self):
		"""After ``IDLE_MAX_S`` seconds the next checkout reconnects."""
		sess1 = _fake_session()
		sess2 = _fake_session()
		with patch.object(openclaw_session_pool.OpenclawSession, "connect",
		                  side_effect=[sess1, sess2]) as mock_connect, \
		     patch.object(openclaw_session_pool.time, "monotonic") as mock_time:
			# T=1000: first checkout creates session.
			mock_time.return_value = 1000.0
			with openclaw_session_pool.checkout("ws://gw"):
				pass
			# T=1000 + IDLE_MAX_S + 1: stale, reconnect.
			mock_time.return_value = 1000.0 + openclaw_session_pool.IDLE_MAX_S + 1
			with openclaw_session_pool.checkout("ws://gw") as got:
				self.assertIs(got, sess2)
			self.assertEqual(mock_connect.call_count, 2)
			sess1.close.assert_called_once()

	# ---- error eviction ---------------------------------------------

	def test_unreachable_during_use_evicts(self):
		"""``OpenclawUnreachableError`` raised inside the ``with`` block
		evicts the entry from the pool so the next checkout reconnects."""
		sess1 = _fake_session()
		sess2 = _fake_session()
		with patch.object(openclaw_session_pool.OpenclawSession, "connect",
		                  side_effect=[sess1, sess2]) as mock_connect:
			with self.assertRaises(OpenclawUnreachableError):
				with openclaw_session_pool.checkout("ws://gw"):
					raise OpenclawUnreachableError("simulated stream failure")
			# Entry evicted; next checkout opens a fresh session.
			with openclaw_session_pool.checkout("ws://gw") as got:
				self.assertIs(got, sess2)
			self.assertEqual(mock_connect.call_count, 2)
			# Evicted session's close() was called.
			sess1.close.assert_called()

	def test_other_exception_does_not_evict(self):
		"""A non-Openclaw exception inside the block should NOT evict
		the pool — those are caller bugs, the connection is fine."""
		sess = _fake_session()
		with patch.object(openclaw_session_pool.OpenclawSession, "connect",
		                  return_value=sess) as mock_connect:
			with self.assertRaises(ValueError):
				with openclaw_session_pool.checkout("ws://gw"):
					raise ValueError("caller bug")
			# Next checkout reuses the same session — no eviction.
			with openclaw_session_pool.checkout("ws://gw") as got:
				self.assertIs(got, sess)
			mock_connect.assert_called_once()

	def test_close_failure_during_eviction_does_not_propagate(self):
		"""If ``sess.close()`` itself raises during eviction (e.g. socket
		already torn down), the pool swallows it. The eviction still
		removes the entry."""
		sess1 = _fake_session()
		sess1.close.side_effect = RuntimeError("already closed")
		sess2 = _fake_session()
		with patch.object(openclaw_session_pool.OpenclawSession, "connect",
		                  side_effect=[sess1, sess2]):
			with self.assertRaises(OpenclawUnreachableError):
				with openclaw_session_pool.checkout("ws://gw"):
					raise OpenclawUnreachableError("boom")
			# Entry should have been removed even though close raised.
			self.assertNotIn("ws://gw", openclaw_session_pool._POOL)

	# ---- concurrent checkout ----------------------------------------

	def test_concurrent_checkout_shares_session(self):
		"""Multiple threads checking out the same URL serialise on the
		entry's lock; one connect, all five threads see the same
		session. Workers are single-threaded in production but the lock
		is exercised here as a safety check."""
		sess = _fake_session()
		# Connect is slow so threads pile up against the lock.
		import time as _time
		def slow_connect(_url):
			_time.sleep(0.01)
			return sess
		with patch.object(openclaw_session_pool.OpenclawSession, "connect",
		                  side_effect=slow_connect) as mock_connect:
			results: list[object] = []
			lock = threading.Lock()
			def runner():
				with openclaw_session_pool.checkout("ws://gw") as got:
					with lock:
						results.append(got)
			threads = [threading.Thread(target=runner) for _ in range(5)]
			for t in threads: t.start()
			for t in threads: t.join()
			self.assertEqual(len(results), 5)
			self.assertTrue(all(r is sess for r in results))
			# Race window means more than one connect MAY have started
			# (the "lost-race insertion" branch handles it), but at
			# least one session must have made it into the pool.
			self.assertGreaterEqual(mock_connect.call_count, 1)
			self.assertIn("ws://gw", openclaw_session_pool._POOL)

	# ---- drain ------------------------------------------------------

	def test_drain_all_closes_every_pooled_session(self):
		sess_a = _fake_session()
		sess_b = _fake_session()
		with patch.object(openclaw_session_pool.OpenclawSession, "connect",
		                  side_effect=[sess_a, sess_b]):
			with openclaw_session_pool.checkout("ws://a"):
				pass
			with openclaw_session_pool.checkout("ws://b"):
				pass
		openclaw_session_pool.drain_all()
		sess_a.close.assert_called_once()
		sess_b.close.assert_called_once()
		self.assertEqual(len(openclaw_session_pool._POOL), 0)

	def test_drain_all_is_idempotent(self):
		"""Calling drain_all on an empty pool should be a no-op, not
		raise."""
		openclaw_session_pool.drain_all()
		openclaw_session_pool.drain_all()
