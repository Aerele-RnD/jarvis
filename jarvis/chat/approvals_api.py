"""Approvals pane API: pending-decision queue + decide-and-resume.

The agent queues decisions it cannot take autonomously as ``Jarvis Approval Request`` rows (see the ocr-data-entry skill contract) and ends the
turn. The customer decides from the SPA Approvals pane (or the Desk
list); deciding posts the decision back into the linked conversation
through the normal ``send_message`` path, so the agent resumes the flow
in the same chat with full context - no separate notification plumbing.
"""

from __future__ import annotations

import json

import frappe

APPROVAL = "Jarvis Approval Request"


def _parse_options(raw: str | None) -> list[str]:
	try:
		out = json.loads(raw or "[]")
		return [str(o) for o in out] if isinstance(out, list) else []
	except Exception:
		# The agent sometimes hands create_doc a real list, which Frappe
		# coerces to str(list) with single quotes - salvage it.
		try:
			import ast
			out = ast.literal_eval(raw or "[]")
			return [str(o) for o in out] if isinstance(out, list) else []
		except Exception:
			return []


def _may_act_on(conversation: str | None) -> bool:
	# SM, or the owner of the linked conversation.
	if "System Manager" in frappe.get_roles():
		return True
	if not conversation:
		return False
	return frappe.db.get_value("Jarvis Conversation", conversation, "owner") == frappe.session.user


@frappe.whitelist()
def list_approvals(status: str = "Pending", limit: int = 50) -> list[dict]:
	"""Approvals visible to the current user (owner of the linked
	conversation, or any System Manager)."""
	if status not in ("Pending", "Approved", "Rejected", "Decided", "All"):
		frappe.throw("Invalid status filter")
	if status == "All":
		filters = {}
	elif status == "Decided":
		filters = {"status": ["in", ["Approved", "Rejected"]]}
	else:
		filters = {"status": status}
	# Non-SM: filter by ownership IN the query so `limit` applies to the
	# caller's rows, not to a mixed page that later shrinks (and no N+1).
	if "System Manager" not in frappe.get_roles():
		my_convs = frappe.get_all(
			"Jarvis Conversation", filters={"owner": frappe.session.user},
			pluck="name",
		)
		if not my_convs:
			return []
		filters["conversation"] = ["in", my_convs]
	rows = frappe.get_all(
		APPROVAL, filters=filters,
		fields=[
			"name", "title", "status", "document_type", "question",
			"context_md", "options", "conversation", "ref_doctype",
			"ref_name", "decision", "decided_by", "decided_at", "creation",
		],
		order_by="creation desc", limit_page_length=int(limit),
	)
	for r in rows:
		r["options"] = _parse_options(r.get("options"))
	return rows


# --------------------------------------------------------------------------- #
# Paginated list (frozen envelope + facets) —
# chat-features-page-migration-design §2.5. ADDITIVE: list_approvals (above)
# STAYS (deprecated). Non-SM scoping is a JOIN on the conversation owner (not an
# IN(all my convs) list, which explodes at 1000s of conversations).
# --------------------------------------------------------------------------- #
_APPROVALS_SORTABLE = {"creation": "creation", "status": "status", "document_type": "document_type"}
_APPROVALS_FILTERS = {"status", "document_type", "conversation"}
_APPROVAL_STATUSES = {"Pending", "Approved", "Rejected", "Decided", "All"}


