"""RQ job: stream one agent turn from openclaw to DB + realtime.

Spawned by jarvis.chat.api.send_message via frappe.enqueue. Holds a Python
WebSocket connection to the openclaw gateway for the duration of the turn
(typically 10-30s); the Frappe request handler returns in ~10ms and the
worker streams events while the browser sees them token-by-token via
socketio.
"""

from __future__ import annotations

import frappe

from jarvis.chat.events import publish_to_user
from jarvis.chat.openclaw_client import OpenclawSession
from jarvis.exceptions import OpenclawUnreachableError

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"


def run_agent_turn(conversation_id: str, message_id: str, run_id: str) -> None:
	"""Drive one agent turn end to end. Called by RQ; not whitelisted."""
	conv = frappe.get_doc(CONV, conversation_id)
	user = conv.owner

	# Create the assistant placeholder row up-front so the browser has a
	# stable name to attach realtime events to.
	assistant_msg = _create_assistant_placeholder(conv)

	publish_to_user(user, {
		"kind": "run:start",
		"conversation_id": conversation_id,
		"message_id": assistant_msg.name,
		"run_id": run_id,
	})

	settings = frappe.get_single("Jarvis Settings")
	gateway_url = (settings.agent_url or "").replace(
		"http://", "ws://"
	).replace("https://", "wss://")
	gateway_token = settings.get_password("agent_token")

	user_message = frappe.db.get_value(MSG, message_id, "content")
	# Prepend today's date as a context line so the agent can resolve
	# relative time expressions ("last quarter", "this week") without an
	# extra round-trip to clarify. The persisted user_message in the DB
	# is unchanged; only the value sent over to openclaw is augmented.
	user_message = _augment_with_context(user_message or "")

	try:
		sess = OpenclawSession.connect(gateway_url, gateway_token)
	except OpenclawUnreachableError as e:
		_mark_errored(assistant_msg.name, str(e))
		publish_to_user(user, {
			"kind": "run:error",
			"conversation_id": conversation_id,
			"message_id": assistant_msg.name,
			"run_id": run_id,
			"error": str(e),
		})
		return

	try:
		idem = f"{conversation_id}:{message_id}"
		tool_msg_by_call_id: dict[str, str] = {}
		for event in sess.stream_agent_turn(conv.session_key, user_message, idem):
			_handle_event(
				event,
				conversation_id=conversation_id,
				assistant_msg_name=assistant_msg.name,
				tool_msg_by_call_id=tool_msg_by_call_id,
				user=user,
				run_id=run_id,
			)
	except OpenclawUnreachableError as e:
		_mark_errored(assistant_msg.name, str(e))
		publish_to_user(user, {
			"kind": "run:error",
			"conversation_id": conversation_id,
			"message_id": assistant_msg.name,
			"run_id": run_id,
			"error": str(e),
		})
		return
	finally:
		sess.close()

	# Streaming exited cleanly via lifecycle.end
	frappe.db.set_value(MSG, assistant_msg.name, "streaming", 0)
	frappe.db.commit()
	publish_to_user(user, {
		"kind": "run:end",
		"conversation_id": conversation_id,
		"message_id": assistant_msg.name,
		"run_id": run_id,
	})


def _augment_with_context(user_message: str) -> str:
	"""Wrap the user message with a small session-level context block.

	The agent's persona (AGENTS.md) tells it to treat the leading
	``[Context: ...]`` line as system context, not user intent. This is
	how Jarvis grounds relative time expressions without per-turn clock
	lookups inside the agent.
	"""
	now = frappe.utils.now_datetime()
	today = now.strftime("%Y-%m-%d (%A)")
	return f"[Context: today is {today}]\n\n{user_message}"


def _create_assistant_placeholder(conv) -> "frappe.model.document.Document":
	from jarvis.chat.api import _next_seq

	seq = _next_seq(conv.name)
	msg = frappe.get_doc({
		"doctype": MSG,
		"conversation": conv.name,
		"seq": seq,
		"role": "assistant",
		"content": "",
		"streaming": 1,
	})
	msg.insert(ignore_permissions=True)
	frappe.db.commit()
	return msg


def _mark_errored(assistant_msg_name: str, error: str) -> None:
	frappe.db.set_value(MSG, assistant_msg_name, {
		"streaming": 0,
		"error": error,
	})
	frappe.db.commit()


def _handle_event(
	event: dict,
	*,
	conversation_id: str,
	assistant_msg_name: str,
	tool_msg_by_call_id: dict[str, str],
	user: str,
	run_id: str,
) -> None:
	kind = event.get("kind")

	if kind == "lifecycle":
		phase = event.get("phase")
		if phase == "error":
			_mark_errored(assistant_msg_name, event.get("error") or "lifecycle error")
			publish_to_user(user, {
				"kind": "run:error",
				"conversation_id": conversation_id,
				"message_id": assistant_msg_name,
				"run_id": run_id,
				"error": event.get("error"),
			})
		# lifecycle start is a no-op (we already published run:start)
		return

	if kind == "assistant":
		text = event.get("text", "")
		frappe.db.set_value(MSG, assistant_msg_name, "content", text)
		frappe.db.commit()
		publish_to_user(user, {
			"kind": "assistant:delta",
			"conversation_id": conversation_id,
			"message_id": assistant_msg_name,
			"text": text,
			"run_id": run_id,
		})
		return

	if kind == "tool":
		phase = event.get("phase")
		tool_call_id = event.get("tool_call_id")
		tool_name = event.get("tool_name")
		if phase == "start":
			from jarvis.chat.api import _next_seq
			seq = _next_seq(conversation_id)
			doc = frappe.get_doc({
				"doctype": MSG,
				"conversation": conversation_id,
				"seq": seq,
				"role": "tool",
				"content": f"calling {tool_name}…",
				"tool_name": tool_name,
				"tool_status": "running",
				"streaming": 1,
			})
			doc.insert(ignore_permissions=True)
			frappe.db.commit()
			tool_msg_by_call_id[tool_call_id] = doc.name
			publish_to_user(user, {
				"kind": "tool:start",
				"conversation_id": conversation_id,
				"message_id": doc.name,
				"tool_name": tool_name,
				"tool_call_id": tool_call_id,
				"run_id": run_id,
			})
		elif phase == "end":
			name = tool_msg_by_call_id.get(tool_call_id)
			if not name:
				return  # shouldn't happen, but ignore orphaned end events
			frappe.db.set_value(MSG, name, {
				"tool_status": event.get("status") or "completed",
				"streaming": 0,
			})
			frappe.db.commit()
			publish_to_user(user, {
				"kind": "tool:end",
				"conversation_id": conversation_id,
				"message_id": name,
				"tool_name": tool_name,
				"tool_call_id": tool_call_id,
				"status": event.get("status"),
				"run_id": run_id,
			})
