"""RQ job: stream one agent turn from openclaw to DB + realtime.

Spawned by jarvis.chat.api.send_message via frappe.enqueue. Holds a Python
WebSocket connection to the openclaw gateway for the duration of the turn
(typically 10-30s); the Frappe request handler returns in ~10ms and the
worker streams events while the browser sees them token-by-token via
socketio.
"""

from __future__ import annotations

import time

import frappe

from jarvis.chat.events import publish_to_user
from jarvis.chat import openclaw_session_pool
from jarvis.exceptions import OpenclawUnreachableError

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"

# Batch-commit thresholds for the assistant-content writes during a
# streamed turn. Sprint-5 punch-list "Worker writes assistant.content on
# every delta with full overwrite + commit per token" (2026-06-16
# review): the previous shape called frappe.db.set_value + frappe.db.
# commit() for every single token, so a 500-token response = 500
# write+commit cycles. The DB write itself is cheap (one Singles row);
# the commit is where the cost lives - it forces a per-token transaction
# round-trip.
#
# Now: buffer the latest cumulative text in memory, flush (write+commit)
# when EITHER threshold trips, AND flush before any tool/lifecycle event
# fires so the on-disk message-row order matches the realtime channel.
# Customer experience stays unchanged - the realtime
# ``assistant:delta`` publish still fires on every token, so the UI
# animates token-by-token. The DB just catches up in batches.
#
# Numbers picked for the punch-list "every N=10 events or 250ms" ask:
# at typical chat throughputs (1-50 tokens/s) this means 1-2 commits
# per second instead of 1-50, but at most ~10 tokens of unwritten
# content if the worker crashes mid-batch (recoverable next stream).
_ASSISTANT_BATCH_SIZE = 10
_ASSISTANT_BATCH_INTERVAL_MS = 250


class _AssistantContentBatcher:
	"""Coalesces per-token assistant-content writes into one DB
	write+commit per batch.

	Usage:
	    batcher = _AssistantContentBatcher(assistant_msg.name)
	    for event in stream:
	        if event["kind"] == "assistant":
	            batcher.delta(event["text"])
	            batcher.flush_if_due()
	            continue
	        batcher.flush()  # ordering: flush before any non-delta event
	        _handle_event(event, ...)
	    batcher.flush()      # drain on stream end
	"""

	def __init__(self, msg_name: str):
		self.msg_name = msg_name
		self._pending_text: str | None = None
		self._events_since_flush = 0
		self._last_flush_ms = self._now_ms()

	@staticmethod
	def _now_ms() -> int:
		return int(time.monotonic() * 1000)

	def delta(self, text: str) -> None:
		"""Record the latest cumulative assistant text. Caller decides
		when to actually persist via flush / flush_if_due."""
		self._pending_text = text
		self._events_since_flush += 1

	def flush_if_due(self) -> bool:
		"""Flush iff the size or time threshold is hit. Returns True iff
		a flush actually happened."""
		if self._pending_text is None:
			return False
		if self._events_since_flush >= _ASSISTANT_BATCH_SIZE:
			return self.flush()
		if self._now_ms() - self._last_flush_ms >= _ASSISTANT_BATCH_INTERVAL_MS:
			return self.flush()
		return False

	def flush(self) -> bool:
		"""Flush immediately if any text is pending. Returns True iff a
		flush happened (caller can use this for trace logging)."""
		if self._pending_text is None:
			return False
		frappe.db.set_value(MSG, self.msg_name, "content", self._pending_text)
		frappe.db.commit()
		self._pending_text = None
		self._events_since_flush = 0
		self._last_flush_ms = self._now_ms()
		return True

