"""Openclaw event parsing + realtime publish wrapper.

openclaw emits WebSocket events with shapes like:
  stream=lifecycle  data={phase: start|end|error, ...}
  stream=item       data={kind: tool, phase: start|end, name, toolCallId, status}
  stream=assistant  data={text: <cumulative>, delta: <incremental>}

This module normalizes those into a flat dict the worker can act on, and
provides a thin wrapper around frappe.publish_realtime so the channel name
("jarvis:event") lives in one place.
"""

from __future__ import annotations

from typing import Any

import frappe

CHANNEL = "jarvis:event"


def parse_event(payload: dict[str, Any]) -> dict[str, Any] | None:
	"""Normalize an openclaw WS frame to a flat dict, or return None to drop it."""
	stream = payload.get("stream")
	data = payload.get("data")
	if not isinstance(data, dict):
		data = {}

	if stream == "lifecycle":
		out: dict[str, Any] = {"kind": "lifecycle", "phase": data.get("phase")}
		if data.get("error"):
			out["error"] = data["error"]
		return out

	if stream == "item":
		if data.get("kind") != "tool":
			return None
		out = {
			"kind": "tool",
			"phase": data.get("phase"),
			"tool_name": data.get("name"),
			"tool_call_id": data.get("toolCallId"),
		}
		if data.get("status"):
			out["status"] = data["status"]
		return out

	if stream == "assistant":
		return {
			"kind": "assistant",
			"text": data.get("text", ""),
			"delta": data.get("delta", ""),
		}

	return None


def publish_to_user(user: str, payload: dict[str, Any]) -> None:
	"""Broadcast a payload to a single user's socketio channel."""
	frappe.publish_realtime(CHANNEL, payload, user=user)
