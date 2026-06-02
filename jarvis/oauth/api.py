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
import requests

from jarvis import admin_client, onboarding
from jarvis.exceptions import JarvisError
from jarvis.oauth.providers import (
	UnknownProviderError, build_authorize_url, get_provider,
)


class TokenExchangeError(JarvisError):
	"""Provider's /oauth/token endpoint rejected the code or had an error."""

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

	provider = entry["provider"]
	model = entry["model"]

	try:
		tokens = _exchange_code(
			provider=provider,
			code=parsed["code"],
			code_verifier=entry["verifier"],
		)
	except TokenExchangeError as e:
		# Nonce NOT cleared; customer can paste again if they fix the URL.
		return _err("token_exchange_failed", str(e))

	access_token = tokens.get("access_token")
	if not access_token:
		return _err("token_exchange_failed", "provider returned no access_token")

	email = (
		tokens.get("email")
		or _fetch_account_email(provider, access_token, tokens.get("id_token") or "")
	)

	p = get_provider(provider)
	now_ms = int(time.time() * 1000)
	expires_ms = now_ms + int(tokens.get("expires_in", 3600)) * 1000
	blob = {
		"type": "oauth",
		"provider": p["openclaw_provider"],
		"access": access_token,
		"refresh": tokens.get("refresh_token") or "",
		"expires": expires_ms,
		"email": email,
		"clientId": p["client_id"],
	}

	admin_client.post_push_oauth_blob(p["openclaw_provider"], blob)
	sync_result = onboarding.save_llm_creds(
		provider=provider, model=model,
		api_key="", base_url="", auth_mode="oauth",
	)

	settings = frappe.get_single("Jarvis Settings")
	settings.db_set("llm_oauth_account_email", email, update_modified=False)
	settings.db_set("llm_oauth_connected_at",
	                frappe.utils.now_datetime(),
	                update_modified=False)

	frappe.cache.hdel(_CACHE_KEY, nonce)
	return _ok({
		"account_email": email,
		"last_sync_status": (sync_result or {}).get("last_sync_status", ""),
	})


def _exchange_code(*, provider: str, code: str, code_verifier: str) -> dict:
	"""POST to provider's token endpoint, return parsed JSON."""
	p = get_provider(provider)
	try:
		resp = requests.post(
			p["token"],
			data={
				"grant_type": "authorization_code",
				"code": code,
				"code_verifier": code_verifier,
				"client_id": p["client_id"],
				"redirect_uri": _REDIRECT_URI,
			},
			timeout=_HTTP_TIMEOUT,
		)
	except requests.RequestException as e:
		raise TokenExchangeError(f"network error: {e}") from e

	if not resp.ok:
		try:
			body = resp.json()
			detail = body.get("error_description") or body.get("error") or resp.text
		except ValueError:
			detail = resp.text
		raise TokenExchangeError(f"HTTP {resp.status_code}: {detail}")

	return resp.json()


def _fetch_account_email(provider: str, access_token: str, id_token: str) -> str:
	"""Best-effort email lookup. OpenAI: userinfo endpoint. Gemini: id_token JWT."""
	p = get_provider(provider)
	if p["userinfo"]:
		try:
			resp = requests.get(
				p["userinfo"],
				headers={"Authorization": f"Bearer {access_token}"},
				timeout=_HTTP_TIMEOUT,
			)
			if resp.ok:
				return resp.json().get("email") or ""
		except requests.RequestException:
			pass
		return ""
	# Gemini path — parse JWT payload for email claim
	if not id_token or id_token.count(".") < 2:
		return ""
	try:
		import json as _json
		_, payload, _ = id_token.split(".", 2)
		padding = "=" * (-len(payload) % 4)
		decoded = base64.urlsafe_b64decode(payload + padding)
		return _json.loads(decoded).get("email", "") or ""
	except (ValueError, Exception):
		return ""


@frappe.whitelist()
def share_paste_signin(nonce: str, recipient_email: str) -> dict:
	"""Email the authorize URL + paste-back instructions to a colleague."""
	from jarvis.oauth.email_templates import build_share_paste_signin_email
	from frappe.utils import get_url

	entry = frappe.cache.hget(_CACHE_KEY, nonce)
	if not entry:
		return _err("unknown_nonce", "nonce not recognized")
	if entry["expires_at_ts"] < int(time.time()):
		return _err("expired", "nonce has expired")
	if entry["send_count"] >= _SHARE_LIMIT:
		return _err("rate_limited",
		            f"Already shared {_SHARE_LIMIT} times.")

	minutes_left = max(0, (entry["expires_at_ts"] - int(time.time())) // 60)
	sender = getattr(frappe.session, "user_fullname", None) or frappe.session.user
	email = build_share_paste_signin_email(
		sender_name=sender,
		company=frappe.local.site,
		provider=entry["provider"],
		authorize_url=entry.get("authorize_url", ""),
		bench_url=get_url().rstrip("/"),
		minutes_left=minutes_left,
	)
	frappe.sendmail(
		recipients=[recipient_email],
		subject=email["subject"],
		message=email["body"],
		now=True,
	)
	entry["send_count"] += 1
	frappe.cache.hset(_CACHE_KEY, nonce, entry)
	return _ok({})


@frappe.whitelist()
def disconnect() -> dict:
	"""Clear the container's OAuth profile, flip bench back to api_key."""
	try:
		admin_client.post_subscription_disconnect()
	except (admin_client.AdminUnreachableError,
	        admin_client.AdminAuthError,
	        admin_client.AdminValidationError) as e:
		return _err("disconnect_failed", str(e))
	settings = frappe.get_single("Jarvis Settings")
	settings.db_set("llm_auth_mode", "api_key", update_modified=False)
	settings.db_set("last_sync_status", "disconnected", update_modified=False)
	settings.db_set("llm_oauth_account_email", "", update_modified=False)
	settings.db_set("llm_oauth_connected_at", None, update_modified=False)
	frappe.cache.delete_key(_CACHE_KEY)
	return _ok({})
