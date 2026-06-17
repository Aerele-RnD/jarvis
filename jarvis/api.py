import json

import frappe

from jarvis._http import validate_bearer as _validate_bearer  # noqa: F401 (kept for callers in mcp.py)
from jarvis._plugin_auth import PluginAuthError, validate_plugin_request
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

	   - ``X-Jarvis-Token`` - the shared ``agent_token`` secret
	     (proves the request originated inside the openclaw container)
	   - ``X-Jarvis-Session`` - the openclaw sessionKey for this conversation

	   The token is validated, then the user is resolved from
	   ``Jarvis Chat Session`` (the row inserted at session-create time maps
	   sessionKey → Frappe user). Dispatch runs under that user via
	   ``frappe.set_user``. The original session user is restored after.

	Returns ``{ok: True, data: ...}`` on success or
	``{ok: False, error: {code, message}}`` on tool-level error. Auth
	failures are reported with the corresponding HTTP status code.
	"""
	# Plugin auth mode - detected by presence of X-Jarvis-Token header.
	# Goes through the C2 hardening pipeline (IP allowlist → bearer →
	# session → optional HMAC signature → rate limit) implemented in
	# jarvis._plugin_auth. PluginAuthError carries the correct status
	# code; any other exception bubbles as a 500 (logged by Frappe).
	if _get_header("X-Jarvis-Token"):
		try:
			session_key = validate_plugin_request(_request_body_bytes())
		except PluginAuthError as e:
			frappe.local.response.http_status_code = e.http_status
			return _error(e.code, e.message)

		plugin_user = frappe.db.get_value(
			"Jarvis Chat Session",
			{"session_key": session_key},
			"user",
		)
		if not plugin_user:
			frappe.local.response.http_status_code = 400
			return _error(
				"InvalidArgumentError",
				f"unknown session: {session_key}",
			)
		if not frappe.db.exists("User", plugin_user):
			frappe.local.response.http_status_code = 400
			return _error(
				"InvalidArgumentError",
				f"session references unknown user: {plugin_user}",
			)

		# C2 stretch (2026-06-16 review): bind session_key -> bench's
		# device_id at session-create time, verify on every call. If the
		# bench has re-paired since this session was created (operator
		# rotation, incident response, etc.) the snapshot won't match
		# the current device_id and we reject. Bounds leaked-session
		# replay to "until the next re-pair."
		#
		# Backwards-compat (two-fold):
		#   1. A row without ``chat_device_id`` (pre-migration row from
		#      before this column was added) passes through.
		#   2. A bench whose Jarvis Chat Session DocType hasn't picked up
		#      the new column yet (pre-bench-migrate state) also passes
		#      through - we tolerate the AttributeError-ish read failure
		#      so call_tool doesn't 500 on the first call after a deploy.
		# Once everyone is migrated the strict check applies uniformly.
		try:
			row_device = (frappe.db.get_value(
				"Jarvis Chat Session",
				{"session_key": session_key},
				"chat_device_id",
			) or "").strip()
		except Exception:
			row_device = ""
		if row_device:
			current_device = (
				frappe.db.get_single_value("Jarvis Settings", "chat_device_id") or ""
			).strip()
			if current_device and row_device != current_device:
				frappe.local.response.http_status_code = 401
				return _error(
					"AuthenticationError",
					"session is bound to a previous device pairing; "
					"the bench has re-paired since this session was issued",
				)

		return _dispatch_from_session(plugin_user, session_key, tool, args)

	# Standard Frappe auth path - Guest is rejected; everything else dispatches
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


def _dispatch_from_session(
	user: str,
	session_key: str,
	tool: str,
	args: dict | str | None,
) -> dict:
	"""Run the dispatch under ``user``, then attribute the tool call to the
	chat session so the UI sees it.
	"""
	original = frappe.session.user
	frappe.set_user(user)
	try:
		args_parsed = _parse_args(args)
		if not isinstance(args_parsed, dict):
			return args_parsed  # already an error envelope
		result = _dispatch_safe(tool, args_parsed)
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
			args = json.loads(args)
		except json.JSONDecodeError as e:
			return _error("InvalidArgumentError", f"args is not valid JSON: {e}")
	args = args or {}
	# Defensive: strip LLM-hallucinated "_user" / "_session" fields. The
	# old MCP design used them as in-band identity carriers; Path A moved
	# identity to HTTPS headers. If the LLM has been trained on the older
	# convention it may emit these even though our tool schemas don't list
	# them - dropping them silently keeps such calls dispatching cleanly.
	if isinstance(args, dict):
		for legacy in ("_user", "_session", "_session_key"):
			args.pop(legacy, None)
	return args


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


def _request_body_bytes() -> bytes:
	"""Best-effort raw request body for HMAC validation.

	Returns b"" in direct-Python contexts (tests, ``bench execute``)
	where ``frappe.request`` isn't bound. Phase-2 signed clients can
	then either skip the signature in tests or use the test harness's
	header-faking shape; an unsigned legacy request returns b"" which
	doesn't matter because the signature path isn't entered.
	"""
	try:
		data = frappe.request.get_data(cache=True)
	except (AttributeError, RuntimeError):
		return b""
	return data if isinstance(data, (bytes, bytearray)) else (data or "").encode("utf-8")


@frappe.whitelist(methods=["POST"])
def rotate_agent_token() -> dict:
	"""Rotate the plugin agent_token (C2 PR-3C orchestrator).

	System Manager only. Generates a fresh 32-byte random token,
	pushes it via admin -> fleet-agent -> container env, and only
	persists locally after admin confirms the container is healthy
	against the new value. This keeps the bench's notion of the
	token in lockstep with what the container holds: a mid-rotation
	failure leaves both ends on the OLD token.

	Operators run this after a suspected leak or as routine hygiene.
	The container is briefly unavailable (~10-30s) during the
	``compose up -d`` recreate that the fleet-agent runs.

	Returns:
	  {"ok": true, "data": {"rotated_at": "<isoformat>"}} on success
	  {"ok": false, "error": {"code": ..., "message": ...}} on any failure;
	      old token is preserved on the bench; admin's response carries
	      the precise failure code (NoRunningTenant 409, RateLimited 429,
	      etc.)

	The old token stops working on the container as soon as the
	recreate completes; legitimate in-flight plugin requests presenting
	the old token will start hitting 401 from the bench (the new
	token doesn't match) AND from the container's plugin (the new
	JARVIS_GATEWAY_TOKEN doesn't match what the plugin remembers).
	Both sides re-sync naturally on the next call.
	"""
	import secrets

	# Block non-System-Manager callers explicitly. allow_guest defaults
	# to False; this is defense-in-depth against a future @whitelist
	# expansion shipping with relaxed defaults.
	frappe.only_for("System Manager")

	new_token = secrets.token_hex(32)  # 64 hex chars

	# Push to admin FIRST. We only persist locally after admin confirms
	# the container is healthy against the new value. If admin fails,
	# the bench's stored token is unchanged - the container also still
	# holds the old token (fleet-agent rolled back per PR-3A), so both
	# ends stay in lockstep.
	from jarvis import admin_client
	try:
		admin_client.post_rotate_agent_token(new_token=new_token)
	except admin_client.AdminAuthError as e:
		frappe.local.response.http_status_code = 502
		return {"ok": False, "error": {
			"code": "AdminAuthError",
			"message": f"admin rejected our credentials: {e}",
		}}
	except admin_client.AdminUnreachableError as e:
		frappe.local.response.http_status_code = 502
		return {"ok": False, "error": {
			"code": "AdminUnreachableError",
			"message": f"admin not reachable: {e}",
		}}
	except admin_client.AdminRateLimitedError as e:
		frappe.local.response.http_status_code = 429
		return {"ok": False, "error": {
			"code": "RateLimitExceeded",
			"message": "admin rate-limit hit; retry later",
			"retry_after_seconds": e.retry_after_seconds,
		}}
	except admin_client.AdminValidationError as e:
		# Admin raised a Frappe ValidationError - typically a 4xx input
		# problem the operator can fix (e.g. malformed token; though our
		# token comes from secrets.token_hex so that's unlikely here).
		frappe.local.response.http_status_code = 400
		return {"ok": False, "error": {
			"code": "AdminValidationError",
			"message": str(e),
		}}
	except Exception as e:
		frappe.local.response.http_status_code = 502
		frappe.log_error(
			title="rotate_agent_token: unexpected admin failure",
			message=frappe.get_traceback(),
		)
		return {"ok": False, "error": {
			"code": type(e).__name__,
			"message": f"unexpected error during rotation: {e}",
		}}

	# Admin succeeded -> the container is now running against new_token.
	# Persist it locally so the bench's future plugin-auth validations
	# match what the container holds.
	settings = frappe.get_single("Jarvis Settings")
	settings.db_set("agent_token", new_token)
	frappe.db.commit()

	return {"ok": True, "data": {"rotated_at": frappe.utils.now()}}
