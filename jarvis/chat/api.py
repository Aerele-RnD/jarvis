"""Whitelisted endpoints for the Jarvis chat surface.

The browser talks to these from the /app/jarvis-chat Desk page.
"""

from __future__ import annotations

import frappe

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"


@frappe.whitelist()
def list_conversations() -> list[dict]:
	"""Return active conversations owned by the current user, newest first."""
	user = frappe.session.user
	rows = frappe.get_all(
		CONV,
		filters={"owner": user, "status": "active"},
		fields=["name", "title", "last_active_at"],
		order_by="last_active_at desc",
	)
	return rows


@frappe.whitelist()
def get_conversation(conversation: str) -> dict:
	"""Return conversation metadata + ordered messages.

	Raises frappe.DoesNotExistError if the conversation does not exist or
	the caller is not the owner.
	"""
	doc = frappe.get_doc(CONV, conversation)  # respects owner-only permission

	messages = frappe.get_all(
		MSG,
		filters={"conversation": conversation},
		fields=[
			"name", "seq", "role", "content", "streaming", "error",
			"tool_name", "tool_args", "tool_result", "tool_status",
		],
		order_by="seq asc",
	)
	return {
		"conversation": {
			"name": doc.name,
			"title": doc.title,
			"status": doc.status,
			"session_key": doc.session_key,
			"last_active_at": doc.last_active_at,
		},
		"messages": messages,
	}


@frappe.whitelist()
def create_conversation() -> str:
	"""Create an empty conversation owned by the current user; return its name."""
	doc = frappe.get_doc({
		"doctype": CONV,
		"title": "New chat",
		"status": "active",
	})
	doc.insert()
	frappe.db.commit()
	return doc.name


@frappe.whitelist()
def archive_conversation(conversation: str) -> dict:
	"""Set status to archived. The openclaw-side session is left in place."""
	doc = frappe.get_doc(CONV, conversation)
	doc.status = "archived"
	doc.save()
	frappe.db.commit()
	return {"ok": True}


import uuid

from frappe import _

from jarvis.chat.policy import validate_can_send
from jarvis.chat.openclaw_client import OpenclawSession


@frappe.whitelist()
def send_message(conversation: str, message: str) -> dict:
	"""Validate, persist the user message, ensure session_key, enqueue the worker.

	Returns {ok: True, run_id, message_id} on success or
	{ok: False, reason: str} on validation failure. Raises
	frappe.DoesNotExistError if the conversation does not exist or the
	caller is not the owner.
	"""
	user = frappe.session.user

	ok, reason = validate_can_send(user)
	if not ok:
		return {"ok": False, "reason": reason}

	if not message or not message.strip():
		return {"ok": False, "reason": _("message is empty")}

	conv_doc = frappe.get_doc(CONV, conversation)  # respects perms

	# Persist the user message with next seq value
	seq = _next_seq(conversation)
	msg_doc = frappe.get_doc({
		"doctype": MSG,
		"conversation": conversation,
		"seq": seq,
		"role": "user",
		"content": message.strip(),
		"streaming": 0,
	})
	msg_doc.insert()

	# First user message becomes the conversation title (capped at 60 chars)
	if conv_doc.title == "New chat":
		conv_doc.title = message.strip()[:60]
	conv_doc.last_active_at = frappe.utils.now()

	# Ensure the conversation has an openclaw session_key; create one on
	# first turn. Insert the Jarvis Chat Session row so the plugin's
	# sessionKey → user lookup works.
	if not conv_doc.session_key:
		conv_doc.session_key = _ensure_session_key(user)
	conv_doc.save()
	frappe.db.commit()

	# Enqueue the worker. Returns immediately; worker runs async.
	run_id = uuid.uuid4().hex[:12]
	frappe.enqueue(
		method="jarvis.chat.worker.run_agent_turn",
		queue="default",
		timeout=200,
		conversation_id=conversation,
		message_id=msg_doc.name,
		run_id=run_id,
	)

	return {"ok": True, "run_id": run_id, "message_id": msg_doc.name}


def _next_seq(conversation: str) -> int:
	"""Return the next seq value for a conversation (max+1, or 1 if empty)."""
	current_max = frappe.db.sql(
		"SELECT MAX(seq) FROM `tabJarvis Chat Message` WHERE conversation = %s",
		(conversation,),
	)[0][0]
	return (current_max or 0) + 1


def _ensure_session_key(user: str) -> str:
	"""Create an openclaw session for `user`, persist the Chat Session row,
	and return the session_key. Caller is responsible for storing it on the
	parent Conversation row.
	"""
	settings = frappe.get_single("Jarvis Settings")
	gateway_url = (settings.openclaw_gateway_url or "").replace("http://", "ws://").replace("https://", "wss://")
	gateway_token = settings.get_password("openclaw_gateway_token")
	if not gateway_url or not gateway_token:
		frappe.throw(_("openclaw is not configured"))

	import time
	sess = OpenclawSession.connect(gateway_url, gateway_token)
	try:
		# Label includes a timestamp because openclaw deduplicates sessions
		# by label and rejects collisions.
		session_key = sess.create_session(label=f"jarvis-chat-{user}-{int(time.time() * 1000)}")
	finally:
		sess.close()

	# Insert the Chat Session row (plugin's sessionKey → user lookup table)
	frappe.get_doc({
		"doctype": "Jarvis Chat Session",
		"session_key": session_key,
		"user": user,
	}).insert(ignore_permissions=True)
	frappe.db.commit()

	return session_key
