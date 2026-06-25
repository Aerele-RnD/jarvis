"""Whitelisted endpoints for the Jarvis chat surface.

The browser talks to these from the /jarvis chat SPA (apps/jarvis/frontend).
"""

from __future__ import annotations

import frappe

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"

# Wall-clock budget for the RQ worker that runs one agent turn.
#
# Covers worst case end-to-end: pair (<=90s admin round-trip) +
# WS connect (10s) + TURN_TIMEOUT_SECONDS (600s) = 700s. 720s gives
# 20s headroom. Bumped from 300s in lockstep with the
# TURN_TIMEOUT_SECONDS bump to 600s (see openclaw_client.py for the
# Frappe-Cloud + Hetzner WAN rationale - the bench RQ envelope has
# to be larger than the WS turn cap or the worker dies first and
# the WS cap never gets a chance to enforce). Previously this was
# hardcoded as ``timeout=300`` at both enqueue sites (send_message
# + retry_message) so a bump had to land in two places - the
# 2026-06-16 review caught a previous 200s ceiling that had drifted
# to 300s in one site but stayed 200s in the other; consolidating
# behind this constant prevents that drift.
_AGENT_TURN_WORKER_TIMEOUT = 720
# Subscription-tier model IDs accepted by codex / gemini-cli's auth tunnel.
# Catalogue lives in jarvis/_subscription_models.py (shared with oauth/api.py
# - the two used to declare it independently, see 2026-06-16 punch-list).
# Mirrors SUBSCRIPTION_MODELS in jarvis_chat.js / jarvis_account.js /
# jarvis_onboarding.js; keep all three JS files in sync with the Python
# catalogue.
from jarvis._subscription_models import (
	DEFAULT_MODEL as _DEFAULT_MODEL,
	SUBSCRIPTION_MODELS as _SUBSCRIPTION_MODELS,
)


@frappe.whitelist()
def list_conversations() -> list[dict]:
	"""Return active conversations owned by the current user, newest first.

	Each row includes ``message_count`` so the UI can identify empty
	conversations (used by ``create_or_focus_empty``).
	"""
	user = frappe.session.user
	rows = frappe.db.sql(
		"""
		SELECT c.name, c.title, c.last_active_at,
		       (SELECT COUNT(*) FROM `tabJarvis Chat Message` m
		        WHERE m.conversation = c.name) AS message_count
		FROM `tabJarvis Conversation` c
		WHERE c.owner = %s AND c.status = 'Active'
		ORDER BY c.last_active_at DESC
		""",
		(user,),
		as_dict=True,
	)
	return rows


@frappe.whitelist()
def create_or_focus_empty() -> str:
	"""Return an empty active conversation for the current user, creating
	one only if no empty conversation already exists.

	Prevents the "click New Chat repeatedly => orphan empty rows" failure
	mode. The most-recently-active empty conversation wins.
	"""
	user = frappe.session.user
	empty = frappe.db.sql(
		"""
		SELECT c.name
		FROM `tabJarvis Conversation` c
		WHERE c.owner = %s AND c.status = 'Active'
		  AND NOT EXISTS (
		    SELECT 1 FROM `tabJarvis Chat Message` m
		    WHERE m.conversation = c.name
		  )
		ORDER BY c.last_active_at DESC
		LIMIT 1
		""",
		(user,),
	)
	if empty:
		return empty[0][0]
	return create_conversation()


@frappe.whitelist()
def get_conversation(conversation: str) -> dict:
	"""Return conversation metadata + ordered messages.

	Raises frappe.DoesNotExistError if the conversation does not exist or
	the caller is not the owner.
	"""
	doc = frappe.get_doc(CONV, conversation)  # respects owner-only permission

	messages = frappe.get_all(
		MSG,
		filters={"conversation": conversation},
		fields=[
			"name", "seq", "role", "content", "streaming", "error",
			"tool_name", "tool_args", "tool_result", "tool_status",
			"canvas", "creation",
		],
		order_by="seq asc",
	)
	# canvas is stored as a JSON string; hand the UI a real list (or None).
	for m in messages:
		if m.get("canvas"):
			try:
				m["canvas"] = frappe.parse_json(m["canvas"])
			except Exception:
				m["canvas"] = None
	return {
		"conversation": {
			"name": doc.name,
			"title": doc.title,
			"status": doc.status,
			"session_key": doc.session_key,
			"model_override": doc.model_override or "",
			"last_active_at": doc.last_active_at,
		},
		"messages": messages,
	}


