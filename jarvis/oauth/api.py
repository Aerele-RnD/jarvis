"""REV-3 OAuth endpoints. Bench drives the OAuth flow end-to-end;
customer's browser is the only "laptop-side" actor (no helper script).

Two whitelisted endpoints:
  - begin_paste_signin(provider, model) → {nonce, authorize_url}
  - complete_paste_signin(nonce, redirected_url) → {account_email, sync_status}

Plus disconnect() and share_paste_signin() (rate-limited email send).
"""
import base64
import hashlib
import secrets
import time

import frappe

from jarvis.oauth.providers import (
	UnknownProviderError, build_authorize_url, get_provider,
)

_CACHE_KEY = "jarvis.oauth.codex_signin"
_NONCE_TTL_SECS = 600
_SHARE_LIMIT = 5
_HTTP_TIMEOUT = 30
_REDIRECT_URI = "http://localhost:1455/auth/callback"
_DEFAULT_MODEL = {"OpenAI": "gpt-4o", "Google Gemini": "gemini-2.0-pro"}


def _ok(data: dict) -> dict:
	return {"ok": True, "data": data}


def _err(code: str, message: str) -> dict:
	return {"ok": False, "error": {"code": code, "message": message}}


def _generate_pkce() -> tuple[str, str]:
	"""Return (verifier, challenge) per RFC 7636."""
	verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
	challenge = base64.urlsafe_b64encode(
		hashlib.sha256(verifier.encode()).digest()
	).rstrip(b"=").decode()
	return verifier, challenge


@frappe.whitelist()
def begin_paste_signin(provider: str, model: str) -> dict:
	"""Mint a nonce + PKCE pair, return the authorize URL for the customer
	to open in their browser."""
	try:
		get_provider(provider)
	except UnknownProviderError as e:
		return _err("unknown_provider", str(e))

	nonce = secrets.token_hex(24)
	verifier, challenge = _generate_pkce()
	state = secrets.token_urlsafe(16)

	authorize_url = build_authorize_url(
		provider=provider,
		redirect_uri=_REDIRECT_URI,
		code_challenge=challenge,
		state=state,
	)

	frappe.cache.hset(_CACHE_KEY, nonce, {
		"provider": provider,
		"model": model or _DEFAULT_MODEL.get(provider, ""),
		"status": "pending",
		"expires_at_ts": int(time.time()) + _NONCE_TTL_SECS,
		"send_count": 0,
		"verifier": verifier,
		"state": state,
		"authorize_url": authorize_url,
	})

	return _ok({
		"nonce": nonce,
		"authorize_url": authorize_url,
		"expires_in": _NONCE_TTL_SECS,
	})


from urllib.parse import urlparse, parse_qs


def _parse_redirected_url(raw: str) -> dict:
	"""Defensively parse the URL the customer pasted.

	Accepts:
	  - http://localhost:1455/auth/callback?code=A&state=B
	  - ?code=A&state=B
	  - code=A&state=B

	Returns: {"code": str|None, "state": str|None}
	"""
	raw = (raw or "").strip()
	if not raw:
		return {"code": None, "state": None}

	if "://" in raw or raw.startswith("/"):
		query = urlparse(raw).query
	elif raw.startswith("?"):
		query = raw[1:]
	else:
		query = raw

	q = parse_qs(query)
	return {
		"code": (q.get("code") or [None])[0],
		"state": (q.get("state") or [None])[0],
	}


@frappe.whitelist()
def complete_paste_signin(nonce: str, redirected_url: str) -> dict:
	"""Wizard calls this after the customer signs in and pastes the URL
	they copied from the browser's address bar."""
	entry = frappe.cache.hget(_CACHE_KEY, nonce)
	if not entry:
		return _err("unknown_nonce", "nonce not recognized")
	if entry["expires_at_ts"] < int(time.time()):
		return _err("expired", "nonce has expired; generate a new sign-in URL")
	if entry["status"] != "pending":
		return _err("not_pending", f"nonce status is {entry['status']!r}")

	parsed = _parse_redirected_url(redirected_url)
	if not parsed["code"]:
		return _err("missing_code", "no `code` parameter found in the pasted URL")
	if parsed["state"] != entry["state"]:
		return _err("state_mismatch",
		            "the `state` parameter doesn't match; "
		            "regenerate the sign-in URL and try again")

	# Token exchange + blob push come in Task 1.4.
	return _err("not_implemented", "token exchange not yet wired")