def _lk(s: str) -> str:
	"""Escape LIKE wildcards in user search input (``\\`` is the default escape)."""
	return (s or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _clamp_page(start, page_length) -> tuple[int, int]:
	try:
		start = max(0, int(start or 0))
	except (TypeError, ValueError):
		start = 0
	try:
		pl = int(page_length or 20)
	except (TypeError, ValueError):
		pl = 20
	return start, max(1, min(pl, 100))


def _load_filters(filters, allowed: set) -> dict:
	if isinstance(filters, str):
		if filters.strip():
			try:
				raw = frappe.parse_json(filters)
			except Exception:
				raw = {}
		else:
			raw = {}
	else:
		raw = filters or {}
	if not isinstance(raw, dict):
		raw = {}
	out: dict = {}
	for k, v in raw.items():
		if k not in allowed:
			frappe.throw(f"Unknown filter: {k}")
		if v in (None, ""):
			continue
		out[k] = v
	return out


def _order_by(sort_field, sort_dir, sortable: dict, default_field, default_dir, prefix="") -> str:
	col = sortable.get(sort_field or "")
	if not col:
		return f"{prefix}`{sortable[default_field]}` {default_dir}, {prefix}`name` asc"
	d = "desc" if (sort_dir or "").lower() == "desc" else "asc"
	return f"{prefix}`{col}` {d}, {prefix}`name` asc"


@frappe.whitelist()
def list_approvals_page(
	search: str = "",
	filters=None,
	sort_field: str = "",
	sort_dir: str = "",
	start: int = 0,
	page_length: int = 20,
) -> dict:
	"""Approvals visible to the caller (SM: all; non-SM: rows whose conversation
	they own), server-side search/filter/sort/paginate + a ``document_type`` facet
	for the triage tabs. Envelope ``{rows, total, has_more, start, page_length,
	facets}``. Behavior-identical scoping to ``list_approvals`` but scalable."""
	me = frappe.session.user
	start, pl = _clamp_page(start, page_length)
	f = _load_filters(filters, _APPROVALS_FILTERS)
	is_sm = "System Manager" in frappe.get_roles()

	if is_sm:
		from_sql = "`tabJarvis Approval Request` a"
	else:
		from_sql = (
			"`tabJarvis Approval Request` a "
			"JOIN `tabJarvis Conversation` c "
			"ON c.name = a.conversation AND c.owner = %(me)s"
		)

	params: dict = {"me": me, "start": start, "page_length": pl}

	# `base` applies to BOTH the main query and the facet query; the
	# document_type filter applies ONLY to the main query (facets drop it).
	base: list[str] = []
	status = f.get("status") or "Pending"
	if status not in _APPROVAL_STATUSES:
		frappe.throw("Invalid status filter")
	if status == "Decided":
		base.append("a.status IN ('Approved', 'Rejected')")
	elif status != "All":
		params["status"] = status
		base.append("a.status = %(status)s")
	if "conversation" in f:
		params["conv"] = f["conversation"]
		base.append("a.conversation = %(conv)s")
	if search:
		params["q"] = f"%{_lk(search)}%"
		base.append("(a.title LIKE %(q)s OR a.question LIKE %(q)s OR a.ref_name LIKE %(q)s)")

	doc_cond = None
	if "document_type" in f:
		dt = f["document_type"]
		if dt == "Unclassified":
			doc_cond = "TRIM(COALESCE(a.document_type, '')) = ''"
		else:
			params["dt"] = dt
			doc_cond = "a.document_type = %(dt)s"

	main_where = " AND ".join(base + ([doc_cond] if doc_cond else [])) or "1=1"
	base_where = " AND ".join(base) or "1=1"
	order = _order_by(sort_field, sort_dir, _APPROVALS_SORTABLE, "creation", "desc", prefix="a.")

	total = frappe.db.sql(f"SELECT COUNT(*) FROM {from_sql} WHERE {main_where}", params)[0][0]
	rows = frappe.db.sql(
		f"""SELECT a.name, a.title, a.status, a.document_type, a.question,
		a.context_md, a.options, a.conversation, a.ref_doctype, a.ref_name,
		a.decision, a.decided_by, a.decided_at, a.creation
		FROM {from_sql}
		WHERE {main_where}
		ORDER BY {order}
		LIMIT %(page_length)s OFFSET %(start)s""",
		params, as_dict=True,
	)
	for r in rows:
		r["options"] = _parse_options(r.get("options"))

	facet_rows = frappe.db.sql(
		f"""SELECT COALESCE(NULLIF(TRIM(a.document_type), ''), 'Unclassified') AS dtv,
		COUNT(*) AS n
		FROM {from_sql}
		WHERE {base_where}
		GROUP BY dtv
		ORDER BY n DESC""",
		params, as_dict=True,
	)
	facets = {"document_type": [{"value": x.dtv, "count": x.n} for x in facet_rows]}

	return {
		"rows": rows,
		"total": total,
		"has_more": start + len(rows) < total,
		"start": start,
		"page_length": pl,
		"facets": facets,
	}


@frappe.whitelist()
def pending_count() -> int:
	# Scoped like list_approvals: non-SM users count only their own.
	if "System Manager" in frappe.get_roles():
		return frappe.db.count(APPROVAL, {"status": "Pending"})
	return len(list_approvals("Pending"))


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
	if not _may_act_on(doc.conversation):
		frappe.throw("Not permitted", frappe.PermissionError)
	if doc.status != "Pending":
		frappe.throw(f"Approval {name} is already {doc.status}")
	new_status = "Approved" if int(approve) else "Rejected"
	# Conditional flip closes the double-decide race: only ONE concurrent
	# caller wins the Pending -> decided transition.
	changed = frappe.db.sql(
		"""update `tabJarvis Approval Request`
		set status=%s, decision=%s, decided_by=%s, decided_at=%s
		where name=%s and status='Pending'""",
		(new_status, decision, frappe.session.user, frappe.utils.now_datetime(), name),
	)
	if not frappe.db.sql(
		"select 1 from `tabJarvis Approval Request` where name=%s and status=%s and decided_by=%s",
		(name, new_status, frappe.session.user),
	):
		frappe.throw(f"Approval {name} was decided concurrently")
	frappe.db.commit()
	doc.reload()
	# fire the trace-comment hook (db update bypasses on_update)
	doc.run_method("on_update")

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
		f = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Jarvis Conversation",
				"attached_to_name": doc.conversation,
			},
			fields=["file_url", "file_name"],
			order_by="creation desc", limit_page_length=1,
		)
		if f:
			attachments = json.dumps(
				[{"file_url": f[0].file_url, "file_name": f[0].file_name}]
			)
		# The decision is durably recorded above; a resume failure must
		# not 500 the endpoint (the SPA would re-show a decided row).
		try:
			res = send_message(conversation=doc.conversation, message=msg, attachments=attachments)
			resumed = bool(res.get("ok"))
		except Exception:
			frappe.log_error(title="approval resume failed", message=frappe.get_traceback())
	return {"ok": True, "status": doc.status, "resumed": resumed}
