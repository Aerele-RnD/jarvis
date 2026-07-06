"""Jarvis Agent Finding DocType controller.

One persistent, severity-tagged finding produced by a deterministic
``run_scrutiny`` result and written by
``jarvis.chat.agent_runs.record_scrutiny_run`` (never model-emitted — the
auditor SKILL narrates, this row is the reproducibility guarantee). Deduped
across runs on ``fingerprint``. The ``All`` role gets ``if_owner`` read + write
so the customer can move a finding to acknowledged/resolved from the SPA, but
cannot forge or reassign one (rows are inserted server-side and owned by the
installation owner).
"""

from frappe.model.document import Document


class JarvisAgentFinding(Document):
	pass
