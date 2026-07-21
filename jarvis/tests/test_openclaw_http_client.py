"""Unit tests for jarvis.chat.openclaw_http_client - the self-hosted openclaw
HTTP chat client (one-shot + SSE streaming). HTTP is mocked; no real openclaw.

The client yields the same worker-shaped events the WS path produces: zero or
more ``{"kind": "assistant", "text": <cumulative>, "delta": <chunk>}`` followed
by a terminal ``{"kind": "lifecycle", "phase": "end"}``. ``text`` is the running
total (the worker overwrites + republishes the row each time).

Run: bench --site <site> run-tests --module jarvis.tests.test_openclaw_http_client
"""

import json
import unittest
from contextlib import contextmanager
from unittest import mock

from jarvis.chat import openclaw_http_client as hc
from jarvis.exceptions import OpenclawUnreachableError


class _RX(Exception):
	"""Stand-in for requests.RequestException under the mocked requests module."""


@contextmanager
def _mock_requests():
	with mock.patch.object(hc, "requests") as rq:
		# The client's `except requests.RequestException` clauses need a real
		# exception class to catch (a bare Mock attribute isn't catchable).
		rq.RequestException = _RX
		yield rq


def _json_resp(status=200, *, content=None, payload=None, text=""):
	"""Non-streaming response: r.json() -> ``payload`` (or a choices/message
	envelope wrapping ``content``)."""
	m = mock.Mock()
	m.status_code = status
	m.text = text
	m.close = mock.Mock()
	if payload is None and content is not None:
		payload = {"choices": [{"message": {"content": content}}]}
	m.json.return_value = payload if payload is not None else {}
	return m


def _sse_resp(lines, status=200, *, raise_at=None, text=""):
	"""Streaming response whose iter_lines() yields ``lines`` (raw decoded SSE
	strings). With ``raise_at`` set, raise a RequestException *before* yielding
	the line at that index (or after the last line when raise_at >= len)."""
	m = mock.Mock()
	m.status_code = status
	m.text = text
	m.close = mock.Mock()

	def _iter(decode_unicode=False):
		for i, ln in enumerate(lines):
			if raise_at is not None and i == raise_at:
				raise _RX("stream dropped")
			yield ln
		if raise_at is not None and raise_at >= len(lines):
			raise _RX("stream dropped")

	m.iter_lines.side_effect = _iter
	return m


def _data(content):
	"""An SSE content chunk line, as iter_lines() decodes it."""
	return "data: " + json.dumps({"choices": [{"delta": {"content": content}}]})


class TestOneShot(unittest.TestCase):
	def test_yields_assistant_then_lifecycle(self):
		with _mock_requests() as rq:
			rq.post.return_value = _json_resp(content="hello world")
			events = list(hc.stream_agent_turn("http://h:1", "tok", "hi", stream=False))
		self.assertEqual(
			events,
			[
				{"kind": "assistant", "text": "hello world", "delta": "hello world"},
				{"kind": "lifecycle", "phase": "end"},
			],
		)

	def test_request_shape(self):
		with _mock_requests() as rq:
			rq.post.return_value = _json_resp(content="x")
			list(hc.stream_agent_turn("http://h:1/", "  tok ", "hi", stream=False))
		args, kwargs = rq.post.call_args
		# Trailing slash on base_url is collapsed; token is trimmed into Bearer.
		self.assertEqual(args[0], "http://h:1/v1/chat/completions")
		self.assertFalse(kwargs["stream"])
		self.assertFalse(kwargs["json"]["stream"])
		self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok")
		self.assertEqual(kwargs["json"]["model"], "openclaw")
		self.assertEqual(kwargs["json"]["messages"][0]["content"], "hi")

	def test_empty_reply_raises(self):
		with _mock_requests() as rq:
			rq.post.return_value = _json_resp(content="   ")
			with self.assertRaises(OpenclawUnreachableError) as cm:
				list(hc.stream_agent_turn("http://h:1", "tok", "hi", stream=False))
		self.assertIn("empty reply", str(cm.exception))

	def test_unparseable_response_raises(self):
		with _mock_requests() as rq:
			r = _json_resp()
			r.json.side_effect = ValueError("not json")
			rq.post.return_value = r
			with self.assertRaises(OpenclawUnreachableError) as cm:
				list(hc.stream_agent_turn("http://h:1", "tok", "hi", stream=False))
		self.assertIn("unparseable", str(cm.exception))


