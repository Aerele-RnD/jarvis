import json

import frappe

from jarvis._http import validate_bearer as _validate_bearer  # noqa: F401 (kept for callers in mcp.py)
from jarvis._plugin_auth import PluginAuthError, validate_plugin_request
from jarvis.exceptions import InvalidArgumentError, JarvisError
from jarvis.tools.registry import dispatch
from jarvis import audit


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
	# Goes through the C2 hardening pipeline (bearer → session →
	# optional HMAC signature → rate limit) implemented in
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
			# Self-hosted benches chat over openclaw's HTTP transport, which
			# creates no Jarvis Chat Session row. The gateway token was already
			# validated above (proving the call came from the configured
			# openclaw), so run the tool as the configured self-host tool user
			# - a self-hosted bench is single-tenant.
			from jarvis import selfhost
			if selfhost.is_self_hosted():
				plugin_user = _selfhost_tool_user()
				if not plugin_user:
					# Self-hosted, but the tool user is unset (or names a user
					# that no longer exists). Fail with a clear, fixable
					# message instead of the opaque "unknown session" below.
					frappe.local.response.http_status_code = 400
					return _error(
						"ConfigurationError",
						"self-hosted tool user is not configured. Set "
						"'Self-Host Tool User' in Jarvis Settings to a "
						"non-admin Frappe user so ERP tools can run.",
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


def _selfhost_tool_user() -> str | None:
	"""User that plugin tool calls run under in self-hosted mode.

	Self-hosted openclaw uses the HTTP transport, which has no Jarvis Chat
	Session → user mapping. The gateway token (X-Jarvis-Token) was already
	validated, so we run tools as the configured self-host tool user (the
	bench is single-tenant). Returns None when not self-hosted, unset, or the
	configured user is not a usable tool user.
	"""
	from jarvis import selfhost
	if not selfhost.is_self_hosted():
		return None
	s = frappe.get_single("Jarvis Settings")
	user = (getattr(s, "selfhost_tool_user", "") or "").strip()
	# Authoritative guard: the selfhost_tool_user Link field can be edited
	# directly on Jarvis Settings (bypassing save_self_hosted's validation), so
	# enforce the invariant HERE - never run jarvis__* tools as Administrator
	# (bypasses all DocType perms), Guest, or a missing/disabled user, however
	# the field was set. get_value("enabled") is None for missing, 0 for disabled.
	if (user and user not in ("Guest", "Administrator")
			and frappe.db.get_value("User", user, "enabled")):
		return user
	return None


def _dispatch_current_user(tool: str, args: dict | str | None) -> dict:
	return _run_tool(tool, args)


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
		# Parse args up front so persist_and_publish gets the same
		# dict shape the tool ran against (or the empty dict on a
		# malformed-args rejection).
		try:
			parsed_args = _parse_args(args)
		except InvalidArgumentError as e:
			result = _error("InvalidArgumentError", str(e))
			_persist_and_publish_tool_call(
				session_key=session_key, tool=tool, args={}, result=result,
			)
			return result
		# Pass the already-parsed dict back through _run_tool. _run_tool's
		# _parse_args call is idempotent on dicts (no JSON parse path,
		# legacy-marker strip is also idempotent), so no double-work.
		result = _run_tool(tool, parsed_args)
		_persist_and_publish_tool_call(
			session_key=session_key, tool=tool, args=parsed_args, result=result,
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
		# Self-hosted: the openclaw HTTP session key isn't linked to a
		# conversation. Attribute the tool call to the in-flight self-host
		# turn (keyed by the tool user = current dispatch user) so the UI
		# renders the tool card like managed mode. get_active_turn returns
		# None when 2+ turns are concurrently active for the tool user, so an
		# ambiguous tool call is dropped rather than mis-filed into - and
		# realtime-leaked to - the wrong conversation.
		from jarvis import selfhost
		turn = selfhost.get_active_turn(frappe.session.user) if selfhost.is_self_hosted() else None
		conv_name = (turn or {}).get("conversation")
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
		# Generation: if the tool produced a file artifact (download_pdf,
		# export_excel, …), attach it to the in-flight assistant message's
		# canvas field + publish a canvas event so it renders inline — the
		# same surface the agent's own canvas files use.
		_maybe_attach_artifact(conv_name, conv_owner, result)
	finally:
		frappe.set_user(original)


def _maybe_attach_artifact(conv_name: str, user: str, result: dict) -> None:
	"""Attach a tool-produced file artifact ({file_url, filename, …}) to the
	current assistant message's ``canvas`` field and publish a canvas event so
	the chat renders it (PDF/image inline, xlsx/other as a download card)."""
	if not isinstance(result, dict) or not result.get("ok"):
		return
	data = result.get("data")
	if not isinstance(data, dict):
		return
	file_url = data.get("file_url")
	filename = data.get("filename") or data.get("file_name")
	if not file_url or not filename:
		return

	from jarvis.chat import canvas as canvas_mod

	typ = canvas_mod._type_for(filename)
	item = {
		"name": filename,
		"title": data.get("title") or canvas_mod._title_for(filename, None, typ),
		"type": typ, "file_url": file_url,
	}
	MSG = "Jarvis Chat Message"
	# Prefer the in-flight (streaming) assistant message; fall back to the latest.
	rows = frappe.get_all(
		MSG, filters={"conversation": conv_name, "role": "assistant", "streaming": 1},
		order_by="seq desc", limit=1, pluck="name",
	) or frappe.get_all(
		MSG, filters={"conversation": conv_name, "role": "assistant"},
		order_by="seq desc", limit=1, pluck="name",
	)
	if not rows:
		return
	msg_name = rows[0]
	existing = frappe.db.get_value(MSG, msg_name, "canvas")
	items = frappe.parse_json(existing) if existing else []
	if not isinstance(items, list):
		items = []
	if any(i.get("file_url") == file_url for i in items):
		return  # already attached
	items.append(item)
	frappe.db.set_value(MSG, msg_name, "canvas", frappe.as_json(items))
	frappe.db.commit()
	frappe.publish_realtime(
		"jarvis:event",
		{"kind": "canvas", "conversation_id": conv_name, "message_id": msg_name, "items": items},
		user=user,
	)


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
	"""Decode the args input into a dict + strip legacy identity markers.

	Raises ``InvalidArgumentError`` (a JarvisError subclass) on JSON
	parse failure - that mirrors what tools raise for malformed input
	and lets ``_run_tool`` translate it via the same path. The previous
	shape returned either a dict OR an error envelope dict, which made
	every caller branch on the result type.
	"""
	if isinstance(args, str):
		try:
			args = json.loads(args)
		except json.JSONDecodeError as e:
			raise InvalidArgumentError(f"args is not valid JSON: {e}")
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


# Mutating tools: audited on every call, and the only tools that accept
# ``preview`` (a dry-run with every DB write rolled back).
_WRITE_TOOLS = frozenset({
	"create_doc", "update_doc", "submit_doc", "cancel_doc", "amend_doc",
	"delete_doc", "run_method",
	"send_email", "add_comment", "update_comment", "share_doc", "unshare_doc",
	"assign_to", "unassign_from", "add_tag", "remove_tag",
	"follow_document", "unfollow_document", "attach_to_doc",
	"create_dashboard_chart", "create_dashboard",
})
_PREVIEWABLE = frozenset({
	"create_doc", "update_doc", "submit_doc", "cancel_doc", "amend_doc",
	"delete_doc", "run_method",
})


def _as_bool(value) -> bool:
	"""Coerce an agent-supplied flag to bool. A JSON client may send the
	string ``"false"``/``"0"``; ``bool("false")`` is True, so treat the common
	falsy strings as False rather than trusting plain ``bool()``."""
	if isinstance(value, str):
		return value.strip().lower() in ("1", "true", "yes", "on")
	return bool(value)


def _run_preview(tool: str, args: dict) -> dict:
	"""Dispatch a write tool with all DB effects sandboxed (mechanics in
	``jarvis.tools._preview_sandbox``, shared with preview_doc). Side effects
	fired directly inside hooks (inline HTTP calls) are NOT sandboxed."""
	from jarvis.tools._preview_sandbox import preview_sandbox

	with preview_sandbox():
		would = dispatch(tool, args)
	return {
		"preview": True,
		"would": would,
		"note": ("Validated with all DB writes rolled back; nothing was "
				 "committed or queued. Side effects fired directly inside "
				 "hooks (inline HTTP calls in on_submit / on_cancel) are "
				 "not sandboxed by preview."),
	}


def _run_tool(tool: str, raw_args: dict | str | None) -> dict:
	"""Parse args + dispatch + wrap in the bench's standard envelope.

	The translation layer between tool-level Python exceptions and
	the wire-shape ``{ok, data}`` / ``{ok, error}`` envelope. JarvisError
	subclasses (InvalidArgumentError, PermissionDeniedError,
	ToolNotFoundError, ...) carry their class name as the wire
	``code`` so the bench's admin_client + tests can branch on it
	without parsing the message.

	frappe.PermissionError is caught here so a tool that goes through
	``frappe.has_permission`` (rather than raising PermissionDeniedError
	itself) still translates to the bench's envelope rather than
	Frappe's native 403 page. Anything else (programming errors, real
	exceptions) is audited (for write tools) and re-raised to Frappe's
	native handler so a 500 surfaces at the seam where the bug lives.

	Replaces the old _dispatch_safe + _parse_args dance: parse_args
	used to mix "dict-or-error-envelope" returns with this function's
	try/except, splitting the translation across two helpers. Folded
	into one to match the reviewer's "native handler" pattern note
	from the 2026-06-16 punch list.
	"""
	is_write = tool in _WRITE_TOOLS
	try:
		args = _parse_args(raw_args)
	except JarvisError as e:
		return _error(type(e).__name__, str(e))

	# ``preview`` is read, not popped: dispatch() filters args to the tool's
	# signature so the flag never reaches the tool anyway, and leaving ``args``
	# unmutated keeps the shared dict the session-persistence path holds intact.
	if isinstance(args, dict) and _as_bool(args.get("preview")):
		if tool not in _PREVIEWABLE:
			return _error("InvalidArgumentError",
						  f"preview is not supported for {tool}")
		# A dry-run: surface its validation errors, but never audit - nothing
		# is committed, so there is no write to record.
		try:
			return {"ok": True, "data": _run_preview(tool, args)}
		except JarvisError as e:
			return _error(type(e).__name__, str(e))
		except frappe.PermissionError as e:
			return _error("PermissionDeniedError", str(e) or "permission denied")
		except (frappe.ValidationError, frappe.DuplicateEntryError) as e:
			return _error("InvalidArgumentError", str(e) or type(e).__name__)

	try:
		data = dispatch(tool, args)
	except JarvisError as e:
		if is_write:
			audit.record(tool=tool, args=args, ok=False,
						 error_code=type(e).__name__, error_message=str(e))
		return _error(type(e).__name__, str(e))
	except frappe.PermissionError as e:
		if is_write:
			audit.record(tool=tool, args=args, ok=False,
						 error_code="PermissionDeniedError", error_message=str(e))
		return _error("PermissionDeniedError", str(e) or "permission denied")
	except (frappe.ValidationError, frappe.DuplicateEntryError) as e:
		# Bad-input errors a tool surfaces from doc.insert()/get_doc/link
		# validation - DuplicateEntryError (a NameError subclass, NOT a
		# ValidationError), MandatoryError, LinkValidationError,
		# DoesNotExistError, UniqueValidationError, plus app-level
		# ValidationError business rules. These are the user's fault, not a
		# bug, so translate to the envelope instead of leaking Frappe's
		# native 500/404. The message carries the specifics; the code stays
		# in the known JarvisError set the bench client branches on.
		if is_write:
			audit.record(tool=tool, args=args, ok=False,
						 error_code="InvalidArgumentError", error_message=str(e))
		return _error("InvalidArgumentError", str(e) or type(e).__name__)
	except Exception as e:
		# Unexpected error (a real bug): audit the attempt for write tools so
		# the trail is complete even for a partial mutation, then re-raise so
		# Frappe's native 500 still surfaces at the seam.
		if is_write:
			audit.record(tool=tool, args=args, ok=False,
						 error_code=type(e).__name__, error_message=str(e))
		raise
	if is_write:
		audit.record(tool=tool, args=args, ok=True, result=data)
	return {"ok": True, "data": data}


# _error lives in jarvis/_responses.py - single source of truth for the
# customer-facing envelope shape, shared with jarvis/oauth/api.py. The
# success envelope (returned inline at lines like
# ``{"ok": True, "data": data}``) is the matching ``ok()`` there if a
# caller wants it explicitly.
from jarvis._responses import err as _error  # noqa: E402


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
	now = frappe.utils.now()
	settings.db_set("agent_token", new_token)
	# C2 time-bound: stamp issued_at so plugin_auth's expiry check has
	# a reference point. Tolerate the column not existing yet on a
	# pre-migration deploy state.
	try:
		settings.db_set("agent_token_issued_at", now)
	except Exception:
		pass
	frappe.db.commit()

	return {"ok": True, "data": {"rotated_at": now}}
