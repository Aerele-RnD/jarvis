"""Post-reply chat feedback: a thumbs up/down (with an optional note on a down)
on an assistant reply, forwarded to the admin fleet dashboard.

Direct-send, no local table: this bench keeps NO copy. ``submit_feedback``
derives every piece of metadata server-side (tenant is derived on the admin side
from the authenticated principal), then forwards it best-effort. A failed forward
is dropped silently - feedback is low-stakes, and a blocked tap is not acceptable.
The reply text is never sent; only the rating, refs, and a bounded optional note.

Only the caller's OWN assistant messages can be rated (ownership via the same
gate the rest of the chat surface uses, ``chat.api._get_owned_conversation``).

The same direct-send, no-local-table rule governs the once-per-session popup
("How did this session go?") at the bottom of this module: only the popup's
own metadata (``Jarvis Conversation.session_feedback_asked_at``, and the
``turn_count`` that triggers it) is kept on the bench - the response itself
lives only on the admin side.
"""

from __future__ import annotations

import re

import frappe

from jarvis.chat.api import _get_owned_conversation
from jarvis.permissions import require_jarvis_access

MSG = "Jarvis Chat Message"
CONV = "Jarvis Conversation"

_RATINGS = {"up", "down"}
_MAX_NOTE = 1000
#: The agent session UUID lives as the last segment of a composite session_key
#: like "agent:main:dashboard:<uuid>". Empty when absent/malformed - the rating
#: still records; only the admin-side deep-link is best-effort.
_SESSION_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")

#: Turns a conversation must have settled before the once-per-session popup is
#: due. Hardcoded for v1 (spec "Settings"): there is no precedent for admin
#: pushing a setting down to bench Jarvis Settings, so a configurable field would
#: be a surface with no way to drive it.
SESSION_FEEDBACK_TURN_THRESHOLD = 10
#: The five preset reactions the popup offers, worst to best. Mirrored by the
#: admin ingest's own allowlist (never trust the bench) and by the SPA dialog.
_SESSION_CHIP_VALUES = {"Great", "Good", "Okay", "Not great", "Frustrating"}
#: The reactions that reveal the optional "what went wrong?" line. "Okay" counts:
#: the spec's rule is "Okay or worse", not just the bottom two.
_SESSION_LOW_CHIPS = {"Okay", "Not great", "Frustrating"}


@frappe.whitelist()
def submit_feedback(message_id: str, rating: str, note: str | None = None) -> dict:
	"""Record a thumbs up/down on one assistant reply and forward it to admin.

	Args:
		message_id: the Jarvis Chat Message name of the assistant reply.
		rating: "up" or "down".
		note: optional free text, kept only on a "down".

	The rating commits on the first call (thumbs tap); a later call carrying the
	note folds onto the same admin row (upsert). Returns ``{"ok": True}`` even when
	the forward fails - the tap must never surface an error.
	"""
	require_jarvis_access()
	rating = (rating or "").strip()
	if rating not in _RATINGS:
		frappe.throw("rating must be 'up' or 'down'", frappe.ValidationError)

	# Raw db read bypasses field permlevel; we only need these four columns.
	msg = frappe.db.get_value(
		MSG, message_id, ["conversation", "role", "model", "reply_duration_ms"], as_dict=True
	)
	if not msg:
		frappe.throw("message not found", frappe.DoesNotExistError)
	if msg.role != "assistant":
		frappe.throw("can only rate assistant replies", frappe.ValidationError)

	# Ownership: the canonical chat gate (raises PermissionError for another user's
	# conversation, DoesNotExistError if it vanished). session_key is permlevel-1;
	# read it via db.get_value to bypass that, matching how the worker touches it.
	_get_owned_conversation(msg.conversation)
	session_key = frappe.db.get_value(CONV, msg.conversation, "session_key")

	payload = {
		"rating": rating,
		"message_ref": message_id,
		"conversation_ref": msg.conversation,
		"session_id": _session_uuid(session_key),
		"model": msg.model or "",
		"user_ref": frappe.session.user,
		"reply_duration_ms": msg.reply_duration_ms or 0,
		"note": (note or "").strip()[:_MAX_NOTE] if rating == "down" else "",
	}
	_forward(payload)
	return {"ok": True}


