# Copyright (c) 2026, Aerele and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class JarvisApproval(Document):
	"""A decision the agent needs a human for.

	Created by the agent itself (via the generic ``jarvis__create_doc``
	tool, per the ocr-data-entry skill contract). The chat turn ENDS
	there - the customer decides later from the Approvals pane/page, and
	the decision is posted back into the linked conversation so the
	agent resumes with full context.
	"""

	def validate(self):
		if self.status != "Pending" and not self.decision:
			frappe.throw("A decided approval must carry the decision text.")

	def on_update(self):
		self._leave_trace_comment()

	def _leave_trace_comment(self):
		"""Audit trail ON the business document: once this approval is
		decided AND points at a real document, add a Comment to that
		document in the name of the deciding user. Runs on every save so
		it also fires when the agent fills ref_doctype/ref_name AFTER the
		decision (the resumed flow creates the document later)."""
		if (
			self.status == "Pending"
			or self.trace_comment_added
			or not (self.ref_doctype and self.ref_name)
			or not frappe.db.exists(self.ref_doctype, self.ref_name)
		):
			return
		decider = self.decided_by or frappe.session.user
		comment = frappe.get_doc({
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": self.ref_doctype,
			"reference_name": self.ref_name,
			"content": (
				f"Approval <b>{self.name}</b> ({frappe.utils.escape_html(self.title or '')}): "
				f"<b>{self.status}</b> - {frappe.utils.escape_html(self.decision or '')}"
			),
			"comment_email": decider,
			"comment_by": frappe.utils.get_fullname(decider),
		})
		comment.flags.ignore_permissions = True
		comment.insert(ignore_permissions=True)
		# owner = the approver, so the trace reads as their action.
		frappe.db.set_value("Comment", comment.name, "owner", decider, update_modified=False)
		self.db_set("trace_comment_added", 1, update_modified=False)