# Provider label → openclaw provider id sent in the chat WS frame.
#
# Openclaw has two dispatch paths chosen at request time
# (openclaw/src/agents/model-selection-cli.ts:6-20):
#
#   - CLI backend: taken when isCliProvider(provider) returns true.
#     Routes dispatch to a registered CliBackend that spawns an external
#     CLI binary. The CliBackend is keyed by the provider id (so the
#     provider sent here must match the CliBackend's id).
#
#   - Embedded runtime (codex / pi harness): taken otherwise. The codex
#     harness has an allowlist of accepted providers; pi handles
#     everything else but expects HTTP API auth (api key).
#
# The two providers we currently support resolve to two different paths:
#
#   - OpenAI codex: codex IS a registered plugin harness
#     (openclaw/extensions/codex/index.ts:34) whose allowlist accepts
#     "openai" as the model-provider key. Use "openai" for the chat WS
#     frame and the embedded codex-harness path handles the dispatch.
#
#   - Google Gemini: gemini-cli is registered ONLY as a CliBackend
#     (openclaw/extensions/google/cli-backend.ts:16 with id
#     "google-gemini-cli"). Use "google-gemini-cli" verbatim so
#     isCliProvider returns true and dispatch routes via the CLI backend
#     to the gemini binary inside the container. Mapping it to "google"
#     makes isCliProvider return false, dispatch falls into the embedded
#     path, and openclaw errors "No API key found for provider 'google'".
#
# Only used in oauth mode - api_key mode skips this map and lets
# openclaw resolve the single registered models.providers entry.
_PROVIDER_LABEL_TO_OPENCLAW_ID = {
	"OpenAI": "openai",
	"Google Gemini": "google-gemini-cli",
}


def _resolve_model_and_provider(conv) -> tuple[str, str | None]:
	"""Return (effective_model, openclaw_provider_id_or_None) for this conv.

	- effective_model = conv.model_override or Jarvis Settings.llm_model
	- provider id is set only in oauth mode (api_key mode keeps it None)
	"""
	settings = frappe.get_single("Jarvis Settings")
	effective_model = (conv.model_override or settings.llm_model or "")
	provider = (
		_PROVIDER_LABEL_TO_OPENCLAW_ID.get(settings.llm_provider)
		if settings.llm_auth_mode == "oauth"
		else None
	)
	return effective_model, provider


