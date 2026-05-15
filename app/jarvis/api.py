import json

import frappe

from jarvis.exceptions import JarvisError
from jarvis.tools.registry import dispatch


@frappe.whitelist()
def call_tool(tool: str, args: dict | str | None = None) -> dict:
    """Whitelisted entry point for tool dispatch.

    Returns a {ok, data} envelope on success or {ok: False, error: {code, message}} on failure.
    The calling user is whoever Frappe's session resolves to; that user's permissions are
    what the tool sees.
    """
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError as e:
            return _error("InvalidArgumentError", f"args is not valid JSON: {e}")
    args = args or {}

    try:
        data = dispatch(tool, args)
    except JarvisError as e:
        return _error(type(e).__name__, str(e))
    except frappe.PermissionError as e:
        return _error("PermissionDeniedError", str(e) or "permission denied")

    return {"ok": True, "data": data}


def _error(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}
