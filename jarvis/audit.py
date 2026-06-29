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
        doctype, name = _ref(args, result)
        entry = {
            "ts": frappe.utils.now(),
            "user": getattr(frappe.session, "user", None),
            "tool": tool,
            "doctype": doctype,
            "name": name,
            "status": "ok" if ok else "error",
            "error_code": error_code,
            "error_message": (error_message or "")[:500] or None,
            "args": _scrub(args),
        }
        frappe.logger("jarvis.tool_audit").info(json.dumps(entry, default=str))
    except Exception:
        try:
            frappe.logger("jarvis.tool_audit").error("audit record failed")
        except Exception:
            pass


def _ref(args, result):
    a = args or {}
    doctype = a.get("doctype")
    name = a.get("name") or a.get("docname")
    if isinstance(result, dict):
        doctype = doctype or result.get("doctype")
        name = name or result.get("name")
    return doctype, name


def _scrub(args):
    """Redact secret-shaped values; cap total size so a giant payload can't
    bloat the log."""
    if not isinstance(args, dict):
        return args
    out = {}
    for k, v in args.items():
        if k.lower() in _SECRET_KEYS:
            out[k] = "[REDACTED]"
        elif isinstance(v, dict):
            out[k] = _scrub(v)
        else:
            out[k] = v
    rendered = json.dumps(out, default=str)
    return out if len(rendered) <= _MAX_ARGS_CHARS else {"_truncated": rendered[:_MAX_ARGS_CHARS]}