def run_agent_turn(
	conversation_id: str, message_id: str, run_id: str, attachments=None,
	context=None,
) -> None:
	"""Drive one agent turn end to end. Called by RQ; not whitelisted.

	`attachments` (optional): list of {file_url, file_name} dicts whose text
	content is inlined into the prompt sent to the agent (see
	_inline_attachments). The persisted/visible user message keeps only the
	"📎 name" marker, so file bytes never bloat the chat history.

	`context` (optional): {doctype, name} of the ERP document the user was
	viewing when they asked (floating-widget auto-context). Prepended to the
	agent prompt only — the persisted/visible user message is unchanged.

	Sprint-3 (2026-06-16 review): the inline ``except OpenclawUnreachableError``
	blocks only marked the placeholder errored for openclaw-specific
	failures. Any OTHER exception (cryptography.InvalidKey, ssl.SSLError,
	programmer bug in _handle_event, etc.) propagated to RQ without
	calling _mark_errored, leaving the assistant row stuck at
	``streaming=1`` forever (the UI poller spins on the empty body).
	An outer try/except Exception now catches everything else, marks the
	row errored + publishes run:error, then re-raises so RQ still records
	the job as failed.
	"""
	conv = frappe.get_doc(CONV, conversation_id)
	user = conv.owner

	# Create the assistant placeholder row up-front so the browser has a
	# stable name to attach realtime events to.
	assistant_msg = _create_assistant_placeholder(conv)

	publish_to_user(user, {
		"kind": "run:start",
		"conversation_id": conversation_id,
		"message_id": assistant_msg.name,
		"run_id": run_id,
	})

	settings = frappe.get_single("Jarvis Settings")
	# Fetch content + sender of THIS user message in one round-trip.
	# msg_row.owner is the Frappe user who sent this turn, set by Frappe
	# at insert time in send_message (jarvis/chat/api.py). We use it
	# rather than conv.owner for the context bracket because the bench-
	# side dispatcher (_dispatch_from_session in jarvis/api.py:118) also
	# acts on the per-request identity, not the conversation creator -
	# the bracket and the tool-call's frappe.session.user stay in lock-
	# step. Today these are equal for single-owner conversations; the
	# distinction matters the moment we ship shared conversations.
	msg_row = (
		frappe.db.get_value(MSG, message_id, ["content", "owner"], as_dict=True)
		or {}
	)
	user_message = msg_row.get("content")
	chat_user = msg_row.get("owner") or user
	# Prepend today's date AND the chat user's Frappe id as a context line so
	# the agent (AGENTS.md tells it to treat the leading ``[Context: ...]``
	# as system, not user) can (a) resolve relative time expressions
	# ("last quarter", "this week") and (b) answer "who am I" / "what
	# perms do I have" without a clarifying round-trip or a doomed
	# get_list on User. The persisted user_message in the DB is
	# unchanged; only the value sent over to openclaw is augmented.
	now = frappe.utils.now_datetime()
	today = now.strftime("%Y-%m-%d (%A)")
	# Fold the auto-apply preference into the system context line so the agent
	# knows whether to confirm mutating ops. Default (off) = confirm; the persona
	# confirms by default, so we only signal the non-default "auto" mode.
	auto_apply = "; auto-apply changes: ON" if settings.auto_apply_changes else ""
	user_message = (
		f"[Context: today is {today}; chat user: {chat_user}{auto_apply}]"
		f"\n\n{user_message or ''}"
	)

	from jarvis import selfhost

	# Floating-widget auto-context + file inputs layer onto the
	# already date/user-augmented user_message built above. Prompt-only;
	# the persisted/visible user message is unchanged.
	user_message = _prepend_doc_context(user_message, context)
	user_message = _inline_attachments(user_message, attachments)

	def _publish_run_error(err: str) -> None:
		_mark_errored(assistant_msg.name, err)
		publish_to_user(user, {
			"kind": "run:error",
			"conversation_id": conversation_id,
			"message_id": assistant_msg.name,
			"run_id": run_id,
			"error": err,
		})

	try:
		idem = f"{conversation_id}:{message_id}"
		tool_msg_by_call_id: dict[str, str] = {}
		batcher = _AssistantContentBatcher(assistant_msg.name)

		def _consume(events) -> None:
			for event in events:
				_handle_event(
					event,
					conversation_id=conversation_id,
					assistant_msg_name=assistant_msg.name,
					tool_msg_by_call_id=tool_msg_by_call_id,
					user=user,
					run_id=run_id,
					batcher=batcher,
				)
			# Drain buffered assistant deltas before the streaming=0 cleanup.
			batcher.flush()

		if selfhost.is_self_hosted():
			# Self-hosted: openclaw's HTTP OpenAI-compatible surface with a
			# bearer token (full operator scope, no device pairing). agent_url
			# holds the http(s) base; the user's openclaw uses its own LLM.
			from jarvis.chat import openclaw_http_client
			base_url = (settings.agent_url or "").strip()
			token = settings.get_password("agent_token", raise_exception=False) or ""
			# Register this turn so the plugin's call_tool callback (which only
			# carries the openclaw HTTP session key, not our conversation) can
			# attribute tool calls back here and surface tool cards.
			tool_user = (settings.selfhost_tool_user or "").strip()
			selfhost.set_active_turn(tool_user, conversation=conversation_id, owner=user, run_id=run_id)
			# Stream token-by-token unless the operator explicitly turned it
			# off (a NULL field on a pre-existing config defaults to streaming).
			stream_pref = (settings.selfhost_stream is None) or bool(settings.selfhost_stream)
			try:
				_consume(openclaw_http_client.stream_agent_turn(
					base_url, token, user_message, model="openclaw", stream=stream_pref,
				))
			except OpenclawUnreachableError as e:
				_publish_run_error(str(e))
				return
			finally:
				selfhost.clear_active_turn(tool_user, run_id)
		else:
			# Managed: device-paired WebSocket to the tenant's gateway.
			# Uses a per-process connection pool so we don't pay the
			# DNS + TCP + TLS + WS upgrade + handshake (~50-200ms) on
			# every turn. The pool eviction on OpenclawUnreachableError
			# means the next attempt will reconnect; we don't auto-
			# retry inside this turn because tokens may have already
			# streamed to the UI by the time the failure surfaces.
			gateway_url = (settings.agent_url or "").replace(
				"http://", "ws://"
			).replace("https://", "wss://")
			effective_model, oauth_provider_id = _resolve_model_and_provider(conv)
			try:
				with openclaw_session_pool.checkout(gateway_url) as sess:
					_consume(sess.stream_agent_turn(
						conv.session_key, user_message, idem,
						model=effective_model, provider=oauth_provider_id,
					))
			except OpenclawUnreachableError as e:
				_publish_run_error(str(e))
				return

		# Streaming exited cleanly via lifecycle.end
		frappe.db.set_value(MSG, assistant_msg.name, "streaming", 0)
		frappe.db.commit()

		# Rich outputs: detect any canvas/chart artifact the agent produced
		# this turn (HTML or SVG), fetch it from the gateway, persist it as a
		# private File, and publish a 'canvas' event so the UI renders it
		# inline. Managed mode only — self-hosted chats over the HTTP surface
		# have no gateway canvas route. Failure here never fails the turn.
		if not selfhost.is_self_hosted():
			try:
				from jarvis.chat import canvas as canvas_mod

				final_content = frappe.db.get_value(MSG, assistant_msg.name, "content") or ""
				canvas_token = settings.get_password("agent_token", raise_exception=False) or ""
				canvas_items = canvas_mod.persist_canvases(
					assistant_msg.name, final_content, settings.agent_url or "", canvas_token,
				)
				if canvas_items:
					publish_to_user(user, {
						"kind": "canvas",
						"conversation_id": conversation_id,
						"message_id": assistant_msg.name,
						"run_id": run_id,
						"items": canvas_items,
					})
			except Exception:
				frappe.log_error(
					title="chat worker: canvas persist failed",
					message=frappe.get_traceback(),
				)

	except Exception as e:
		# Last-resort backstop. Any exception that wasn't an
		# OpenclawUnreachableError (e.g. cryptography.InvalidKey from
		# device-pairing signing, ssl.SSLError, a tool-handler bug,
		# DoesNotExistError on a stale conversation row) would otherwise
		# leave the assistant row at ``streaming=1`` indefinitely. Mark
		# it errored, publish run:error, then re-raise so RQ records the
		# job as failed (and the operator gets a normal Error Log entry).
		try:
			_mark_errored(
				assistant_msg.name,
				f"unexpected worker error: {type(e).__name__}",
			)
			publish_to_user(user, {
				"kind": "run:error",
				"conversation_id": conversation_id,
				"message_id": assistant_msg.name,
				"run_id": run_id,
				# Don't leak full str(e) - the operator-safe identifier is
				# the exception class; the full traceback is in Error Log.
				"error": f"{type(e).__name__}",
			})
		except Exception:
			# If even the error-marking path fails, swallow - we're
			# already in an error path and re-raising would mask the
			# original exception that RQ should see.
			pass
		raise
	publish_to_user(user, {
		"kind": "run:end",
		"conversation_id": conversation_id,
		"message_id": assistant_msg.name,
		"run_id": run_id,
	})

	# Auto-title (managed mode): the first substantive turn of a still-unnamed
	# conversation gets a concise, LLM-summarised title — not the raw first
	# message. Runs AFTER run:end so the turn UI has already unblocked; the new
	# title lands a few seconds later via a "conversation:renamed" event.
	# Best-effort — a title failure must never affect the completed turn.
	from jarvis import selfhost
	if not selfhost.is_self_hosted():
		try:
			from jarvis.chat import title as title_mod

			gw = (settings.agent_url or "").replace(
				"http://", "ws://"
			).replace("https://", "wss://")
			eff_model, oauth_pid = _resolve_model_and_provider(conv)
			title_mod.maybe_autotitle(
				conversation_id, user,
				gateway_url=gw, model=eff_model, provider=oauth_pid,
			)
		except Exception:
			frappe.log_error(
				title="chat worker: auto-title failed",
				message=frappe.get_traceback(),
			)


