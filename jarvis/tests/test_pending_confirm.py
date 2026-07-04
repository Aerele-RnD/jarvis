"""Tests for jarvis.chat.pending_confirm - the cache-backed token store that
parks a pending mutating tool call until a human confirms it.

No gate wiring here (that is a later task) - just mint/peek/consume and the
args_hash used to bind a token to the exact call.
"""

import contextvars
import threading

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat import pending_confirm

CONV = "conv-1"
OWNER = "owner@example.invalid"
TOOL = "create_doc"
ARGS = {"doctype": "Task", "subject": "hello", "nested": {"b": 2, "a": 1}}
RUN_ID = "run-1"


class TestArgsHash(FrappeTestCase):
	def test_stable_across_key_ordering(self):
		a = {"x": 1, "y": 2, "nested": {"b": 2, "a": 1}}
		b = {"nested": {"a": 1, "b": 2}, "y": 2, "x": 1}
		self.assertEqual(
			pending_confirm.args_hash("some_tool", a),
			pending_confirm.args_hash("some_tool", b),
		)

	def test_differs_when_a_value_changes(self):
		a = {"x": 1}
		b = {"x": 2}
		self.assertNotEqual(
			pending_confirm.args_hash("some_tool", a),
			pending_confirm.args_hash("some_tool", b),
		)

	def test_differs_when_tool_changes(self):
		self.assertNotEqual(
			pending_confirm.args_hash("tool_a", ARGS),
			pending_confirm.args_hash("tool_b", ARGS),
		)


class TestMint(FrappeTestCase):
	def test_two_mints_are_distinct_tokens(self):
		t1 = pending_confirm.mint(
			conversation=CONV, owner=OWNER, tool=TOOL, args=ARGS, run_id=RUN_ID,
		)
		t2 = pending_confirm.mint(
			conversation=CONV, owner=OWNER, tool=TOOL, args=ARGS, run_id=RUN_ID,
		)
		self.assertNotEqual(t1, t2)
		# Both are independently live.
		self.assertIsNotNone(pending_confirm.peek(t1))
		self.assertIsNotNone(pending_confirm.peek(t2))


class TestPeek(FrappeTestCase):
	def test_unknown_token_is_none(self):
		self.assertIsNone(pending_confirm.peek("does-not-exist"))

	def test_live_token_returns_full_record(self):
		token = pending_confirm.mint(
			conversation=CONV, owner=OWNER, tool=TOOL, args=ARGS, run_id=RUN_ID,
		)
		record = pending_confirm.peek(token)
		self.assertIsNotNone(record)
		self.assertEqual(record["conversation"], CONV)
		self.assertEqual(record["owner"], OWNER)
		self.assertEqual(record["tool"], TOOL)
		self.assertEqual(record["args"], ARGS)
		self.assertEqual(record["run_id"], RUN_ID)
		self.assertEqual(record["args_hash"], pending_confirm.args_hash(TOOL, ARGS))

	def test_expired_token_is_none(self):
		"""Simulate expiry directly (waiting out the real 900s TTL is not
		practical in a test): mint, then drop the underlying cache key, then
		peek must report it gone same as a token that never existed."""
		token = pending_confirm.mint(
			conversation=CONV, owner=OWNER, tool=TOOL, args=ARGS, run_id=RUN_ID,
		)
		frappe.cache().delete_value(pending_confirm._PREFIX + token)
		self.assertIsNone(pending_confirm.peek(token))


class TestConsume(FrappeTestCase):
	def _mint(self):
		return pending_confirm.mint(
			conversation=CONV, owner=OWNER, tool=TOOL, args=ARGS, run_id=RUN_ID,
		)

	def test_happy_path_returns_record_and_is_single_use(self):
		token = self._mint()
		record = pending_confirm.consume(token, owner=OWNER, conversation=CONV)
		self.assertIsNotNone(record)
		self.assertEqual(record["tool"], TOOL)
		self.assertEqual(record["args"], ARGS)
		# Second consume of the same token: already burned.
		self.assertIsNone(pending_confirm.consume(token, owner=OWNER, conversation=CONV))
		# And it is really gone, not just "consumed once but still peekable".
		self.assertIsNone(pending_confirm.peek(token))

	def test_wrong_owner_returns_none_and_does_not_burn_token(self):
		token = self._mint()
		self.assertIsNone(
			pending_confirm.consume(token, owner="someone-else@example.invalid", conversation=CONV)
		)
		# Token still lives - a later correct consume still works.
		record = pending_confirm.consume(token, owner=OWNER, conversation=CONV)
		self.assertIsNotNone(record)

	def test_wrong_conversation_returns_none_and_does_not_burn_token(self):
		token = self._mint()
		self.assertIsNone(
			pending_confirm.consume(token, owner=OWNER, conversation="conv-other")
		)
		record = pending_confirm.consume(token, owner=OWNER, conversation=CONV)
		self.assertIsNotNone(record)

	def test_unknown_token_returns_none(self):
		self.assertIsNone(
			pending_confirm.consume("does-not-exist", owner=OWNER, conversation=CONV)
		)

	def test_expired_token_returns_none(self):
		token = self._mint()
		frappe.cache().delete_value(pending_confirm._PREFIX + token)
		self.assertIsNone(pending_confirm.consume(token, owner=OWNER, conversation=CONV))

	def test_concurrent_consumes_exactly_one_wins(self):
		"""Two threads race to consume the same legitimate token. Redis GETDEL
		is atomic server-side, so exactly one of the two concurrent consumes
		must get the record back; the other must get None - never both, never
		neither."""
		token = self._mint()
		results = [None, None]

		def _consume(i):
			results[i] = pending_confirm.consume(token, owner=OWNER, conversation=CONV)

		# threading.Thread does not inherit frappe.local (a contextvar-backed
		# thread local); copy_context().run propagates it into each thread so
		# frappe.cache() works there too.
		ctx1 = contextvars.copy_context()
		ctx2 = contextvars.copy_context()
		t1 = threading.Thread(target=ctx1.run, args=(_consume, 0))
		t2 = threading.Thread(target=ctx2.run, args=(_consume, 1))
		t1.start()
		t2.start()
		t1.join(timeout=5)
		t2.join(timeout=5)

		winners = [r for r in results if r is not None]
		self.assertEqual(len(winners), 1)
		self.assertIsNone(pending_confirm.peek(token))
