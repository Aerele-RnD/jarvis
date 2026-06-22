"""Whitelisted endpoints for the Jarvis chat surface.

The browser talks to these from the /app/jarvis-chat Desk page.
"""

from __future__ import annotations

import json
import os

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

# Process-local cache for the chat bundle hash. Invalidated by mtime so a
# `bench build` is picked up without restarting workers.
_BUILD_ID_CACHE: dict = {"mtime": 0.0, "value": ""}


def _get_build_id() -> str:
	"""Return the current chat bundle hash (e.g. "PY42KOXK").

	Reads sites/assets/assets.json and pulls the hashed filename for
	jarvis_chat.bundle.js. The hash changes on every `bench build`, so a
	mismatch with what the browser captured at page load means the bundle
	has been rebuilt - banner the user to refresh.

	Returns "" if the asset map is missing (dev bench before first build).
	"""
	path = os.path.join(frappe.utils.get_bench_path(), "sites", "assets", "assets.json")
	try:
		mtime = os.path.getmtime(path)
	except OSError:
		return ""
	if mtime == _BUILD_ID_CACHE["mtime"] and _BUILD_ID_CACHE["value"]:
		return _BUILD_ID_CACHE["value"]
	try:
		with open(path) as f:
			data = json.load(f)
	except (OSError, ValueError):
		return ""
	# Entry looks like "/assets/jarvis/dist/js/jarvis_chat.bundle.PY42KOXK.js".
	entry = data.get("jarvis_chat.bundle.js") or ""
	# Last path component, drop the .js suffix.
	value = os.path.basename(entry).removesuffix(".js")
	_BUILD_ID_CACHE["mtime"] = mtime
	_BUILD_ID_CACHE["value"] = value
	return value

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
			"creation",
		],
		order_by="seq asc",
	)
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

	if not message or not message.strip():
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

	# Persist the user message with next seq value
	seq = _next_seq(conversation)
	msg_doc = frappe.get_doc({
		"doctype": MSG,
		"conversation": conversation,
		"seq": seq,
		"role": "user",
		"content": message.strip(),
		"streaming": 0,
	})
	msg_doc.insert()

	# First user message becomes the conversation title (capped at 60 chars)
	if conv_doc.title == "New chat":
		conv_doc.title = message.strip()[:60]
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
	frappe.enqueue(
		method="jarvis.chat.worker.run_agent_turn",
		queue="default",
		timeout=_AGENT_TURN_WORKER_TIMEOUT,
		conversation_id=conversation,
		message_id=msg_doc.name,
		run_id=run_id,
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
		"build_id": _get_build_id(),
	}


@frappe.whitelist()
def get_build_id() -> dict:
	"""Cheap endpoint the chat UI polls on tab refocus to detect a stale
	JS bundle after a `bench build`. Returns {"build_id": "<hash>"}.
	"""
	return {"build_id": _get_build_id()}


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
	frappe.enqueue(
		method="jarvis.chat.worker.run_agent_turn",
		queue="default",
		timeout=_AGENT_TURN_WORKER_TIMEOUT,
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
