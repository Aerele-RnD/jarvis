"""Build the render-ready "what will change" summary for a confirmation card (F9).

The write-safety gate (``jarvis.api._run_tool``) parks a gated write and shows the
user a card. Today that card renders a raw-JSON dump of the dry-run ``would`` doc
and a one-line ``_describe_call`` target string - it names the record but not what
the write does to it. ``build_card`` turns the tool + args + park-time preview into
a structured, human-readable summary the SPA renders like the model-authored draft
card (a field list for a create, a from->to diff for an update, a per-record
from->to diff for a bulk update, a verb line for submit/cancel/delete/amend,
to/subject/body for an email, method + args for run_method).

It is attached ONCE at park as ``preview["card"]`` (see the gate). Phase-1 F2 stores
the park-time preview in the token record and the resync endpoint returns it
verbatim, so the card rides the ``action:pending`` event, the record, and every
resync identically - it is never rebuilt at resync (which would let it diverge from
the stored preview and re-load the doc on each reconnect).

Safety: values come from the ALREADY perm-filtered ``would`` (create/update tools
call ``apply_fieldlevel_read_permissions`` before returning), and the update
``from`` values are read from a freshly-fetched doc that is permission-CHECKED
(``has_permission("read")``) and then perm-filtered - ``frappe.get_doc`` checks no
permission on its own unless passed a ``check_permission`` kwarg (which defaults to
None), and the fieldlevel filter is permlevel-only, so the explicit check is what
keeps an unreadable record's old values off the card. Long values are truncated,
rows capped, and obviously-secret ``run_method`` arg keys masked. The card carries
no material the owner would not already see in the post-confirm receipt.

Field selection, doc reads, value formatting and no-op detection all live in
``jarvis.chat._record_summary``; this module owns card SHAPE only. The dependency
runs one way (confirm_card -> _record_summary) and must stay that way.

Returns ``None`` for tool shapes without a bespoke card (share_doc, assign_to,
create_custom_skill, update_wiki, bulk email, and any token minted before this
existed) - the SPA falls back to the summary + raw-preview rendering.
"""

from __future__ import annotations

import frappe

from jarvis.chat._record_summary import (
	_MAX_TABLES,
	fmt,
	is_secret,
	same_value,
	summary_rows,
	table_rows,
)

_MAX_ROWS = 20  # cap fields / diff rows / batch bullets / targets shown
_BULK_KEYS = ("names", "updates", "docs", "messages")

# tool -> present-tense verb for the "will <verb> this <doctype> <name>" card.
_VERB = {
	"submit_doc": "submit",
	"cancel_doc": "cancel",
	"delete_doc": "delete",
	"amend_doc": "amend",
	"apply_workflow_action": "apply",
}


def build_card(tool: str, args, preview) -> dict | None:
	"""Structured, render-ready confirmation summary, or None to fall back to the
	SPA's summary + raw-preview rendering. Best-effort: never raises (a card is
	UX, not correctness), so a failure just yields None."""
	if not isinstance(args, dict):
		return None
	would = preview.get("would") if isinstance(preview, dict) else None
	try:
		bulk_key, bulk_items = _bulk(args)
		if tool == "create_doc":
			return _batch_create_card(would) if bulk_key == "docs" else _create_card(args, would)
		if tool == "update_doc" and not bulk_key:
			return _update_card(args, would)
		if tool == "update_doc" and bulk_key == "updates":
			return _bulk_update_card(args, bulk_items)
		if tool in _VERB:
			return _verb_card(tool, args, bulk_items)
		if tool == "send_email":
			return _email_card(args)
		if tool == "run_method":
			return _method_card(args)
	except Exception:
		frappe.log_error(title="build_card failed", message=frappe.get_traceback())
	return None


def _bulk(args: dict):
	"""(batch-key, items) for a bulk call, else (None, None). Keys are mutually
	exclusive per the tool contracts."""
	for k in _BULK_KEYS:
		v = args.get(k)
		if isinstance(v, list) and v:
			return k, v
	return None, None


def _meta(doctype):
	try:
		return frappe.get_meta(doctype) if doctype else None
	except Exception:
		return None


def _label(meta, fieldname: str) -> str:
	if meta:
		df = meta.get_field(fieldname)
		if df and df.label:
			return df.label
	return fieldname


