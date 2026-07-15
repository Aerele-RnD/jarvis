"""Build the render-ready "what will change" summary for a confirmation card (F9).

The write-safety gate (``jarvis.api._run_tool``) parks a gated write and shows the
user a card. Today that card renders a raw-JSON dump of the dry-run ``would`` doc
and a one-line ``_describe_call`` target string - it names the record but not what
the write does to it. ``build_card`` turns the tool + args + park-time preview into
a structured, human-readable summary the SPA renders like the model-authored draft
card (a field list for a create, a from->to diff for an update, a verb line for
submit/cancel/delete/amend, to/subject/body for an email, method + args for
run_method).

It is attached ONCE at park as ``preview["card"]`` (see the gate). Phase-1 F2 stores
the park-time preview in the token record and the resync endpoint returns it
verbatim, so the card rides the ``action:pending`` event, the record, and every
resync identically - it is never rebuilt at resync (which would let it diverge from
the stored preview and re-load the doc on each reconnect).

Safety: values come from the ALREADY perm-filtered ``would`` (create/update tools
call ``apply_fieldlevel_read_permissions`` before returning), and the update
``from`` values are read from a freshly-fetched, perm-filtered current doc - so a
restricted field's value never lands in the card. Long values are truncated, rows
capped, and obviously-secret ``run_method`` arg keys masked. The card carries no
material the owner would not already see in the post-confirm receipt.

Returns ``None`` for tool shapes without a bespoke card (share_doc, assign_to,
create_custom_skill, update_wiki, bulk update/email, and any token minted before
this existed) - the SPA falls back to the summary + raw-preview rendering.
"""

from __future__ import annotations

import re

import frappe

_MAX_VAL = 200  # truncate a single displayed value to this many chars
_MAX_ROWS = 20  # cap fields / diff rows / batch bullets / targets shown
_BULK_KEYS = ("names", "updates", "docs", "messages")
_SECRET_KEY_RE = re.compile(r"password|secret|token|api[_-]?key", re.IGNORECASE)

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


def _fmt(value) -> str:
	"""A scalar as a short display string; a child-table list -> "N rows"."""
	if isinstance(value, list):
		return f"{len(value)} row{'' if len(value) == 1 else 's'}"
	if isinstance(value, dict):
		return "..."
	s = "" if value is None else str(value)
	return s if len(s) <= _MAX_VAL else s[: _MAX_VAL - 1] + "…"


def _create_card(args: dict, would) -> dict:
	doctype = args.get("doctype")
	values = args.get("values") if isinstance(args.get("values"), dict) else {}
	meta = _meta(doctype)
	rows = []
	for key in list(values)[: _MAX_ROWS * 2]:
		# Perm guard: only show a field that survived the resolved doc's
		# field-level read-permission filter.
		if isinstance(would, dict) and key not in would:
			continue
		val = would.get(key) if isinstance(would, dict) else values.get(key)
		if val is None or (not isinstance(val, list) and str(val).strip() == ""):
			continue
		rows.append({"label": _label(meta, key), "value": _fmt(val)})
		if len(rows) >= _MAX_ROWS:
			break
	name = would.get("name") if isinstance(would, dict) else None
	return {"kind": "create", "doctype": doctype, "name": name, "rows": rows}


def _update_card(args: dict, would) -> dict:
	doctype = args.get("doctype")
	name = args.get("name")
	changes = args.get("changes") if isinstance(args.get("changes"), dict) else {}
	meta = _meta(doctype)
	# OLD values from the current doc (the park dry-run rolled back, so the DB is
	# back to the pre-update state), perm-filtered so a restricted field's old
	# value never leaks. NEW values from ``would`` (already perm-filtered +
	# normalized by the tool).
	old = {}
	try:
		doc = frappe.get_doc(doctype, name)
		doc.apply_fieldlevel_read_permissions()
		old = doc.as_dict()
	except Exception:
		old = {}
	diff = []
	for key in list(changes)[: _MAX_ROWS * 2]:
		if isinstance(would, dict) and key not in would:
			continue  # not perm-visible in the resolved doc
		to_val = would.get(key) if isinstance(would, dict) else changes.get(key)
		from_val = old.get(key)
		if from_val == to_val:
			continue  # normalized to a no-op
		diff.append({
			"label": _label(meta, key), "from": _fmt(from_val), "to": _fmt(to_val)})
		if len(diff) >= _MAX_ROWS:
			break
	return {"kind": "update", "doctype": doctype, "name": name, "diff": diff}


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
		}
	return {
		"kind": "verb", "verb": verb, "action": action, "doctype": doctype,
		"count": 1, "targets": [args["name"]] if args.get("name") else [], "extra": 0,
	}


def _email_card(args: dict) -> dict | None:
	if isinstance(args.get("messages"), list):
		return None  # bulk mail-merge: the summary's count is clearer than one body
	to = args.get("recipients") or args.get("to") or ""
	if isinstance(to, list):
		to = ", ".join(str(x) for x in to)
	return {
		"kind": "email", "to": _fmt(to), "subject": _fmt(args.get("subject") or ""),
		"body": _fmt(args.get("content") or args.get("message") or ""),
	}


def _method_card(args: dict) -> dict:
	inner = args.get("args") if isinstance(args.get("args"), dict) else {}
	shown = {}
	for k, v in list(inner.items())[:_MAX_ROWS]:
		shown[str(k)] = "[hidden]" if _SECRET_KEY_RE.search(str(k)) else _fmt(v)
	return {"kind": "method", "method": _fmt(args.get("method") or ""), "args": shown}