class TestStatusMapping(unittest.TestCase):
	"""_check_status guards both transports; exercised here via one-shot."""

	def test_401_maps_to_rejected_token(self):
		with _mock_requests() as rq:
			rq.post.return_value = _json_resp(status=401)
			with self.assertRaises(OpenclawUnreachableError) as cm:
				list(hc.stream_agent_turn("http://h:1", "bad", "hi", stream=False))
		self.assertIn("rejected the token", str(cm.exception))

	def test_500_includes_body_snippet(self):
		with _mock_requests() as rq:
			rq.post.return_value = _json_resp(status=500, text="boom upstream")
			with self.assertRaises(OpenclawUnreachableError) as cm:
				list(hc.stream_agent_turn("http://h:1", "tok", "hi", stream=False))
		msg = str(cm.exception)
		self.assertIn("HTTP 500", msg)
		self.assertIn("boom upstream", msg)

	def test_network_error_before_response(self):
		with _mock_requests() as rq:
			rq.post.side_effect = _RX("connection refused")
			with self.assertRaises(OpenclawUnreachableError) as cm:
				list(hc.stream_agent_turn("http://h:1", "tok", "hi", stream=False))
		self.assertIn("request failed", str(cm.exception))


class TestStreamed(unittest.TestCase):
	def test_accumulates_cumulative_text_per_chunk(self):
		lines = [
			'data: {"choices":[{"delta":{"role":"assistant"}}]}',  # opener, no content
			_data("Hel"),
			_data("lo"),
			_data(" world"),
			"data: [DONE]",
		]
		with _mock_requests() as rq:
			rq.post.return_value = _sse_resp(lines)
			events = list(hc.stream_agent_turn("http://h:1", "tok", "hi", stream=True))
		self.assertEqual(
			events,
			[
				{"kind": "assistant", "text": "Hel", "delta": "Hel"},
				{"kind": "assistant", "text": "Hello", "delta": "lo"},
				{"kind": "assistant", "text": "Hello world", "delta": " world"},
				{"kind": "lifecycle", "phase": "end"},
			],
		)

	def test_request_shape_sets_stream_true(self):
		with _mock_requests() as rq:
			rq.post.return_value = _sse_resp([_data("hi"), "data: [DONE]"])
			list(hc.stream_agent_turn("http://h:1", "tok", "hi", stream=True))
		_, kwargs = rq.post.call_args
		self.assertTrue(kwargs["stream"])
		self.assertTrue(kwargs["json"]["stream"])

	def test_skips_keepalives_comments_and_role_openers(self):
		lines = [
			": keep-alive",  # comment, no data:
			"data: garbage-not-json",  # unparseable -> skip
			'data: {"choices":[{"delta":{"role":"assistant"}}]}',  # role only -> skip
			"",  # blank -> skip
			_data("Hi"),
			"data: [DONE]",
		]
		with _mock_requests() as rq:
			rq.post.return_value = _sse_resp(lines)
			events = list(hc.stream_agent_turn("http://h:1", "tok", "hi", stream=True))
		self.assertEqual(
			events,
			[
				{"kind": "assistant", "text": "Hi", "delta": "Hi"},
				{"kind": "lifecycle", "phase": "end"},
			],
		)

	def test_midstream_drop_keeps_partial_and_ends_gracefully(self):
		# Two content chunks arrive, then the connection drops. The turn ends
		# with the partial reply (no raise) and the response is closed.
		resp = _sse_resp([_data("Par"), _data("tial")], raise_at=2)
		with _mock_requests() as rq:
			rq.post.return_value = resp
			events = list(hc.stream_agent_turn("http://h:1", "tok", "hi", stream=True))
		self.assertEqual(
			events,
			[
				{"kind": "assistant", "text": "Par", "delta": "Par"},
				{"kind": "assistant", "text": "Partial", "delta": "tial"},
				{"kind": "lifecycle", "phase": "end"},
			],
		)
		resp.close.assert_called_once()

	def test_drop_before_any_content_raises(self):
		resp = _sse_resp([_data("never")], raise_at=0)
		with _mock_requests() as rq:
			rq.post.return_value = resp
			with self.assertRaises(OpenclawUnreachableError) as cm:
				list(hc.stream_agent_turn("http://h:1", "tok", "hi", stream=True))
		self.assertIn("stream failed", str(cm.exception))
		resp.close.assert_called_once()

	def test_empty_stream_raises(self):
		with _mock_requests() as rq:
			rq.post.return_value = _sse_resp(["data: [DONE]"])
			with self.assertRaises(OpenclawUnreachableError) as cm:
				list(hc.stream_agent_turn("http://h:1", "tok", "hi", stream=True))
		self.assertIn("empty reply", str(cm.exception))

	def test_401_on_stream_maps_to_rejected_token(self):
		with _mock_requests() as rq:
			rq.post.return_value = _sse_resp([], status=401)
			with self.assertRaises(OpenclawUnreachableError) as cm:
				list(hc.stream_agent_turn("http://h:1", "bad", "hi", stream=True))
		self.assertIn("rejected the token", str(cm.exception))


if __name__ == "__main__":
	unittest.main()