def _prepend_doc_context(user_message: str, context) -> str:
	"""Prepend the ERP doc the user was viewing (floating-widget auto-context)
	as a leading ``[Viewing: ...]`` line, so questions like "is this overdue?"
	resolve against the right record without the user naming it. Prompt-only;
	the stored message is untouched. Defensive: a malformed context is ignored.
	"""
	if not isinstance(context, dict):
		return user_message
	doctype = (context.get("doctype") or "").strip()
	if not doctype:
		return user_message
	name = (context.get("name") or "").strip()
	ref = f"{doctype} {name}".strip() if name else f"the {doctype} list"
	return f"[Viewing: {ref} — resolve 'this'/'here' against it]\n\n{user_message}"


_MAX_INLINE_CHARS = 20000


def _inline_attachments(user_message: str, attachments) -> str:
	"""Inline the text content of attached files into the message sent to the
	agent. Binary/undecodable files get a short note instead of bytes. Only the
	prompt is augmented - the stored, visible user message is untouched.
	"""
	if not attachments:
		return user_message
	blocks = []
	for att in attachments:
		if not isinstance(att, dict):
			continue
		url = att.get("file_url")
		name = att.get("file_name") or url or "file"
		if not url:
			continue
		try:
			fdoc = frappe.get_doc("File", {"file_url": url})
			raw = fdoc.get_content()
		except Exception:
			blocks.append(f"[Could not read attached file `{name}`.]")
			continue
		if isinstance(raw, bytes):
			try:
				text = raw.decode("utf-8")
			except UnicodeDecodeError:
				blocks.append(
					f"[Attached file `{name}` is binary ({len(raw)} bytes); not inlined.]"
				)
				continue
		else:
			text = raw or ""
		if len(text) > _MAX_INLINE_CHARS:
			text = text[:_MAX_INLINE_CHARS] + "\n…[truncated]"
		blocks.append(f"Attached file `{name}`:\n```\n{text}\n```")
	if not blocks:
		return user_message
	return user_message + "\n\n" + "\n\n".join(blocks)