def _session_uuid(session_key: str | None) -> str:
	"""Bare agent session UUID from a composite session_key, or "" when absent."""
	tail = (session_key or "").rsplit(":", 1)[-1]
	return tail if _SESSION_UUID_RE.match(tail) else ""


def _forward(payload: dict) -> None:
	"""Best-effort forward to admin. NEVER raises to the caller: a lost rating is
	acceptable (low-stakes), a blocked or errored tap is not."""
	try:
		from jarvis import admin_client

		admin_client.push_chat_feedback(payload)
	except Exception:
		frappe.log_error(title="chat feedback forward failed")


# --------------------------------------------------------------------------- #
# Once-per-session popup ("How did this session go?")
# --------------------------------------------------------------------------- #


@frappe.whitelist()
def session_feedback_status(conversation: str) -> dict:
	"""Whether the once-per-session popup is due for this conversation now.

	Costs ONE indexed row read (the ownership gate's own load) and no scan:
	``turn_count`` is a maintained counter bumped per settled turn by
	``jarvis.chat.settlement._bump_turn_count``, never a live ``COUNT(*)`` - this
	is polled after every assistant reply, so a scan here would be the most
	expensive query the feature adds.

	Not due for a File Box conversation (an unattended drop, never a chat session
	a human would rate), nor once the popup has already been answered or skipped
	for this conversation - ``session_feedback_asked_at`` is final, so Skip means
	"never again in this conversation" and survives a reload or a second tab.
	"""
	require_jarvis_access()
	# The canonical ownership gate; it already loads the row, so read the three
	# fields off the doc it returns rather than issuing a second query.
	conv = _get_owned_conversation(conversation)
	if conv.file_box:
		return {"due": False}
	due = int(conv.turn_count or 0) >= SESSION_FEEDBACK_TURN_THRESHOLD and not conv.session_feedback_asked_at
	return {"due": bool(due)}


@frappe.whitelist()
def submit_session_feedback(
	conversation: str, chip_value: str | None = None, note: str | None = None
) -> dict:
	"""Record the once-per-session popup's answer, or a Skip (``chip_value`` unset).

	Every accepted call stamps ``session_feedback_asked_at``, so the popup can
	never fire twice for this conversation whichever button was pressed. A Skip
	records nothing and is never forwarded to admin (there is no response to
	store); a real reaction is forwarded best-effort. The optional note is kept
	only on "Okay" or worse - the popup only reveals the field there, and a note
	typed before switching to a positive reaction must not ride along.

	A malformed reaction is rejected BEFORE the stamp: the one-shot popup is the
	user's only chance to answer in this conversation, so a broken client must
	not silently burn it.

	Returns ``{"ok": True, "recorded": <bool>}`` even when the forward fails: like
	the thumbs tap, a lost response is acceptable and a blocked popup is not.
	"""
	require_jarvis_access()
	_get_owned_conversation(conversation)
	if chip_value and chip_value not in _SESSION_CHIP_VALUES:
		frappe.throw("chip_value is not one of the preset reactions", frappe.ValidationError)

	# update_modified=False: this is server-set popup metadata, not a user edit of
	# the conversation - matching every other db.set_value on this doctype.
	frappe.db.set_value(
		CONV, conversation, "session_feedback_asked_at", frappe.utils.now(), update_modified=False
	)
	if not chip_value:
		return {"ok": True, "recorded": False}

	payload = {
		"kind": "Session",
		"session_ref": conversation,
		"chip_value": chip_value,
		"user_ref": frappe.session.user,
		"note": (note or "").strip()[:_MAX_NOTE] if chip_value in _SESSION_LOW_CHIPS else "",
	}
	_forward_session(payload)
	return {"ok": True, "recorded": True}


def _forward_session(payload: dict) -> None:
	"""Best-effort forward to admin, same contract as ``_forward`` above: a lost
	response is acceptable, a blocked popup is not. Named verbatim in
	``admin_client.push_session_feedback``'s docstring - keep the two in step."""
	try:
		from jarvis import admin_client

		admin_client.push_session_feedback(payload)
	except Exception:
		frappe.log_error(title="session feedback forward failed")
