"""REV-3 OAuth endpoints. Bench drives the OAuth flow end-to-end;
customer's browser is the only "laptop-side" actor (no helper script).

Two whitelisted endpoints:
  - begin_paste_signin(provider, model) → {nonce, authorize_url}
  - complete_paste_signin(nonce, redirected_url) → {account_email, sync_status}

Plus disconnect() to reverse the connection.
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
	UnknownProviderError, build_authorize_url, extract_account_id, get_provider,
)


class TokenExchangeError(JarvisError):
	"""Provider's /oauth/token endpoint rejected the code or had an error.

	The ``code`` attribute is one of the opaque codes from
	``_TOKEN_EXCHANGE_OPAQUE_CODES`` below; the message is safe to surface
	to the customer. The full provider response detail is logged via
	``frappe.log_error`` server-side at raise time so ops can triage.
	"""

	def __init__(self, message: str, *, code: str = "token_exchange_failed"):
		super().__init__(message)
		self.code = code


# Provider error_description → opaque code mapping.
# Provider responses can leak implementation detail; in particular,
# ``invalid_client`` distinguishes "client_secret needed" from
# "client_secret wrong", an oracle on gemini-cli's confidential-client
# secret. We collapse the provider's distinction into opaque buckets.
# Sprint-1 Important #6 from the 2026-06-16 code review.
_TOKEN_EXCHANGE_OPAQUE_CODES = {
	"invalid_grant": (
		"code_invalid",
		"The authorization code was rejected. Start a fresh sign-in.",
	),
	"invalid_client": (
		"auth_failed",
		"The provider rejected this sign-in. If this keeps happening, "
		"contact support.",
	),
	"invalid_request": (
		"auth_failed",
		"The provider rejected this sign-in. If this keeps happening, "
		"contact support.",
	),
}


_CACHE_KEY = "jarvis.oauth.codex_signin"
_NONCE_TTL_SECS = 600
_HTTP_TIMEOUT = 30
_REDIRECT_URI = "http://localhost:1455/auth/callback"
# Codex/gemini-cli's CLI-specific model IDs (not OpenAI/Google's standard
# API model names). Mirrors the SUBSCRIPTION_MODELS dict in
# jarvis_onboarding.js / jarvis_account.js - keep both in sync. Customer-
# supplied models outside this set get coerced to _DEFAULT_MODEL before
# being cached: sending a standard-API model (e.g. "gpt-4o") through the
# codex auth tunnel makes openclaw's codex extension fail every chat turn
# with ProviderAuthError: "No API key found for provider openai" (it
# treats model-mismatch as auth failure, not as a clearer model error).
# Live-confirmed 2026-06-11 on jarvis-pool-05b704.
#
# Catalog sync: these values must match openclaw 2026.6.4's bundled
# codex catalog (the version pinned by jarvis_admin.host_setup.
# DEFAULT_OPENCLAW_IMAGE). The script at
# jarvis-fleet-agent/scripts/verify-openclaw-assumptions.sh asserts at
# image-bump time that the catalog still contains "gpt-5.5"; if it ever
# fails because the catalog drifted, update this set + the JS mirrors
# atomically and re-run the script before bumping the image pin.
_SUBSCRIPTION_MODELS = {
	"OpenAI": {"gpt-5.5", "gpt-5.4", "gpt-5.4-mini"},
	"Google Gemini": {"gemini-2.0-pro", "gemini-1.5-pro", "gemini-1.5-flash"},
}
_DEFAULT_MODEL = {"OpenAI": "gpt-5.5", "Google Gemini": "gemini-2.0-pro"}


def _coerce_subscription_model(provider: str, model: str) -> str:
	"""Return ``model`` if valid for ``provider``'s subscription mode,
	else fall back to ``_DEFAULT_MODEL[provider]``. Empty string for an
	unknown provider (begin_paste_signin already rejects those upstream)."""
	valid = _SUBSCRIPTION_MODELS.get(provider, set())
	if model and model in valid:
		return model
	return _DEFAULT_MODEL.get(provider, "")


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
	to open in their browser.

	Gated on System Manager (Sprint-1 Important from the 2026-06-16 code
	review). The cached nonce is bound to ``frappe.session.user`` so
	another logged-in System Manager can't complete an in-flight sign-in
	that someone else started.
	"""
	frappe.only_for("System Manager")
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
		"model": _coerce_subscription_model(provider, model),
		"status": "pending",
		"expires_at_ts": int(time.time()) + _NONCE_TTL_SECS,
		"verifier": verifier,
		"state": state,
		"originator_user": frappe.session.user,
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
	they copied from the browser's address bar.

	Gated on System Manager + per-user nonce binding: another System
	Manager can't accidentally (or maliciously) complete a sign-in that
	someone else started. Sprint-1 Important from the 2026-06-16 code
	review.
	"""
	frappe.only_for("System Manager")
	entry = frappe.cache.hget(_CACHE_KEY, nonce)
	if not entry:
		return _err("unknown_nonce", "nonce not recognized")
	if entry["expires_at_ts"] < int(time.time()):
		return _err("expired", "nonce has expired; generate a new sign-in URL")
	if entry["status"] != "pending":
		return _err("not_pending", f"nonce status is {entry['status']!r}")
	# Per-user binding: the user who began the sign-in must be the same
	# one completing it. Without this, a second System Manager on the same
	# site could complete a peer's pending OAuth with a redirect they
	# control. The error message is the same as "unknown_nonce" on purpose
	# (don't leak which nonces are live).
	if entry.get("originator_user") != frappe.session.user:
		return _err("unknown_nonce", "nonce not recognized")

	parsed = _parse_redirected_url(redirected_url)
	if not parsed["code"]:
		return _err("missing_code", "no `code` parameter found in the pasted URL")
	if parsed["state"] != entry["state"]:
		return _err("state_mismatch",
		            "the `state` parameter doesn't match; "
		            "regenerate the sign-in URL and try again")

	provider = entry["provider"]
	# Re-coerce belt-and-suspenders: nonces live up to 10 min, so
	# _SUBSCRIPTION_MODELS could in principle be tightened mid-flight
	# (e.g. a codex model deprecated). begin_paste_signin already coerced
	# at cache time; doing it again here means the cached model can never
	# escape the codex-valid set even across config reloads.
	model = _coerce_subscription_model(provider, entry["model"])

	try:
		tokens = _exchange_code(
			provider=provider,
			code=parsed["code"],
			code_verifier=entry["verifier"],
		)
	except TokenExchangeError as e:
		# Nonce NOT cleared; customer can paste again if they fix the URL.
		# `e.code` is one of the pre-mapped opaque codes from
		# _TOKEN_EXCHANGE_OPAQUE_CODES; the message is the user-safe text
		# from that same map, NOT the raw provider response. The provider
		# detail was logged via frappe.log_error inside _exchange_code.
		return _err(e.code, str(e))

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
		"accountId": extract_account_id(provider, access_token),
		"clientId": p["client_id"],
	}

	admin_client.post_push_oauth_blob(p["openclaw_provider"], blob)
	# force=True is mandatory here. The OAuth blob lives in the container's
	# auth-profiles.json (out-of-band from Jarvis Settings), so on_update's
	# diff classifier sees no change and skips the re-render+restart when
	# a customer re-authorizes with the same provider+model. Without the
	# restart the container's openclaw keeps serving stale auth, surfacing
	# as the same ProviderAuthError the re-auth was meant to fix. Verified
	# live 2026-06-11.
	sync_result = onboarding.save_llm_creds(
		provider=provider, model=model,
		api_key="", base_url="", auth_mode="oauth",
		force=True,
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
	"""POST to provider's token endpoint, return parsed JSON.

	On error, raises TokenExchangeError with an opaque code + user-safe
	message. The full provider response detail is logged server-side via
	frappe.log_error so operators can triage without leaking the detail
	(e.g. invalid_client vs invalid_grant) to the wire. Sprint-1
	Important #6 from the 2026-06-16 code review.
	"""
	p = get_provider(provider)
	try:
		data = {
			"grant_type": "authorization_code",
			"code": code,
			"code_verifier": code_verifier,
			"client_id": p["client_id"],
			"redirect_uri": _REDIRECT_URI,
		}
		# Confidential clients (gemini-cli) require client_secret alongside
		# PKCE. Pure-PKCE clients (codex) leave it blank and we don't send it.
		if p.get("client_secret"):
			data["client_secret"] = p["client_secret"]
		resp = requests.post(
			p["token"],
			data=data,
			timeout=_HTTP_TIMEOUT,
		)
	except requests.RequestException as e:
		# Log the network detail; surface a fixed message + opaque code.
		frappe.log_error(
			title="oauth token exchange: network error",
			message=f"provider={provider!r} error={e!r}",
		)
		raise TokenExchangeError(
			"Couldn't reach the sign-in provider. Try again in a minute.",
			code="network_error",
		) from e

	if not resp.ok:
		# Parse the provider's response defensively. The full body is logged
		# server-side; only an opaque code + canned message goes back to
		# the wire so the response can't be used as an oracle (e.g.
		# distinguishing invalid_client from invalid_grant).
		raw_error = ""
		try:
			body = resp.json()
			raw_error = body.get("error") or ""
			detail = body.get("error_description") or raw_error or resp.text
		except ValueError:
			detail = resp.text
		frappe.log_error(
			title="oauth token exchange: provider rejected",
			message=(
				f"provider={provider!r} status={resp.status_code} "
				f"raw_error={raw_error!r} detail={detail!r}"
			),
		)
		opaque_code, opaque_msg = _TOKEN_EXCHANGE_OPAQUE_CODES.get(
			raw_error, ("token_exchange_failed",
						"Sign-in failed at the provider. Start a fresh sign-in."),
		)
		raise TokenExchangeError(opaque_msg, code=opaque_code)

	return resp.json()


def _fetch_account_email(provider: str, access_token: str, id_token: str) -> str:
	"""Best-effort email lookup via the provider's Bearer-authenticated
	userinfo endpoint (OpenAI + Gemini). The id_token JWT branch below is
	retained as a defensive fallback for any future provider configured
	with ``userinfo: None`` - no current provider takes that path."""
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
	# Fallback for providers with userinfo=None - parse id_token JWT for email.
	# No current provider takes this path; retained defensively.
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
def disconnect() -> dict:
	"""Clear the container's OAuth profile, flip bench back to api_key.

	Gated on System Manager (Sprint-1 Important from the 2026-06-16
	code review): writes Jarvis Settings, ends an active subscription
	connection.
	"""
	frappe.only_for("System Manager")
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
