"""Direct apply for chat action cards (the record draft panel).

The agent emits a ``jarvis-action`` block; the SPA renders it in a side-panel
editor and posts the FINAL values here — no LLM turn in the apply path. All
mutations route through the existing permission-checked tools
(``jarvis.tools.create_doc`` etc.), so this module adds routing + a receipt,
not a second write path.
"""

import frappe
from frappe import _

from jarvis import audit
from jarvis.chat.api import _NON_EDIT_FIELDTYPES, _next_seq
from jarvis.exceptions import InvalidArgumentError

MSG = "Jarvis Chat Message"
CONV = "Jarvis Conversation"

# Child-grid columns can be any data-bearing fieldtype except nested tables
# (no grid-in-grid in v1).
_SKIP_CHILD_FIELDTYPES = _NON_EDIT_FIELDTYPES | {"Table", "Table MultiSelect"}


def _field_dict(df) -> dict:
	return {
		"fieldname": df.fieldname,
		"label": df.label or df.fieldname,
		"fieldtype": df.fieldtype,
		"options": df.options or "",
		"reqd": int(df.reqd or 0),
		"read_only": int(df.read_only or 0),
	}


def _child_columns(child_doctype: str) -> list[dict]:
	"""Grid columns for one child table: the child's in_list_view fields (what
	the Desk grid shows), falling back to the first 4 editable fields when the
	child marks none."""
	meta = frappe.get_meta(child_doctype)
	editable = [
		df for df in meta.fields
		if df.fieldname and df.fieldtype not in _SKIP_CHILD_FIELDTYPES
	]
	listed = [df for df in editable if df.in_list_view]
	return [_field_dict(df) for df in (listed or editable[:4])]


@frappe.whitelist()
def get_doctype_form_meta(doctype: str) -> dict:
	"""Form metadata for the draft panel: main fields INCLUDING Table fields,
	plus per-table child columns — one call, so the panel never fans out.
	Gated on read permission of the parent (child meta rides on that gate)."""
	doctype = (doctype or "").strip()
	if not doctype or not frappe.db.exists("DocType", doctype):
		return {"ok": False, "reason": _("unknown doctype")}
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("You don't have access to {0}.").format(doctype), frappe.PermissionError)
	meta = frappe.get_meta(doctype)
	fields, tables = [], {}
	for df in meta.fields:
		if not df.fieldname:
			continue
		if df.fieldtype == "Table" and df.options:
			fields.append(_field_dict(df))
			tables[df.fieldname] = {
				"child_doctype": df.options,
				"label": df.label or df.fieldname,
				"columns": _child_columns(df.options),
			}
			continue
		if df.fieldtype in _NON_EDIT_FIELDTYPES:
			continue
		fields.append(_field_dict(df))
	return {
		"ok": True,
		"doctype": doctype,
		"is_submittable": int(meta.is_submittable or 0),
		"title_field": meta.get("title_field") or "",
		"fields": fields,
		"tables": tables,
	}


@frappe.whitelist()
def load_doc(doctype: str, name: str) -> dict:
	"""Current values of one document (main fields + child rows restricted to
	the form-meta columns) so the panel can pre-fill an update draft. Gated on
	WRITE permission — this endpoint exists to edit."""
	doctype = (doctype or "").strip()
	name = (name or "").strip()
	if not doctype or not name:
		raise InvalidArgumentError("doctype and name are required")
	if not frappe.db.exists(doctype, name):
		raise frappe.DoesNotExistError(f"{doctype} {name} not found")
	if not frappe.has_permission(doctype, "write", doc=name):
		frappe.throw(_("You can't edit {0} {1}.").format(doctype, name), frappe.PermissionError)
	fm = get_doctype_form_meta(doctype)
	doc = frappe.get_doc(doctype, name)
	values = {}
	for f in fm["fields"]:
		if f["fieldtype"] == "Table":
			continue
		v = doc.get(f["fieldname"])
		values[f["fieldname"]] = "" if v is None else v
	tables = {}
	for tf, spec in fm["tables"].items():
		cols = [c["fieldname"] for c in spec["columns"]]
		tables[tf] = [
			{c: row.get(c) for c in cols} for row in (doc.get(tf) or [])
		]
	return {
		"ok": True, "doctype": doctype, "name": name,
		"docstatus": int(doc.docstatus or 0),
		"values": values, "tables": tables,
	}


# apply_action is the human-authored EDIT path only: the human deliberately
# changes values in the draft panel and applies them under their own session.
# The confirm-as-proposed verbs run the payload the MODEL proposed, so they must
# route through the token gate (confirm_tool), never here.
_EDIT_VERBS = {"create", "update"}
_CONFIRM_VERBS = {"submit", "cancel", "delete", "amend"}
_RECEIPT = {"create": "Created", "update": "Updated"}


