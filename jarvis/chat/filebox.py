"""File Box: drop an inbound business document, get a draft.

The SPA's File Box pane uploads the file (standard Frappe upload_file),
then calls ``drop_file``. That creates a conversation named after the
file and sends ONE directed prompt through the normal send_message +
attachments machinery: process via the ocr-data-entry skill, decide by
convention, queue Jarvis Approval rows for real ambiguities, at most one
consolidated question. The chat stays the execution surface - the File
Box is just the directed entry point, so streaming, drafts, approvals
and recovery all behave exactly like a hand-typed turn.
"""

from __future__ import annotations

import json

import frappe

INBOUND_PROMPT = (
	"This file arrived through the File Box - process it as an inbound "
	"business document using the ocr-data-entry skill (read "
	"skills/ocr-data-entry/SKILL.md first and follow its decision policy "
	"exactly). Classify the document type, extract it fully - every line "
	"item verbatim, never a lump-sum balancing line - resolve ambiguities "
	"by the skill's convention ladder, and create the draft. Do NOT ask "
	"me anything in this chat: I am not here. EVERY decision that needs "
	"a human - including what document this is, or that the file is "
	"unreadable - goes to a Jarvis Approval row (empty document_type for "
	"classification decisions), then end the turn with a one-line summary."
)


@frappe.whitelist()
def drop_file(file_url: str, file_name: str | None = None) -> dict:
	"""Create a conversation for an uploaded file and kick off processing."""
	file_url = (file_url or "").strip()
	if not file_url:
		frappe.throw("file_url is required")
	# The URL must be a real uploaded File of this site (no external URLs).
	fdoc = frappe.db.get_value(
		"File", {"file_url": file_url},
		["name", "file_name", "file_size", "is_private"], as_dict=True,
	)
	if not fdoc:
		frappe.throw("Unknown file - upload it first")
	# Object-level auth: a caller must not be able to feed SOMEONE ELSE'S
	# private file_url and have the agent OCR its contents back to them.
	if not frappe.has_permission("File", doc=fdoc.name):
		frappe.throw("Not permitted", frappe.PermissionError)

	from jarvis.chat.api import create_conversation, send_message

	conv_id = create_conversation()
	title = (file_name or fdoc.file_name or "Inbound document")[:60]
	frappe.db.set_value(
		"Jarvis Conversation", conv_id, "title", f"File: {title}",
		update_modified=False,
	)
	# Durable exact link: attach the File to the conversation so resumes
	# re-attach THIS file (not a fragile filename-prefix LIKE match).
	frappe.db.set_value(
		"File", fdoc.name,
		{"attached_to_doctype": "Jarvis Conversation", "attached_to_name": conv_id},
		update_modified=False,
	)
	frappe.db.commit()

	attachments = json.dumps([{"file_url": file_url, "file_name": file_name or fdoc.file_name}])
	res = send_message(conversation=conv_id, message=INBOUND_PROMPT, attachments=attachments)
	return {
		"ok": bool(res.get("ok")),
		"conversation_id": conv_id,
		"run_id": res.get("run_id"),
		"reason": res.get("reason"),
	}


@frappe.whitelist()
def list_inbound(limit: int = 30) -> list[dict]:
	"""Recent File-Box conversations for the pane's inbound list, with a
	coarse status derived from live chat state - no extra bookkeeping
	doctype to drift out of sync."""
	rows = frappe.get_all(
		"Jarvis Conversation",
		filters={"title": ["like", "File: %"], "owner": frappe.session.user},
		fields=["name", "title", "creation"],
		order_by="creation desc", limit_page_length=int(limit),
	)
	for r in rows:
		last = frappe.get_all(
			"Jarvis Chat Message",
			filters={"conversation": r.name, "role": "assistant"},
			fields=["streaming", "error", "recovering"],
			order_by="seq desc", limit_page_length=1,
		)
		pending = frappe.db.count(
			"Jarvis Approval", {"conversation": r.name, "status": "Pending"}
		)
		if pending:
			r["status"] = "needs_approval"
		elif last and (last[0].streaming or last[0].recovering):
			r["status"] = "processing"
		elif last and last[0].error:
			r["status"] = "error"
		else:
			r["status"] = "done"
		r["pending_approvals"] = pending
	return rows
