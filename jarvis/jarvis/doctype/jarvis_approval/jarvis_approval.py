# Copyright (c) 2026, Aerele and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class JarvisApproval(Document):
	"""A decision the agent needs a human for.

	Created by the agent itself (via the generic ``jarvis__create_doc``
	tool, per the ocr-data-entry skill contract) whenever a document flow
	hits something conventions cannot resolve. The chat turn ENDS there -
	the customer decides later from the Approvals pane (or the Desk list),
	and the decision is posted back into the linked conversation so the
	agent resumes with full context.
	"""

	def validate(self):
		if self.status != "Pending" and not self.decision:
			frappe.throw("A decided approval must carry the decision text.")
