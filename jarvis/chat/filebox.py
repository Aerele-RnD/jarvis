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
	"unreadable - goes to a Jarvis Approval Request row (empty document_type for "
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
	# background=1 (requires the dedicated-chat-queue PR): a batch of
	# drops drains FIFO and never jumps ahead of a human's typed question.
	res = send_message(
		conversation=conv_id, message=INBOUND_PROMPT, attachments=attachments,
		background=1,
	)
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
	conv_ids = [r.name for r in rows]
	# Batched: one grouped query for pending approvals, one window query for
	# each conversation's latest assistant message (was a 2xN loop).
	pending_by_conv = {}
	if conv_ids:
		# Raw SQL: v16's get_all rejects SQL-function strings in fields
		# ("count(name) as n" -> ValidationError), which 500'd this whole
		# endpoint for anyone with a File-Box conversation.
		for row in frappe.db.sql(
			"""select conversation, count(name) n
			from `tabJarvis Approval Request`
			where conversation in %(convs)s and status='Pending'
			group by conversation""",
			{"convs": conv_ids}, as_dict=True,
		):
			pending_by_conv[row.conversation] = row.n
	last_by_conv = {}
	if conv_ids:
		for row in frappe.db.sql(
			"""select m.conversation, m.streaming, m.error, m.recovering
			from `tabJarvis Chat Message` m
			join (select conversation, max(seq) mseq from `tabJarvis Chat Message`
			      where conversation in %(convs)s and role='assistant'
			      group by conversation) x
			  on x.conversation = m.conversation and x.mseq = m.seq
			where m.role='assistant'""",
			{"convs": conv_ids}, as_dict=True,
		):
			last_by_conv[row.conversation] = row
	for r in rows:
		last = [last_by_conv[r.name]] if r.name in last_by_conv else []
		pending = pending_by_conv.get(r.name, 0)
		if pending:
			r["status"] = "needs_approval"
		elif last and (last[0].streaming or last[0].recovering):
			r["status"] = "processing"
		elif last and last[0].error:
			r["status"] = "error"
		elif not last:
			# Dropped but the worker hasn't inserted the assistant
			# placeholder yet - queued, not done.
			r["status"] = "processing"
		else:
			r["status"] = "done"
		r["pending_approvals"] = pending
	return rows