@frappe.whitelist()
def get_canvas(message: str, name: str | None = None) -> dict:
	"""Return one canvas artifact's render-ready content for inline display.

	Permission: the caller must own the parent conversation (same gate as
	get_conversation). Returns {name, title, type, content} where content is
	ready to drop into a sandboxed iframe srcdoc — HTML as-is, SVG wrapped in
	a minimal HTML shell.
	"""
	from frappe import _ as _t

	row = frappe.db.get_value(MSG, message, ["conversation", "canvas"], as_dict=True)
	if not row:
		frappe.throw(_t("message not found"), frappe.DoesNotExistError)
	frappe.get_doc(CONV, row.conversation)  # owner-only permission check

	items = frappe.parse_json(row.canvas) if row.canvas else []
	if not isinstance(items, list) or not items:
		frappe.throw(_t("no canvas on this message"), frappe.DoesNotExistError)
	item = next((c for c in items if c.get("name") == name), None) if name else None
	if item is None:
		item = items[0]

	typ = item.get("type")
	fdoc = frappe.get_doc("File", {"file_url": item.get("file_url")})
	raw = fdoc.get_content()
	out = {
		"name": item.get("name"), "title": item.get("title"),
		"type": typ, "file_url": item.get("file_url"),
	}
	if typ in ("html", "svg"):
		# Rendered inline in a sandboxed iframe srcdoc.
		body = raw.decode("utf-8") if isinstance(raw, bytes) else (raw or "")
		if typ == "svg":
			body = (
				'<!doctype html><meta charset="utf-8">'
				"<style>html,body{margin:0;height:100%;background:#fff}"
				"svg{display:block;max-width:100%;height:auto;margin:0 auto}</style>"
				+ body
			)
		out["content"] = body
	else:
		# pdf / image / file → base64 data URL (used by <iframe>/<img>/download).
		import base64

		data = raw if isinstance(raw, bytes) else (raw or "").encode("utf-8")
		out["data_url"] = f"data:{_artifact_mime(item)};base64," + base64.b64encode(data).decode("ascii")
	return out


def _artifact_mime(item: dict) -> str:
	"""Best-effort MIME for a non-text artifact, from its extension."""
	ext = (item.get("name") or "").rsplit(".", 1)[-1].lower()
	return {
		"pdf": "application/pdf",
		"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
		"gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml",
		"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		"xls": "application/vnd.ms-excel", "csv": "text/csv",
		"json": "application/json", "txt": "text/plain", "md": "text/markdown",
	}.get(ext, "application/octet-stream")


@frappe.whitelist()
def create_conversation() -> str:
	"""Create an empty conversation owned by the current user; return its name."""
	doc = frappe.get_doc({
		"doctype": CONV,
		"title": "New chat",
		"status": "Active",
	})
	doc.insert()
	frappe.db.commit()
	return doc.name


@frappe.whitelist()
def archive_conversation(conversation: str) -> dict:
	"""Set status to archived. The openclaw-side session is left in place."""
	doc = frappe.get_doc(CONV, conversation)
	doc.status = "Archived"
	doc.save()
	frappe.db.commit()
	return {"ok": True}


import uuid

from frappe import _

from jarvis.chat.policy import validate_can_send
from jarvis.chat.openclaw_client import OpenclawSession