def _require_own_conversation(conversation: str) -> None:
	owner = frappe.db.get_value(CONV, conversation, "owner")
	if not owner:
		raise InvalidArgumentError("unknown conversation")
	if owner != frappe.session.user:
		frappe.throw(_("Not your conversation."), frappe.PermissionError)


def _append_receipt(conversation: str, verb: str, doctype: str, name: str,
					args: dict, submitted: int = 0) -> None:
	"""Tool message first (feeds the SPA's docRefs → the receipt's doc id
	linkifies to Desk), then a short assistant receipt the agent also sees in
	the transcript on its next turn — so it never re-applies the change."""
	frappe.get_doc({
		"doctype": MSG, "conversation": conversation, "seq": _next_seq(conversation),
		"role": "tool", "streaming": 0,
		"tool_name": f"{verb}_doc",
		"tool_args": frappe.as_json(args),
		"tool_result": frappe.as_json({"ok": True, "data": {"doctype": doctype, "name": name}}),
		"tool_status": "completed",
	}).insert(ignore_permissions=True)
	text = f"{_RECEIPT[verb]} {doctype} {name}."
	if verb == "create" and submitted:
		text = f"Created and submitted {doctype} {name}."
	frappe.get_doc({
		"doctype": MSG, "conversation": conversation, "seq": _next_seq(conversation),
		"role": "assistant", "content": text, "streaming": 0,
	}).insert(ignore_permissions=True)
	frappe.db.set_value(CONV, conversation, "last_active_at", frappe.utils.now(),
						update_modified=False)


@frappe.whitelist()
def apply_action(action: dict | str | None = None) -> dict:
	"""Apply a human-authored draft-panel edit: create or update ONLY, with the
	values the human deliberately entered before applying. Runs as the session
	user; the mutation goes through the existing tool (its permission and
	protected-field checks fire unchanged), is audited as a human-authored write,
	and leaves a receipt in the conversation.

	The confirm-as-proposed verbs (submit/cancel/delete/amend) run the payload
	the MODEL proposed, so they are NOT accepted here; they route through the
	token gate (``confirm_tool``). ``conversation`` is mandatory and always
	owner-checked: an apply can only ever act inside the caller's own
	conversation."""
	a = frappe.parse_json(action) if isinstance(action, str) else (action or {})
	verb = (a.get("verb") or "").strip()
	doctype = (a.get("doctype") or "").strip()
	name = (a.get("name") or "").strip()
	conversation = (a.get("conversation") or "").strip()
	values = a.get("values") or {}
	do_submit = int(a.get("submit") or 0)
	if verb in _CONFIRM_VERBS:
		raise InvalidArgumentError(
			f"{verb!r} is a confirm-as-proposed action; approve it through the "
			"confirmation card, not the draft-edit path.")
	if verb not in _EDIT_VERBS:
		raise InvalidArgumentError(f"unsupported verb {verb!r}")
	if not doctype:
		raise InvalidArgumentError("doctype is required")
	if not conversation:
		raise InvalidArgumentError("conversation is required")
	_require_own_conversation(conversation)

	if verb == "create":
		from jarvis.tools.create_doc import create_doc
		res = create_doc(doctype, values)
		name = res.get("name")
		if do_submit:
			# Submit of the JUST-created draft the human authored (the same
			# payload they saw) - low risk, kept as part of the draft-editor UX.
			from jarvis.tools.submit_doc import submit_doc
			submit_doc(doctype, name)
		args = {"doctype": doctype, "values": values}
	else:  # update
		from jarvis.tools.update_doc import update_doc
		update_doc(doctype, name, values)
		args = {"doctype": doctype, "name": name, "changes": values}

	# Audit as a human-authored write, distinct from a model tool call. The
	# actor (frappe.session.user) is captured by audit.record; the tool label
	# marks the human-edit origin.
	audit.record(tool=f"apply_action.{verb}_doc", args=args, ok=True,
				 result={"doctype": doctype, "name": name})

	frappe.db.commit()
	try:
		_append_receipt(conversation, verb, doctype, name, args, do_submit)
		frappe.db.commit()
	except Exception:
		# The mutation is already committed — a receipt hiccup must not
		# report failure (the SPA would retry and duplicate the create).
		frappe.log_error(title="apply_action receipt failed", message=frappe.get_traceback())
	slug = doctype.lower().replace(" ", "-")
	return {"ok": True, "verb": verb, "name": name,
			"doc_url": f"/app/{slug}/{name}"}


_INVALID_CONFIRM = {
	"ok": False,
	"error": {
		"type": "InvalidConfirmation",
		"message": "This confirmation is no longer valid.",
	},
}


