"""Pending-confirmation token store for the write-safety confirmation gate
(issue #186).

A mutating tool call that needs a human's go-ahead is parked here under a
single-use token instead of running immediately. The gate itself (later
task) mints a token when it intercepts such a call, shows the user a
preview built from ``peek``, and only actually runs the call once
``consume`` returns the stored record for the confirming click.

This module only owns the store - it does not decide which tools need
confirmation and does not run anything.

Storage: ``frappe.cache()`` (Redis), one key per token, single round trip
TTL so a token that nobody clicks self-expires instead of leaking forever.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import secrets

import frappe

_TTL_S = 900  # 15 min; a confirmation token the user must click within
_PREFIX = "jarvis:pending_confirm:"


def _key(token: str) -> str:
	return _PREFIX + token


def args_hash(tool: str, args: dict) -> str:
	"""Stable hash of the tool + its canonical args, so a token is bound to
	the EXACT call. Canonical = json.dumps(args, sort_keys=True, default=str).
	"""
	canonical = json.dumps(args, sort_keys=True, default=str)
	return hashlib.sha256(f"{tool}:{canonical}".encode()).hexdigest()


def mint(*, conversation: str, owner: str, tool: str, args: dict, run_id: str) -> str:
	"""Store a pending call and return a fresh single-use token
	(secrets.token_urlsafe(24)). The stored record carries conversation,
	owner, tool, args (the full dict - this is the authoritative payload
	that will execute), args_hash, run_id. TTL _TTL_S. Returns the token.
	"""
	token = secrets.token_urlsafe(24)
	record = {
		"conversation": conversation,
		"owner": owner,
		"tool": tool,
		"args": args,
		"args_hash": args_hash(tool, args),
		"run_id": run_id,
	}
	frappe.cache().set_value(_key(token), record, expires_in_sec=_TTL_S)
	return token


def peek(token: str) -> dict | None:
	"""Return the stored record (dict) without consuming it, or None if the
	token is unknown/expired. Used to build the preview/UI event. Does NOT
	validate ownership - callers that act on it must.
	"""
	if not token:
		return None
	return frappe.cache().get_value(_key(token), use_local_cache=False)


def consume(token: str, *, owner: str, conversation: str) -> dict | None:
	"""Validate AND atomically single-use-consume. Returns the stored record
	ONLY when: token exists, record.owner == owner, record.conversation ==
	conversation. On success the token is deleted BEFORE returning (single
	use - a second consume returns None). On any mismatch returns None and
	does NOT delete (so a wrong-owner probe cannot burn a legitimate token).

	Atomicity: ownership is checked first with a plain (non-destructive)
	read, so a mismatched call never touches the stored key. Only once
	ownership matches do we delete - and that delete uses Redis' GETDEL,
	a single atomic server-side command (get-and-delete in one round trip,
	no separate check-then-delete on our side). If two confirmed consumes
	race each other here, the server serializes the two GETDELs: exactly
	one gets the pickled record back, the other gets None. That is the
	single-use guarantee - it does not depend on Python-level locking,
	which would not help anyway across separate worker processes.
	"""
	if not token:
		return None
	record = frappe.cache().get_value(_key(token), use_local_cache=False)
	if not record:
		return None
	if record.get("owner") != owner or record.get("conversation") != conversation:
		return None

	full_key = frappe.cache().make_key(_key(token))
	raw = frappe.cache().getdel(full_key)
	frappe.local.cache.pop(full_key, None)
	if raw is None:
		return None
	return pickle.loads(raw)