@frappe.whitelist()
def send_message(
	conversation: str, message: str, model_override: str | None = None,
	attachments: str | None = None, context: str | None = None,
) -> dict:
	"""Validate, persist the user message, ensure session_key, enqueue the worker.

	`model_override` (optional): bare model id to apply to this conversation
	BEFORE enqueueing the worker. Used from the welcome screen so the first
	turn lands on the picker-chosen model without a race against the worker.
	Validated against the same allowlist set_conversation_model uses.
	Empty string / None leaves the existing override alone.

	Returns {ok: True, run_id, message_id} on success or
	{ok: False, reason: str} on validation failure. Raises
	frappe.DoesNotExistError if the conversation does not exist or the
	caller is not the owner.
	"""
	user = frappe.session.user

	ok, reason = validate_can_send(user)
	if not ok:
		return {"ok": False, "reason": reason}

	# Attachments arrive as a JSON string of [{file_url, file_name}, ...] from
	# the composer's file picker (already uploaded to the Frappe File doctype).
	# The worker inlines their text content into the prompt; here we only keep
	# a "📎 name" marker on the visible message.
	atts = []
	if attachments:
		try:
			parsed = frappe.parse_json(attachments)
			if isinstance(parsed, list):
				atts = [a for a in parsed if isinstance(a, dict) and a.get("file_url")]
		except Exception:
			atts = []

	if (not message or not message.strip()) and not atts:
		return {"ok": False, "reason": _("message is empty")}

	conv_doc = frappe.get_doc(CONV, conversation)  # respects perms

	# Apply model override BEFORE enqueueing so the worker sees the new value
	# when it loads the conversation. (If we set this after the enqueue, the
	# worker may pick up the run before the DB write commits.)
	if model_override:
		settings = frappe.get_single("Jarvis Settings")
		allowed = _SUBSCRIPTION_MODELS.get(settings.llm_provider, [])
		if model_override not in allowed:
			return {"ok": False, "reason":
			        f"model {model_override!r} is not valid for "
			        f"{settings.llm_provider!r}"}
		conv_doc.model_override = model_override

	# Visible message keeps the typed text plus a compact attachment marker;
	# the file bytes are inlined for the agent in the worker, not stored here.
	display_content = message.strip()
	if atts:
		names = ", ".join((a.get("file_name") or "file") for a in atts)
		display_content = (display_content + "\n\n" if display_content else "") + "📎 " + names

	# Persist the user message with next seq value
	seq = _next_seq(conversation)
	msg_doc = frappe.get_doc({
		"doctype": MSG,
		"conversation": conversation,
		"seq": seq,
		"role": "user",
		"content": display_content,
		"streaming": 0,
	})
	msg_doc.insert()

	# First user message becomes the conversation title (capped at 60 chars)
	if conv_doc.title == "New chat":
		conv_doc.title = (message.strip() or display_content or "New chat")[:60]
	conv_doc.last_active_at = frappe.utils.now()

	# Ensure the conversation has an openclaw session_key; create one on
	# first turn. Insert the Jarvis Chat Session row so the plugin's
	# sessionKey → user lookup works. Self-hosted mode chats over openclaw's
	# HTTP surface (stateless per call) and needs no WS session / device
	# pairing, so skip session creation there.
	from jarvis import selfhost
	if not selfhost.is_self_hosted() and not conv_doc.session_key:
		conv_doc.session_key = _ensure_session_key(user)
	conv_doc.save()
	frappe.db.commit()

	# Enqueue the worker. Returns immediately; worker runs async.
	run_id = uuid.uuid4().hex[:12]
	# Only pass `attachments` when there are some, so a not-yet-reloaded worker
	# (RQ workers don't hot-reload) keeps handling ordinary messages instead of
	# erroring on an unexpected kwarg.
	enqueue_kwargs = {
		"conversation_id": conversation,
		"message_id": msg_doc.name,
		"run_id": run_id,
	}
	if atts:
		enqueue_kwargs["attachments"] = atts
	# Floating-widget auto-context: {doctype, name, label} of the doc the user
	# is viewing. Only forwarded when present, for the same not-yet-reloaded
	# worker safety as attachments above.
	if context:
		try:
			ctx = frappe.parse_json(context)
			if isinstance(ctx, dict) and ctx.get("doctype"):
				enqueue_kwargs["context"] = {
					"doctype": ctx.get("doctype"),
					"name": ctx.get("name") or "",
				}
		except Exception:
			pass
	# Route to the ``long`` queue rather than ``default``: chat turns can run
	# up to ``_AGENT_TURN_WORKER_TIMEOUT`` (720s, far above the 300s default
	# cap), and ``default`` is shared with provisioning + OAuth-refresh jobs
	# which would otherwise block interactive chat behind 30s+ pieces of
	# infrastructure work. ``at_front=True`` pushes interactive chat to the
	# head of the long queue so a scheduled long-running job (backup, big
	# import) doesn't make a user wait for it to finish.
	frappe.enqueue(
		method="jarvis.chat.worker.run_agent_turn",
		queue="long",
		timeout=_AGENT_TURN_WORKER_TIMEOUT,
		at_front=True,
		**enqueue_kwargs,
	)

	return {"ok": True, "run_id": run_id, "message_id": msg_doc.name}