def _create_assistant_placeholder(conv) -> "frappe.model.document.Document":
	from jarvis.chat.api import _next_seq

	seq = _next_seq(conv.name)
	msg = frappe.get_doc({
		"doctype": MSG,
		"conversation": conv.name,
		"seq": seq,
		"role": "assistant",
		"content": "",
		"streaming": 1,
	})
	msg.insert(ignore_permissions=True)
	frappe.db.commit()
	return msg


def _mark_errored(assistant_msg_name: str, error: str) -> None:
	frappe.db.set_value(MSG, assistant_msg_name, {
		"streaming": 0,
		"error": error,
	})
	frappe.db.commit()


def _handle_event(
	event: dict,
	*,
	conversation_id: str,
	assistant_msg_name: str,
	tool_msg_by_call_id: dict[str, str],
	user: str,
	run_id: str,
	batcher: _AssistantContentBatcher,
) -> None:
	"""Per-event dispatch. Wrapped in a top-level try/except so a
	programmer bug on one event (KeyError on a malformed openclaw frame,
	a DB DoesNotExist on a stale row, etc.) doesn't kill the whole turn
	and leave the assistant row stranded at streaming=1. Sprint-5
	punch-list "Wrap _handle_event in try/except logging event kind +
	tool_call_id + run_id". On failure we log the event metadata and
	continue - the next event might be a clean recovery (e.g. the
	turn's final lifecycle.end still flips streaming=0).
	"""
	try:
		_handle_event_inner(
			event,
			conversation_id=conversation_id,
			assistant_msg_name=assistant_msg_name,
			tool_msg_by_call_id=tool_msg_by_call_id,
			user=user,
			run_id=run_id,
			batcher=batcher,
		)
	except Exception:
		frappe.log_error(
			title="chat worker: _handle_event failed",
			message=(
				f"kind={event.get('kind')!r} "
				f"phase={event.get('phase')!r} "
				f"tool_call_id={event.get('tool_call_id')!r} "
				f"tool_name={event.get('tool_name')!r} "
				f"run_id={run_id!r} "
				f"conversation_id={conversation_id!r}\n\n"
				f"{frappe.get_traceback()}"
			),
		)
		# Don't re-raise; the outer run_agent_turn loop catches Exception
		# at its outermost layer for the streaming=1 cleanup. Per-event
		# failures should let the stream continue (the next assistant
		# delta might overwrite this bad row with good content).


