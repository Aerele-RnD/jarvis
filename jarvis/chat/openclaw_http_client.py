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
branches on deployment_mode and the per-event handling is unchanged.

v1: non-streaming (one-shot) for reliability - the worker still renders the
full answer. Token-by-token SSE is a later polish.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import requests

from jarvis.exceptions import OpenclawUnreachableError

_CHAT_TIMEOUT = 180


def stream_agent_turn(
    base_url: str, token: str, message: str, *, model: str | None = None,
) -> Iterator[dict[str, Any]]:
    """POST one chat turn to a self-hosted openclaw; yield worker-shaped events.

    Yields one ``{"kind": "assistant", "text": <full>, "delta": <full>}`` then
    ``{"kind": "lifecycle", "phase": "end"}`` on success. Raises
    OpenclawUnreachableError on network/auth/protocol failure (mapped by
    worker.py to an errored assistant row), mirroring the WS client's contract.
    """
    url = (base_url or "").rstrip("/") + "/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {(token or '').strip()}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model or "openclaw",
        "messages": [{"role": "user", "content": message}],
        "stream": False,
    }

    try:
        r = requests.post(url, headers=headers, json=body, timeout=_CHAT_TIMEOUT)
    except requests.RequestException as e:
        raise OpenclawUnreachableError(
            f"self-hosted openclaw request failed: {e}"
        ) from e

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
        raise OpenclawUnreachableError(
            "self-hosted openclaw returned an empty reply (is an LLM configured "
            "and reachable on your openclaw?)"
        )

    yield {"kind": "assistant", "text": content, "delta": content}
    yield {"kind": "lifecycle", "phase": "end"}