@frappe.whitelist()
def get_chat_ui_settings() -> dict:
	"""Return the bench-side LLM settings the chat UI needs to render the
	model picker (provider label, current default model, auth mode, and the
	allowlist of subscription-mode models per provider).

	Picker is shown only when auth_mode == "oauth" - api_key customers
	register a single model at signup and there's no multi-model UI
	for them yet (see spec § Out of scope).
	"""
	settings = frappe.get_single("Jarvis Settings")
	# default_models lets callers (jarvis_onboarding.js,
	# jarvis_account.js subscription-tab) skip duplicating the
	# canonical "what's the safe default model id per provider"
	# table. Together with subscription_models this turns the JS
	# pages into pure consumers of jarvis/_subscription_models.py.
	# Punch-list "_SUBSCRIPTION_MODELS duplicated 4-5 times" from
	# the 2026-06-16 cross-repo review.
	return {
		"llm_auth_mode": settings.llm_auth_mode or "api_key",
		"llm_provider": settings.llm_provider or "",
		"llm_model": settings.llm_model or "",
		"subscription_models": _SUBSCRIPTION_MODELS,
		"default_models": _DEFAULT_MODEL,
		# When 1, the agent applies mutating changes without confirming (auto mode).
		"auto_apply_changes": int(settings.auto_apply_changes or 0),
	}


@frappe.whitelist()
def set_auto_apply(value) -> dict:
	"""Toggle the per-site 'auto-apply changes (skip confirmation)' setting.

	OFF (default) = the agent confirms every ERP-mutating action before running
	it; ON = it applies changes immediately. Read by the chat worker and folded
	into the turn's [Context: ...] line so the agent knows which mode it's in.
	"""
	on = 1 if str(value) in ("1", "true", "True", "on", "yes") else 0
	frappe.db.set_single_value("Jarvis Settings", "auto_apply_changes", on)
	frappe.db.commit()
	return {"ok": True, "data": {"auto_apply_changes": on}}


def _est_tokens(text: str | None) -> int:
	"""Rough token estimate for ``text`` (~4 chars/token, the standard English
	approximation). We can't do better: openclaw's gateway stream doesn't emit
	real per-turn token counts, so everything here is clearly labelled an
	estimate in the UI."""
	if not text:
		return 0
	return (len(text) + 3) // 4


@frappe.whitelist()
def get_usage(conversation: str | None = None) -> dict:
	"""Estimated token usage for the current user — this chat, this month, and
	all-time — plus the monthly budget so the UI can draw a meter.

	ESTIMATE ONLY (see _est_tokens): summed from stored message text
	(content + tool args/results), not real API token counts, which openclaw
	doesn't expose. Owner-scoped: only the caller's own conversations.
	"""
	from frappe.utils import get_datetime, get_first_day, now_datetime

	user = frappe.session.user
	convs = frappe.get_all(CONV, filters={"owner": user}, pluck="name")
	budget = int(frappe.db.get_single_value("Jarvis Settings", "token_budget_monthly") or 0)
	month_start = get_datetime(get_first_day(now_datetime()))
	out = {
		"estimated": True,
		"chat_tokens": 0,
		"month_tokens": 0,
		"total_tokens": 0,
		"budget_monthly": budget,
		"month_label": now_datetime().strftime("%B %Y"),
	}
	if not convs:
		return out

	rows = frappe.get_all(
		MSG,
		filters={"conversation": ["in", convs]},
		fields=["conversation", "content", "tool_args", "tool_result", "creation"],
	)
	for m in rows:
		t = _est_tokens(m.content) + _est_tokens(m.tool_args) + _est_tokens(m.tool_result)
		out["total_tokens"] += t
		if m.creation and get_datetime(m.creation) >= month_start:
			out["month_tokens"] += t
		if conversation and m.conversation == conversation:
			out["chat_tokens"] += t
	return out


@frappe.whitelist()
def set_conversation_model(conversation: str, model: str | None = None) -> dict:
	"""Set or clear the per-conversation model override.

	`model`: bare model id (no provider prefix), validated against
	the customer's current llm_provider's allowed set. Empty string or
	None clears the override (so subsequent turns fall back to
	Jarvis Settings.llm_model).

	Returns {"ok": True, "data": {"effective_model": <model>}} where
	effective_model is what will be sent for the next turn - either
	the override or the settings default.
	"""
	if not frappe.db.exists(CONV, conversation):
		return {"ok": False, "error": {
			"code": "unknown_conversation",
			"message": f"conversation {conversation!r} not found",
		}}

	settings = frappe.get_single("Jarvis Settings")

	# Empty / None clears the override.
	if not model:
		frappe.db.set_value(CONV, conversation, "model_override", "", update_modified=False)
		frappe.db.commit()
		return {"ok": True, "data": {"effective_model": settings.llm_model or ""}}

	allowed = _SUBSCRIPTION_MODELS.get(settings.llm_provider, [])
	if model not in allowed:
		return {"ok": False, "error": {
			"code": "unknown_model",
			"message": (
				f"{model!r} is not a recognized model for {settings.llm_provider!r}. "
				f"Allowed: {allowed!r}"
			),
		}}

	frappe.db.set_value(CONV, conversation, "model_override", model, update_modified=False)
	frappe.db.commit()
	return {"ok": True, "data": {"effective_model": model}}


