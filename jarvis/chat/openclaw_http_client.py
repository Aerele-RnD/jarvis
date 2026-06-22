"""HTTP chat client for self-hosted openclaw.

Self-hosted mode (deployment_mode == "Self-Hosted") talks to the user's own
openclaw over its OpenAI-compatible HTTP surface:

    POST {base}/v1/chat/completions   Authorization: Bearer <gateway_token>

openclaw grants full operator scope to shared-secret bearer auth on this
surface, so there is NO Ed25519 device-pairing (unlike the WS path, which
strips operator.write from non-loopback token-only clients). model="openclaw"
addresses the agent; the user's openclaw uses whatever LLM they configured.

`stream_agent_turn` yields the same parsed-event dicts that
`jarvis.chat.events.parse_event` produces for the WS path, so `worker.py`
branches on deployment_mode and the per-event handling is unchanged. In
particular an ``assistant`` event's ``text`` is the *cumulative* reply so far
(the worker overwrites the row + republishes on each one), so the streaming
path accumulates and yields the running total per chunk.

Transport is configurable via Jarvis Settings.selfhost_stream:
  - stream=True  (default): open an SSE response and yield one assistant event
    per token chunk -> the UI animates the reply token-by-token.
  - stream=False: one-shot request, single cumulative assistant event. Use when
    a proxy in front of the user's openclaw buffers SSE.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import requests

from jarvis.exceptions import OpenclawUnreachableError

_CHAT_TIMEOUT = 180


def stream_agent_turn(
    base_url: str, token: str, message: str, *,
    model: str | None = None, stream: bool = True,
) -> Iterator[dict[str, Any]]:
    """POST one chat turn to a self-hosted openclaw; yield worker-shaped events.

    With ``stream=True`` yields a ``{"kind":"assistant","text":<cumulative>,
    "delta":<chunk>}`` per token chunk then ``{"kind":"lifecycle","phase":
    "end"}``. With ``stream=False`` yields a single cumulative assistant event
    then lifecycle end - same contract, no incremental rendering.

    Raises OpenclawUnreachableError on network/auth/protocol failure *before any
    content arrives* (mapped by worker.py to an errored row), mirroring the WS
    client. A mid-stream drop *after* partial content ends the turn gracefully
    with whatever was received.
    """
    url = (base_url or "").rstrip("/") + "/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {(token or '').strip()}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model or "openclaw",
        "messages": [{"role": "user", "content": message}],
        "stream": bool(stream),
    }
    if stream:
        yield from _streamed(url, headers, body)
    else:
        yield from _one_shot(url, headers, body)


def _post(url: str, headers: dict, body: dict, *, stream: bool):
    try:
        return requests.post(
            url, headers=headers, json=body, timeout=_CHAT_TIMEOUT, stream=stream,
        )
    except requests.RequestException as e:
        raise OpenclawUnreachableError(
            f"self-hosted openclaw request failed: {e}"
        ) from e


def _check_status(r) -> None:
    if r.status_code in (401, 403):
        raise OpenclawUnreachableError(
            f"self-hosted openclaw rejected the token (HTTP {r.status_code}) - "
            "re-check the gateway token in Deployment settings."
        )
    if r.status_code != 200:
        snippet = (r.text or "")[:200]
        raise OpenclawUnreachableError(
            f"self-hosted openclaw returned HTTP {r.status_code}: {snippet}"
        )


def _empty_reply_error() -> OpenclawUnreachableError:
    return OpenclawUnreachableError(
        "self-hosted openclaw returned an empty reply (is an LLM configured "
        "and reachable on your openclaw?)"
    )


def _one_shot(url: str, headers: dict, body: dict) -> Iterator[dict[str, Any]]:
    r = _post(url, headers, body, stream=False)
    _check_status(r)
    try:
        payload = r.json()
        content = ((payload.get("choices") or [{}])[0]
                   .get("message", {}).get("content") or "")
    except (ValueError, AttributeError, IndexError) as e:
        raise OpenclawUnreachableError(
            f"self-hosted openclaw returned an unparseable response: {e}"
        ) from e
    content = (content or "").strip()
    if not content:
        raise _empty_reply_error()
    yield {"kind": "assistant", "text": content, "delta": content}
    yield {"kind": "lifecycle", "phase": "end"}


def _streamed(url: str, headers: dict, body: dict) -> Iterator[dict[str, Any]]:
    r = _post(url, headers, body, stream=True)
    _check_status(r)
    acc = ""
    try:
        for raw in r.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = raw.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue  # keep-alive / non-JSON line
            try:
                delta = (chunk.get("choices") or [{}])[0].get("delta", {}) or {}
                piece = delta.get("content") or ""
            except (AttributeError, IndexError):
                piece = ""
            if not piece:
                continue  # role-only opener, tool deltas, etc.
            acc += piece
            yield {"kind": "assistant", "text": acc, "delta": piece}
    except requests.RequestException as e:
        # Connection dropped mid-stream. Keep partial content if we have any;
        # otherwise surface it as unreachable so the row is marked errored.
        if not acc.strip():
            raise OpenclawUnreachableError(
                f"self-hosted openclaw stream failed: {e}"
            ) from e
    finally:
        r.close()

    if not acc.strip():
        raise _empty_reply_error()
    yield {"kind": "lifecycle", "phase": "end"}