def _handle_event_inner(
	event: dict,
	*,
	conversation_id: str,
	assistant_msg_name: str,
	tool_msg_by_call_id: dict[str, str],
	user: str,
	run_id: str,
	batcher: _AssistantContentBatcher,
) -> None:
	kind = event.get("kind")

	if kind == "lifecycle":
		# Lifecycle events bracket the stream. Drain any pending
		# assistant content before we write the lifecycle outcome so
		# the on-disk row reflects whatever text was rendered up to
		# this point (matters mostly for the error branch).
		batcher.flush()
		phase = event.get("phase")
		if phase == "error":
			_mark_errored(assistant_msg_name, event.get("error") or "lifecycle error")
			publish_to_user(user, {
				"kind": "run:error",
				"conversation_id": conversation_id,
				"message_id": assistant_msg_name,
				"run_id": run_id,
				"error": event.get("error"),
			})
		# lifecycle start is a no-op (we already published run:start)
		return

	if kind == "assistant":
		text = event.get("text", "")
		# Hot path: buffer the cumulative text + maybe-flush. The
		# realtime publish still fires on every token so the customer's
		# UI animates without delay; the DB write coalesces.
		batcher.delta(text)
		batcher.flush_if_due()
		publish_to_user(user, {
			"kind": "assistant:delta",
			"conversation_id": conversation_id,
			"message_id": assistant_msg_name,
			"text": text,
			"run_id": run_id,
		})
		return

	if kind == "tool":
		# Tool start/end events insert new rows. Drain pending assistant
		# content first so the on-disk row order matches the realtime
		# event order (assistant text the customer saw before this tool
		# call is durable before the tool row appears).
		batcher.flush()
		phase = event.get("phase")
		tool_call_id = event.get("tool_call_id")
		tool_name = event.get("tool_name")
		if phase == "start":
			from jarvis.chat.api import _next_seq
			seq = _next_seq(conversation_id)
			doc = frappe.get_doc({
				"doctype": MSG,
				"conversation": conversation_id,
				"seq": seq,
				"role": "tool",
				"content": f"calling {tool_name}…",
				"tool_name": tool_name,
				"tool_status": "running",
				"streaming": 1,
			})
			doc.insert(ignore_permissions=True)
			frappe.db.commit()
			tool_msg_by_call_id[tool_call_id] = doc.name
			publish_to_user(user, {
				"kind": "tool:start",
				"conversation_id": conversation_id,
				"message_id": doc.name,
				"tool_name": tool_name,
				"tool_call_id": tool_call_id,
				"run_id": run_id,
			})
		elif phase == "end":
			name = tool_msg_by_call_id.get(tool_call_id)
			if not name:
				# Orphan: openclaw emitted a tool 'end' event for a
				# tool_call_id we never logged a 'start' for. Shouldn't
				# happen, but the previous shape silently returned and
				# left no operator trace - so a real recurring orphan
				# (would point at an openclaw event-ordering regression)
				# would be invisible. Log it as a warning so it shows
				# up in Error Log triage.
				frappe.log_error(
					title="chat worker: orphan tool 'end' event",
					message=(
						f"conversation_id={conversation_id!r} "
						f"run_id={run_id!r} "
						f"tool_call_id={tool_call_id!r} "
						f"tool_name={tool_name!r} "
						f"event_status={event.get('status')!r}"
					),
				)
				return
			frappe.db.set_value(MSG, name, {
				"tool_status": event.get("status") or "completed",
				"streaming": 0,
			})
			frappe.db.commit()
			publish_to_user(user, {
				"kind": "tool:end",
				"conversation_id": conversation_id,
				"message_id": name,
				"tool_name": tool_name,
				"tool_call_id": tool_call_id,
				"status": event.get("status"),
				"run_id": run_id,
			})