@frappe.whitelist()
def retry_message(message: str) -> dict:
	"""Re-run the agent turn that produced an errored assistant message.

	Finds the user message that immediately precedes ``message`` in the same
	conversation, then enqueues ``run_agent_turn`` against it. The original
	errored placeholder stays in the conversation as history - the new turn
	creates its own assistant placeholder, so the chat reads "user → (errored
	turn) → (retried turn)".

	Returns ``{ok: True, run_id}`` on success or ``{ok: False, reason}`` on
	validation failure. Raises ``frappe.DoesNotExistError`` if the caller
	doesn't own the message.
	"""
	doc = frappe.get_doc(MSG, message)  # owner-only perm
	if doc.role != "assistant":
		return {"ok": False, "reason": _("only assistant messages can be retried")}
	if not doc.error:
		return {"ok": False, "reason": _("message did not error")}

	# Find the most recent user message that came BEFORE this assistant in
	# the same conversation. That's the turn we want to re-run.
	prev_user = frappe.db.sql(
		"""SELECT name FROM `tabJarvis Chat Message`
		WHERE conversation = %s AND role = 'user' AND seq < %s
		ORDER BY seq DESC LIMIT 1""",
		(doc.conversation, doc.seq),
	)
	if not prev_user:
		return {"ok": False, "reason": _("no preceding user message to retry")}
	user_msg_id = prev_user[0][0]

	# Bump the conversation's last_active_at so the sidebar surfaces it.
	frappe.db.set_value(
		CONV, doc.conversation, "last_active_at", frappe.utils.now()
	)

	run_id = uuid.uuid4().hex[:12]
	# Same routing as send_message: long queue + push to the front so the
	# retry doesn't wait behind unrelated long-queue work.
	frappe.enqueue(
		method="jarvis.chat.worker.run_agent_turn",
		queue="long",
		timeout=_AGENT_TURN_WORKER_TIMEOUT,
		at_front=True,
		conversation_id=doc.conversation,
		message_id=user_msg_id,
		run_id=run_id,
	)
	return {"ok": True, "run_id": run_id}


def _next_seq(conversation: str) -> int:
	"""Return the next seq value for a conversation (max+1, or 1 if empty)."""
	current_max = frappe.db.sql(
		"SELECT MAX(seq) FROM `tabJarvis Chat Message` WHERE conversation = %s",
		(conversation,),
	)[0][0]
	return (current_max or 0) + 1


def _ensure_session_key(user: str) -> str:
	"""Create an openclaw session for `user`, persist the Chat Session row,
	and return the session_key. Caller is responsible for storing it on the
	parent Conversation row.
	"""
	settings = frappe.get_single("Jarvis Settings")
	gateway_url = (settings.agent_url or "").replace("http://", "ws://").replace("https://", "wss://")
	gateway_token = settings.get_password("agent_token")
	if not gateway_url or not gateway_token:
		frappe.throw(_("openclaw is not configured"))

	import time
	sess = OpenclawSession.connect(gateway_url)
	try:
		# Label includes a timestamp because openclaw deduplicates sessions
		# by label and rejects collisions.
		session_key = sess.create_session(label=f"jarvis-chat-{user}-{int(time.time() * 1000)}")
	finally:
		sess.close()

	# C2 stretch (2026-06-16 review): snapshot the bench's current
	# chat_device_id into the Jarvis Chat Session row. On every
	# call_tool the plugin-auth validator re-checks that the row's
	# device_id still matches the bench's current device_id; if not
	# (because the bench re-paired - operator rotation or compromise
	# response), the session_key is dead. This bounds the window for
	# a leaked-session-key replay attack to "until the next re-pair."
	current_device_id = (settings.chat_device_id or "").strip()

	# Insert the Chat Session row (plugin's sessionKey → user lookup table)
	frappe.get_doc({
		"doctype": "Jarvis Chat Session",
		"session_key": session_key,
		"user": user,
		"chat_device_id": current_device_id,
	}).insert(ignore_permissions=True)
	frappe.db.commit()

	return session_key
