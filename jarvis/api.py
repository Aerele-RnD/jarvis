import json

import frappe

from jarvis._http import raw_json_response as _raw_json_response
from jarvis._http import validate_bearer as _validate_bearer
from jarvis.exceptions import JarvisError
from jarvis.tools.registry import dispatch


@frappe.whitelist(allow_guest=True, methods=["POST"])
def call_tool(tool: str, args: dict | str | None = None) -> dict:
	"""Whitelisted entry point for Jarvis tool dispatch.

	Two authentication modes are supported:

	1. **Standard Frappe auth** (external callers): session cookie or
	   ``Authorization: token <api_key>:<api_secret>``. The calling user is
	   whoever Frappe's session resolves to; their permissions are what the
	   tool sees. Guest is rejected.

	2. **Plugin auth** (``jarvis-openclaw-plugin`` Path A): two custom headers
	   are presented together:

	   - ``X-Jarvis-Token`` — the shared ``openclaw_gateway_token`` secret
	   - ``X-Jarvis-User`` — the Frappe user to dispatch as

	   When both headers are present the token is validated, the user is
	   verified to exist, and dispatch runs under that user via
	   ``frappe.set_user``. The original session user is restored after
	   dispatch.

	Returns ``{ok: True, data: ...}`` on success or
	``{ok: False, error: {code, message}}`` on tool-level error. Auth
	failures are reported with the corresponding HTTP status code.
	"""
	# Plugin auth mode — detected by presence of X-Jarvis-Token header.
	if _get_header("X-Jarvis-Token"):
		if not _validate_bearer():
			frappe.local.response.http_status_code = 401
			return _error("AuthenticationError", "invalid X-Jarvis-Token")

		plugin_user = _get_header("X-Jarvis-User")
		if not plugin_user:
			frappe.local.response.http_status_code = 400
			return _error(
				"InvalidArgumentError",
				"X-Jarvis-User header required when using X-Jarvis-Token",
			)
		if not frappe.db.exists("User", plugin_user):
			frappe.local.response.http_status_code = 400
			return _error("InvalidArgumentError", f"unknown user: {plugin_user}")

		return _dispatch_as_user(plugin_user, tool, args)

	# Standard Frappe auth path — Guest is rejected; everything else dispatches
	# under the current Frappe session user.
	if frappe.session.user == "Guest":
		frappe.local.response.http_status_code = 401
		return _error("AuthenticationError", "authentication required")

	return _dispatch_current_user(tool, args)


def _dispatch_current_user(tool: str, args: dict | str | None) -> dict:
	args = _parse_args(args)
	if isinstance(args, dict):
		return _dispatch_safe(tool, args)
	return args  # already an error envelope


def _dispatch_as_user(user: str, tool: str, args: dict | str | None) -> dict:
	original = frappe.session.user
	frappe.set_user(user)
	try:
		args_parsed = _parse_args(args)
		if not isinstance(args_parsed, dict):
			return args_parsed  # already an error envelope
		result = _dispatch_safe(tool, args_parsed)

		# If the plugin signalled a chat session, surface the tool call
		# (args + result + status) to the chat UI.
		session_key = _get_header("X-Jarvis-Session")
		if session_key:
			_persist_and_publish_tool_call(
				session_key=session_key,
				tool=tool,
				args=args_parsed,
				result=result,
			)
		return result
	finally:
		frappe.set_user(original)


def _persist_and_publish_tool_call(
	*,
	session_key: str,
	tool: str,
	args: dict,
	result: dict,
) -> None:
	"""Persist a Jarvis Chat Message (role=tool) and publish a realtime event.

	Best-effort: if no conversation owns this session_key, return silently.
	"""
	conv_name = frappe.db.get_value("Jarvis Conversation", {"session_key": session_key}, "name")
	if not conv_name:
		return
	status = "completed" if result.get("ok") else "error"

	# Run as the conversation owner so DocType perms allow it
	conv_owner = frappe.db.get_value("Jarvis Conversation", conv_name, "owner")
	original = frappe.session.user
	frappe.set_user(conv_owner)
	try:
		from jarvis.chat.api import _next_seq
		seq = _next_seq(conv_name)
		doc = frappe.get_doc({
			"doctype": "Jarvis Chat Message",
			"conversation": conv_name,
			"seq": seq,
			"role": "tool",
			"tool_name": tool,
			"tool_args": frappe.as_json(args),
			"tool_result": frappe.as_json(result),
			"tool_status": status,
			"content": f"{tool} → {status}",
		})
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		publish_realtime_tool_result(
			user=conv_owner,
			conversation_id=conv_name,
			tool_message_id=doc.name,
			tool_name=tool,
			args=args,
			result=result,
			status=status,
		)
	finally:
		frappe.set_user(original)


def publish_realtime_tool_result(
	*,
	user: str,
	conversation_id: str,
	tool_message_id: str,
	tool_name: str,
	args: dict,
	result: dict,
	status: str,
) -> None:
	"""Wrapper around frappe.publish_realtime so tests can mock at this seam."""
	frappe.publish_realtime(
		"jarvis:event",
		{
			"kind": "tool:result",
			"conversation_id": conversation_id,
			"tool_message_id": tool_message_id,
			"tool_name": tool_name,
			"args": args,
			"result": result,
			"status": status,
		},
		user=user,
	)


def _parse_args(args: dict | str | None) -> dict:
	if isinstance(args, str):
		try:
			return json.loads(args)
		except json.JSONDecodeError as e:
			return _error("InvalidArgumentError", f"args is not valid JSON: {e}")
	return args or {}


def _dispatch_safe(tool: str, args: dict) -> dict:
	try:
		data = dispatch(tool, args)
	except JarvisError as e:
		return _error(type(e).__name__, str(e))
	except frappe.PermissionError as e:
		return _error("PermissionDeniedError", str(e) or "permission denied")
	return {"ok": True, "data": data}


def _error(code: str, message: str) -> dict:
	return {"ok": False, "error": {"code": code, "message": message}}


def _get_header(name: str) -> str:
	"""Read a request header, returning empty string when no request is bound.

	``frappe.request`` is an unbound LocalProxy in direct-Python contexts
	(unit tests, ``bench execute``), so accessing attributes on it raises
	``RuntimeError``. We tolerate that and treat absent headers as empty.
	"""
	try:
		value = frappe.request.headers.get(name)
	except (AttributeError, RuntimeError):
		return ""
	return (value or "").strip()


@frappe.whitelist(allow_guest=True, methods=["POST"])
def lookup_user_by_session():
	"""Map an openclaw sessionKey to its owning Frappe user.

	Called by ``jarvis-openclaw-plugin`` from each tool factory's execute
	function to discover which user a tool call should run as. Auth via the
	shared ``X-Jarvis-Token`` bearer secret.

	Request body (JSON): ``{"session_key": "<key>"}``
	Response (200):      ``{"user": "<frappe_user_email>"}``
	Error responses:     ``{"error": "<reason>"}`` with the appropriate HTTP
	status code.
	"""
	if not _validate_bearer():
		return _raw_json_response({"error": "unauthorized"}, status_code=401)

	try:
		body = frappe.request.get_json(force=True)
	except Exception:
		return _raw_json_response({"error": "invalid json"}, status_code=400)

	session_key = body.get("session_key") if isinstance(body, dict) else None
	if not session_key:
		return _raw_json_response({"error": "session_key required"}, status_code=400)

	user = frappe.db.get_value("Jarvis Chat Session", {"session_key": session_key}, "user")
	if not user:
		return _raw_json_response({"error": "unknown session"}, status_code=404)

	return _raw_json_response({"user": user})
