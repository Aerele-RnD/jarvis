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
