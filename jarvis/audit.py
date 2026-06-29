"""Structured audit logging for mutating tool calls.

Every write tool dispatched through ``jarvis.api._run_tool`` is logged here
- who / what / when / result - to the ``jarvis.tool_audit`` logger. We use a
dedicated structured logger rather than a DocType insert on purpose: it is
transaction-safe (it never entangles or partially commits the tool's own DB
transaction, and a failed write can't leave a dangling audit row), and it
never raises into the tool path. A queryable DocType sink can be layered on
later by swapping the body of ``record`` for a doc insert.
"""
import json

import frappe

# Secret-shaped keys scrubbed from the logged args summary.
_SECRET_KEYS = {
    "password", "new_password", "pwd", "api_key", "api_secret", "secret",
    "token", "access_token", "refresh_token", "key",
}
_MAX_ARGS_CHARS = 2000


def record(*, tool: str, args: dict | None, ok: bool,
           error_code: str | None = None, error_message: str | None = None,
           result=None) -> None:
    """Emit one structured audit line for a mutating tool call.

    Best-effort: never raises (audit must not break or fail the tool)."""
    try:
        doctype, name, method = _ref(args, result)
        scrubbed = _scrub(args)
        rendered = json.dumps(scrubbed, default=str)
        if len(rendered) > _MAX_ARGS_CHARS:
            scrubbed = {"_truncated": rendered[:_MAX_ARGS_CHARS]}
        entry = {
            "ts": frappe.utils.now(),
            "user": getattr(frappe.session, "user", None),
            "tool": tool,
            "doctype": doctype,
            "name": name,
            "method": method,
            "status": "ok" if ok else "error",
            "error_code": error_code,
            "error_message": (error_message or "")[:500] or None,
            "args": scrubbed,
        }
        frappe.logger("jarvis.tool_audit").info(json.dumps(entry, default=str))
    except Exception:
        try:
            frappe.logger("jarvis.tool_audit").error("audit record failed")
        except Exception:
            pass


def _ref(args, result):
    """Best-effort (doctype, name, method) for the audited target. Covers the
    common arg names across the write tools - doctype/name plus attach_to_doc's
    target_doctype/target_name and run_method's method - and falls back to the
    returned doc when the args don't name it."""
    a = args if isinstance(args, dict) else {}
    doctype = a.get("doctype") or a.get("target_doctype")
    name = a.get("name") or a.get("docname") or a.get("target_name")
    method = a.get("method")
    if isinstance(result, dict):
        doctype = doctype or result.get("doctype")
        name = name or result.get("name")
    return doctype, name, method


def _scrub(value):
    """Recursively redact secret-shaped keys in dicts, including dicts nested in
    lists (e.g. child-table rows like values={"users":[{"password":...}]}).
    Non-collection values pass through. Size-capping is applied once by the
    caller after the whole structure is scrubbed."""
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if k.lower() in _SECRET_KEYS else _scrub(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value
