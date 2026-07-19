"""Jarvis Agent Finding DocType controller.

One persistent, severity-tagged finding produced by a delegate's deterministic
evaluator and written by ``jarvis.chat.agent_runs.record_delegate_run`` (never
model-emitted — the delegate narrates, this row is the reproducibility
guarantee). Deduped across runs on ``fingerprint``. The ``All`` role gets ``if_owner`` read + write
so the customer can move a finding to acknowledged/resolved from the SPA, but
cannot forge or reassign one (rows are inserted server-side and owned by the
installation owner).
"""

from frappe.model.document import Document

# Engine-owned audit fields — everything except the user-actionable ``state``.
# Frozen on any customer save so the audited party cannot rewrite/erase a finding.
_FROZEN_FIELDS = (
	"run",
	"agent",
	"rule_id",
	"severity",
	"title",
	"detail_md",
	"section",
	"effective_date",
	"disclaimer",
	"ref_doctype",
	"ref_name",
	"amount",
	"fingerprint",
	"first_seen_run",
	"last_seen_run",
)


class JarvisAgentFinding(Document):
	def validate(self):
		self._freeze_audit_fields()

	def _freeze_audit_fields(self):
		"""TASK 31 (AGENTS-3): a finding is the reproducibility guarantee of an
		audit run. The customer gets ``if_owner`` WRITE so they can move a finding's
		``state`` (acknowledge / resolve), but the audited party must NOT be able to
		silently rewrite or erase the audit content (severity / detail_md / amount /
		…) via a generic-REST PUT and defeat the audit trail. On any non-new,
		non-server save, restore every engine-owned field to its stored value so
		only ``state`` can change. The engine writes with ``ignore_permissions``
		(insert) or raw ``db.set_value`` (recurrence / auto-resolve bumps), both of
		which bypass this."""
		if self.is_new() or self.flags.ignore_permissions:
			return
		before = self.get_doc_before_save()
		if not before:
			return
		for field in _FROZEN_FIELDS:
			stored = before.get(field)
			if self.get(field) != stored:
				self.set(field, stored)