def _create_card(args: dict, would) -> dict:
	doctype = args.get("doctype")
	values = args.get("values") if isinstance(args.get("values"), dict) else {}
	meta = _meta(doctype)
	# Child tables FIRST: a list value rendered as a table must not also render as a
	# bare "Items · 1 row" text row below. The ``would`` guard is the same perm check
	# the scalar rows use - a permlevel-dropped table would otherwise show as a write
	# that will not happen.
	tables, table_keys = [], set()
	for key in list(values):
		if len(tables) >= _MAX_TABLES:
			break
		value = values.get(key)
		if not isinstance(value, list) or not value:
			continue
		if isinstance(would, dict) and key not in would:
			continue  # perm-dropped from the resolved doc: the save will not write it
		t = table_rows(meta, key, value)
		if t:
			tables.append(t)
			table_keys.add(key)
	rows = []
	for key in list(values)[: _MAX_ROWS * 2]:
		# Perm guard: only show a field that survived the resolved doc's
		# field-level read-permission filter.
		if isinstance(would, dict) and key not in would:
			continue
		if key in table_keys:
			continue  # rendered as a table below, not as a bare "N rows"
		val = would.get(key) if isinstance(would, dict) else values.get(key)
		if val is None or (not isinstance(val, list) and str(val).strip() == ""):
			continue
		df = meta.get_field(key) if meta else None
		rows.append({"label": _label(meta, key), "value": fmt(val, df)})
		if len(rows) >= _MAX_ROWS:
			break
	name = would.get("name") if isinstance(would, dict) else None
	return {"kind": "create", "doctype": doctype, "name": name, "rows": rows,
			"tables": tables}


def _update_card(args: dict, would) -> dict:
	doctype = args.get("doctype")
	name = args.get("name")
	changes = args.get("changes") if isinstance(args.get("changes"), dict) else {}
	meta = _meta(doctype)
	# OLD values from the current doc (the park dry-run rolled back, so the DB is
	# back to the pre-update state), permission-CHECKED then perm-filtered so
	# neither an unreadable record's nor a restricted field's old value ever leaks.
	# NEW values from ``would`` (already perm-filtered + normalized by the tool).
	old = {}
	doc = None  # must be bound: fmt(..., doc=doc) below needs it for currency/link titles
	try:
		doc = frappe.get_doc(doctype, name)
		# get_doc checks NO permission unless passed a check_permission kwarg
		# (document.py:141-145 -> :336-349), which defaults to None; and the
		# fieldlevel filter below is permlevel-only. Without this, a user who cannot
		# read the record sees its old values on the card.
		if not doc.has_permission("read"):
			raise frappe.PermissionError
		doc.apply_fieldlevel_read_permissions()
		old = doc.as_dict()
	except Exception:
		frappe.clear_messages()  # get_doc's throw leaves an entry that leaks into the turn
		old, doc = {}, None
	diff = []
	for key in list(changes)[: _MAX_ROWS * 2]:
		if isinstance(would, dict) and key not in would:
			continue  # not perm-visible in the resolved doc
		to_val = would.get(key) if isinstance(would, dict) else changes.get(key)
		from_val = old.get(key)
		df = meta.get_field(key) if meta else None
		if same_value(from_val, to_val, df):
			continue  # the save would not change the stored value
		from_s, to_s = fmt(from_val, df, doc), fmt(to_val, df)
		if is_secret(meta, key):
			from_s = to_s = "[hidden]"  # never render a password / secret value
		diff.append({"label": _label(meta, key), "from": from_s, "to": to_s})
		if len(diff) >= _MAX_ROWS:
			break
	title = ""
	if doc is not None and meta:
		try:
			tf = meta.get_title_field()
			if tf and tf != "name" and hasattr(doc, tf):
				title = fmt(doc.get(tf), meta.get_field(tf), doc)
		except Exception:
			title = ""
	return {"kind": "update", "doctype": doctype, "name": name, "title": title,
			"diff": diff}


