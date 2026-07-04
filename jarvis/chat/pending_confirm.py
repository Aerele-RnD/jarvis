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

import redis.exceptions

import frappe

_TTL_S = 900  # 15 min; a confirmation token the user must click within
_PREFIX = "jarvis:pending_confirm:"
# Per-owner index: a Redis set of the owner's currently-live token ids, so the
# resync endpoint can enumerate a user's own parked confirmations after a reload
# or reconnect. TTL discipline mirrors selfhost.get_active_turn: dead members
# (token record expired/consumed) are pruned on read; the set key itself is
# given a refreshed TTL on every mint so an emptied set self-expires.
_OWNER_PREFIX = "jarvis:pending_confirm:owner:"


def _key(token: str) -> str:
	return _PREFIX + token


def _owner_key(owner: str) -> str:
	return _OWNER_PREFIX + owner


def args_hash(tool: str, args: dict) -> str:
	"""Stable hash of the tool + its canonical args, so a token is bound to
	the EXACT call. Canonical = json.dumps(args, sort_keys=True, default=str).
	"""
	canonical = json.dumps(args, sort_keys=True, default=str)
	return hashlib.sha256(f"{tool}:{canonical}".encode()).hexdigest()


def mint(*, conversation: str, owner: str, tool: str, args: dict, run_id: str,
		 exec_user: str | None = None) -> str:
	"""Store a pending call and return a fresh single-use token
	(secrets.token_urlsafe(24)). The stored record carries conversation,
	owner, tool, args (the full dict - this is the authoritative payload
	that will execute), args_hash, run_id, exec_user. TTL _TTL_S. Returns
	the token.

	``owner`` is the CONVERSATION OWNER - the human who sees the card, clicks
	Confirm, and whose browser is subscribed. Delivery + binding + confirm all
	key off this identity. ``exec_user`` is the scoped model-execution identity
	the confirmed write must run AS (so a confirm can never exceed the model
	path's permission scope). In managed mode owner == exec_user; in self-host
	owner is the operator and exec_user is the restricted tool user. It defaults
	to ``owner`` when omitted (managed-mode back-compat).
	"""
	token = secrets.token_urlsafe(24)
	record = {
		"conversation": conversation,
		"owner": owner,
		"exec_user": exec_user or owner,
		"tool": tool,
		"args": args,
		"args_hash": args_hash(tool, args),
		"run_id": run_id,
	}
	frappe.cache().set_value(_key(token), record, expires_in_sec=_TTL_S)
	# Index the token under its owner so list_for_owner can re-surface it. Best
	# effort: the token record is the source of truth (owner binding + execution
	# both read it), so an index hiccup must never block the park.
	try:
		cache = frappe.cache()
		cache.sadd(_owner_key(owner), token)
		cache.expire_key(_owner_key(owner), _TTL_S)
	except Exception:
		pass
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
	# GETDEL is a raw redis-py command, not one of RedisWrapper's own wrapped
	# methods (get_value/set_value/...), so unlike those it is NOT wrapped in
	# RedisWrapper's usual suppress(redis.exceptions.ConnectionError) - a
	# transient redis blip here would otherwise propagate as an uncaught 500
	# instead of the graceful None the caller expects (treated as
	# not-consumable -> InvalidConfirmation; the token is not burned, the user
	# can retry). Also defensively catch ResponseError: GETDEL requires
	# redis-server >= 6.2, and an older/misconfigured server rejects the
	# command outright. Either error returns None here WITHOUT falling back to
	# a non-atomic get-then-delete, which would reintroduce the very race
	# GETDEL exists to close - only the same atomic getdel is retried on a
	# later call.
	try:
		raw = frappe.cache().getdel(full_key)
	except (redis.exceptions.ConnectionError, redis.exceptions.ResponseError):
		return None
	frappe.local.cache.pop(full_key, None)
	if raw is None:
		return None
	# Drop the now-dead token from the owner index (best effort - list_for_owner
	# also prunes dead members on read, so a miss here self-heals).
	try:
		frappe.cache().srem(_owner_key(owner), token)
	except Exception:
		pass
	return pickle.loads(raw)


def list_for_owner(owner: str, conversation: str | None = None) -> list[dict]:
	"""Return the owner's currently-live parked records (each with its ``token``
	attached), newest-first is NOT guaranteed. Reads the per-owner index, peeks
	each token, and:
	  - prunes dead members (token record expired/consumed) from the index,
	  - filters to records whose stored owner matches ``owner`` (defense in
	    depth - never returns another user's token),
	  - filters to ``conversation`` when one is given.

	Never returns another user's tokens. Used by the resync endpoint so the SPA
	can re-surface confirmation cards after a reload/reconnect.
	"""
	if not owner:
		return []
	try:
		members = {
			m.decode() if isinstance(m, bytes) else m
			for m in (frappe.cache().smembers(_owner_key(owner)) or set())
		}
	except Exception:
		return []
	if not members:
		return []
	out: list[dict] = []
	dead: list[str] = []
	for token in members:
		record = peek(token)
		if not record:
			dead.append(token)
			continue
		if record.get("owner") != owner:
			continue
		if conversation is not None and record.get("conversation") != conversation:
			continue
		out.append({**record, "token": token})
	if dead:
		try:
			frappe.cache().srem(_owner_key(owner), *dead)
		except Exception:
			pass
	return out
