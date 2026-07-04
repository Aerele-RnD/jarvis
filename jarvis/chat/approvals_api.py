"""Approvals pane API: pending-decision queue + decide-and-resume.

The agent queues decisions it cannot take autonomously as ``Jarvis
Approval`` rows (see the ocr-data-entry skill contract) and ends the
turn. The customer decides from the SPA Approvals pane (or the Desk
list); deciding posts the decision back into the linked conversation
through the normal ``send_message`` path, so the agent resumes the flow
in the same chat with full context - no separate notification plumbing.
"""

from __future__ import annotations

import json

import frappe

APPROVAL = "Jarvis Approval"


def _parse_options(raw: str | None) -> list[str]:
	try:
		out = json.loads(raw or "[]")
		return [str(o) for o in out] if isinstance(out, list) else []
	except Exception:
		return []


@frappe.whitelist()
def list_approvals(status: str = "Pending", limit: int = 50) -> list[dict]:
	"""Approvals visible to the current user (owner of the linked
	conversation, or any System Manager)."""
	if status not in ("Pending", "Approved", "Rejected", "All"):
		frappe.throw("Invalid status filter")
	filters = {} if status == "All" else {"status": status}
	rows = frappe.get_all(
		APPROVAL, filters=filters,
		fields=[
			"name", "title", "status", "question", "context_md", "options",
			"conversation", "ref_doctype", "ref_name", "decision",
			"decided_by", "decided_at", "creation",
		],
		order_by="creation desc", limit_page_length=int(limit),
	)
	is_sm = "System Manager" in frappe.get_roles()
	out = []
	for r in rows:
		if not is_sm:
			conv_owner = (
				frappe.db.get_value("Jarvis Conversation", r.conversation, "owner")
				if r.conversation else None
			)
			if conv_owner != frappe.session.user:
				continue
		r["options"] = _parse_options(r.get("options"))
		out.append(r)
	return out


@frappe.whitelist()
def pending_count() -> int:
	return frappe.db.count(APPROVAL, {"status": "Pending"})


@frappe.whitelist()
def decide(name: str, decision: str, approve: int = 1) -> dict:
	"""Record the decision and resume the linked conversation.

	``decision`` is the human's answer (an option or free text). The
	resume message is a plain user message through send_message, so the
	agent sees it exactly like any chat turn - same session, same context.
	"""
	decision = (decision or "").strip()
	if not decision:
		frappe.throw("Decision text is required")
	doc = frappe.get_doc(APPROVAL, name)
	if doc.status != "Pending":
		frappe.throw(f"Approval {name} is already {doc.status}")
	doc.status = "Approved" if int(approve) else "Rejected"
	doc.decision = decision
	doc.decided_by = frappe.session.user
	doc.decided_at = frappe.utils.now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	resumed = False
	if doc.conversation and frappe.db.exists("Jarvis Conversation", doc.conversation):
		from jarvis.chat.api import send_message
		verdict = "APPROVED" if doc.status == "Approved" else "REJECTED"
		msg = (
			f"[Approval {doc.name} - {doc.title}] {verdict}: {decision}\n"
			f"Continue the flow with this decision; do not re-ask."
		)
		# File-Box conversations: re-attach the source document. Attachments
		# ride only the message they were sent with, so a resumed turn can
		# no longer SEE the pages - observed live: the agent (correctly)
		# refused to draft rather than fabricate lines it couldn't see.
		attachments = None
		title = frappe.db.get_value("Jarvis Conversation", doc.conversation, "title") or ""
		if title.startswith("File: "):
			fname = title[len("File: "):]
			f = frappe.get_all(
				"File", filters={"file_name": ["like", fname + "%"]},
				fields=["file_url", "file_name"],
				order_by="creation desc", limit_page_length=1,
			)
			if f:
				attachments = json.dumps(
					[{"file_url": f[0].file_url, "file_name": f[0].file_name}]
				)
		res = send_message(conversation=doc.conversation, message=msg, attachments=attachments)
		resumed = bool(res.get("ok"))
	return {"ok": True, "status": doc.status, "resumed": resumed}