@frappe.whitelist()
def confirm_tool(token: str, conversation: str | None = None) -> dict:
	"""Execute a parked mutating tool call after the human clicked Confirm.

	Owner-bound + conversation-bound + single-use via ``pending_confirm``. The
	confirmation gate in ``jarvis.api._run_tool`` parks every gated write and
	stores the authoritative call; this endpoint is the ONLY path that runs it.

	Human cookie-session only (whitelisted, not allow_guest, not the plugin
	path).

	Identity model (issue #186, #1/#5/#6): the gate binds the token to the
	CONVERSATION OWNER - the human whose browser is subscribed and who clicks
	Confirm. That is ``frappe.session.user`` here in BOTH deployment modes (in
	self-host the operator's browser session is the conversation owner, not the
	restricted tool user), so we consume under the session user directly - no
	per-mode owner resolution. ``consume`` re-validates owner + conversation
	atomically and single-uses the token; a wrong-owner caller learns nothing
	and does NOT burn the token.

	Conversation guard (#11): ``conversation`` is the conversation the click came
	from (the SPA passes its current id). When given it is passed into
	``consume`` as a REAL check (record.conversation must match). When omitted
	(back-compat) the record's own conversation is used - a tautology - so the
	guard reduces to owner + single-use and the conversation check does not
	actually run.

	Execution scope (#6): the confirmed write executes AS the stored
	``exec_user`` (the scoped model-execution identity - the tool user in
	self-host), so a confirm can never exceed the model path's permission scope.
	The original session user is always restored in a finally.
	"""
	if frappe.session.user == "Guest":
		raise frappe.PermissionError("authentication required")

	from jarvis.chat import pending_confirm
	from jarvis import api

	token = (token or "").strip()
	record = pending_confirm.peek(token)
	if not record:
		return _INVALID_CONFIRM

	# Real conversation guard (#11): if the caller passed the conversation the
	# click came from, enforce it; otherwise fall back to the record's own
	# conversation (owner + single-use remain the guarantees).
	passed_conv = (conversation or "").strip()
	guard_conv = passed_conv if passed_conv else record.get("conversation")
	record = pending_confirm.consume(
		token, owner=frappe.session.user, conversation=guard_conv)
	if not record:
		return _INVALID_CONFIRM

	# Execute AS the scoped model-execution identity the gate stored, restoring
	# the confirming session user afterwards no matter what. exec_user defaults
	# to the owner for tokens minted before this field existed.
	exec_user = record.get("exec_user") or record.get("owner") or frappe.session.user
	original = frappe.session.user
	frappe.set_user(exec_user)
	try:
		# Same envelope + audit as an inline write - dispatch_confirmed bypasses
		# the gate so the stored call actually executes instead of parking again.
		result = api.dispatch_confirmed(record["tool"], record["args"])
	finally:
		frappe.set_user(original)

	# Leave a transcript receipt (#7) so a confirmed delete/submit/email shows on
	# reload, matching the inline model-write path's tool card. Best-effort: the
	# write already committed, so a receipt hiccup must not report failure. Needs
	# a resolved conversation to attach to (self-host with no conv binding skips).
	conv = record.get("conversation")
	if conv:
		try:
			api.persist_tool_receipt(conv, record["tool"], record["args"], result)
		except Exception:
			frappe.log_error(title="confirm_tool receipt failed",
							 message=frappe.get_traceback())

	return result


@frappe.whitelist()
def list_pending_confirmations(conversation: str | None = None) -> dict:
	"""Re-surface the caller's OWN currently-parked confirmation cards after a
	reload/reconnect (issue #186, enables R3's fix for #3).

	Owner-scoped: returns only the calling user's live parked tokens (never
	another user's), optionally filtered to ``conversation``. Each item carries
	exactly what the ``action:pending`` realtime event already delivers to this
	same owner's UI - token + tool + preview + summary + conversation + run_id -
	so no new information is leaked. Human cookie-session only.
	"""
	if frappe.session.user == "Guest":
		raise frappe.PermissionError("authentication required")

	from jarvis.chat import pending_confirm
	from jarvis.api import _pending_preview, _describe_call

	conv = (conversation or "").strip() or None
	records = pending_confirm.list_for_owner(frappe.session.user, conversation=conv)
	items = []
	for r in records:
		tool = r.get("tool")
		args = r.get("args") or {}
		items.append({
			"token": r.get("token"),
			"tool": tool,
			"preview": _pending_preview(tool, args),
			"summary": _describe_call(tool, args),
			"conversation": r.get("conversation"),
			"run_id": r.get("run_id"),
		})
	return {"ok": True, "data": {"pending": items}}