def _bulk_update_card(args: dict, updates) -> dict | None:
	"""Per-record from->to diff for a batch ``update_doc(updates=[{name, changes}])``.

	Each rendered record's OLD values come from its current (post-rollback) doc,
	permission-CHECKED then perm-filtered so a restricted field never leaks; the
	NEW values are the caller's requested ``changes``. No-op fields are dropped
	(comparing the values the SAVE would store, never their display forms - see
	``same_value``: fmt_money renders 100.005 and 100.001 identically, so a display
	compare would drop a real change from the card), permlevel-restricted
	fields are skipped (the confirmed save would silently drop them - mirrors
	_update_card's ``would`` guard), and secret / Password values are masked. Only
	the first ``_MAX_ROWS`` records are rendered - each costs one doc read - and the
	rest ride ``extra`` (the raw payload under Details still lists every name).
	``varying`` flags a heterogeneous batch (the requested changes differ across
	records). Each record also carries the changed field labels for its row."""
	doctype = args.get("doctype")
	meta = _meta(doctype)
	first = updates[0].get("changes") if isinstance(updates[0], dict) else None
	varying = any(isinstance(u, dict) and u.get("changes") != first for u in updates)
	records = []
	for u in updates[:_MAX_ROWS]:
		if not isinstance(u, dict):
			continue
		name = u.get("name")
		changes = u.get("changes") if isinstance(u.get("changes"), dict) else {}
		# OLD from the current doc (the park dry-run rolled back), perm-filtered so a
		# restricted field's old value never leaks - same guard as _update_card.
		old, loaded = {}, False
		try:
			doc = frappe.get_doc(doctype, name)
			# get_doc checks NO permission (document.py:141-145 -> :336-349 defaults
			# check_permission to None) and the fieldlevel filter is permlevel-only.
			if not doc.has_permission("read"):
				raise frappe.PermissionError
			doc.apply_fieldlevel_read_permissions()
			old = doc.as_dict()
			loaded = True
		except Exception:
			frappe.clear_messages()
			old = {}
		diff, fields = [], []
		for key in list(changes)[: _MAX_ROWS * 2]:  # over-scan so no-ops don't eat slots
			# A field the user cannot read at their permlevel is delattr'd from the
			# perm-filtered doc; the confirmed save silently skips it too, so don't
			# show a phantom change (mirrors _update_card's ``key not in would``).
			if loaded and key not in old:
				continue
			cdf = meta.get_field(key) if meta else None
			if same_value(old.get(key), changes.get(key), cdf):
				continue  # the save would not change the stored value
			from_s, to_s = fmt(old.get(key), cdf, doc if loaded else None), fmt(changes.get(key), cdf)
			if is_secret(meta, key):
				from_s = to_s = "[hidden]"  # never render a password / secret value
			label = _label(meta, key)
			fields.append(label)
			diff.append({"label": label, "from": from_s, "to": to_s})
			if len(diff) >= _MAX_ROWS:
				break
		row_title = ""
		if loaded and meta:
			try:
				tf = meta.get_title_field()
				if tf and tf != "name" and hasattr(doc, tf):
					row_title = fmt(doc.get(tf), meta.get_field(tf), doc)
			except Exception:
				row_title = ""
		records.append({"name": name, "title": row_title, "fields": fields, "diff": diff})
	if not records:
		return None
	return {
		"kind": "bulk_update", "doctype": doctype, "count": len(updates),
		"records": records, "extra": max(0, len(updates) - len(records)),
		"varying": varying,
	}


def _batch_create_card(would) -> dict | None:
	if not isinstance(would, dict) or not isinstance(would.get("created"), list):
		return None
	created = would["created"]
	rows = [
		{"doctype": d.get("doctype"), "name": d.get("name")}
		for d in created[:_MAX_ROWS] if isinstance(d, dict)
	]
	notes = [str(n) for n in (would.get("notes") or []) if str(n or "").strip()]
	return {
		"kind": "batch_create", "count": len(created), "rows": rows,
		"extra": max(0, len(created) - len(rows)), "notes": notes[:_MAX_ROWS],
	}


def _target_name(item):
	if isinstance(item, dict):
		return item.get("name") or item.get("recipients") or item.get("doctype")
	return item


def _verb_records(doctype, names) -> list[dict]:
	"""A summary per target, capped. ``summary_rows`` returns None for a record that
	is MISSING or that the caller cannot READ - both degrade to name-only, and they
	must stay indistinguishable so the card is not an existence oracle. The title
	only ever comes from summary_rows' permission-checked path.
	"""
	out = []
	for name in names[:_MAX_ROWS]:
		summary = summary_rows(doctype, name) if doctype and name else None
		out.append({
			"name": name,
			"title": summary["title"] if summary else "",
			"rows": summary["rows"] if summary else [],
		})
	return out


def _verb_card(tool: str, args: dict, bulk_items) -> dict:
	verb = _VERB[tool]
	doctype = args.get("doctype")
	action = args.get("action") or ""  # apply_workflow_action only
	if bulk_items:
		targets = [t for t in (_target_name(x) for x in bulk_items[:_MAX_ROWS]) if t]
		return {
			"kind": "verb", "verb": verb, "action": action, "doctype": doctype,
			"count": len(bulk_items), "targets": targets,
			"extra": max(0, len(bulk_items) - len(targets)),
			"records": _verb_records(doctype, targets),
		}
	targets = [args["name"]] if args.get("name") else []
	return {
		"kind": "verb", "verb": verb, "action": action, "doctype": doctype,
		"count": 1, "targets": targets, "extra": 0,
		"records": _verb_records(doctype, targets),
	}


def _email_card(args: dict) -> dict | None:
	if isinstance(args.get("messages"), list):
		return None  # bulk mail-merge: the summary's count is clearer than one body
	to = args.get("recipients") or args.get("to") or ""
	if isinstance(to, list):
		to = ", ".join(str(x) for x in to)
	return {
		"kind": "email", "to": fmt(to), "subject": fmt(args.get("subject") or ""),
		"body": fmt(args.get("content") or args.get("message") or ""),
	}


def _method_card(args: dict) -> dict:
	inner = args.get("args") if isinstance(args.get("args"), dict) else {}
	shown = {}
	for k, v in list(inner.items())[:_MAX_ROWS]:
		# No meta for a run_method arg bag, so this is the key-name check only.
		shown[str(k)] = "[hidden]" if is_secret(None, k) else fmt(v)
	return {"kind": "method", "method": fmt(args.get("method") or ""), "args": shown}
