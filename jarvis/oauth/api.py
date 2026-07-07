"""REV-3 OAuth endpoints. Bench drives the OAuth flow end-to-end;
customer's browser is the only "laptop-side" actor (no helper script).

Two whitelisted endpoints:
  - begin_paste_signin(provider, model) → {nonce, authorize_url}
  - complete_paste_signin(nonce, redirected_url) → {account_email, sync_status}

Plus disconnect() to reverse the connection.
"""
import base64
import hashlib
import json
import secrets
import time

import frappe
import requests

from jarvis import admin_client, onboarding
from jarvis.exceptions import JarvisError
from jarvis.oauth.providers import (
	UnknownProviderError, build_authorize_url, extract_account_id, get_provider,
	is_oauth_provider,
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
# Cap on how many cache fields the GC sweep visits per begin_paste_signin.
# A misbehaving caller looping begin without complete could otherwise fill
# the hash and make every subsequent begin pay an O(N) Redis trip. The cap
# bounds the sweep cost; truly stale entries get cleaned next time.
_GC_SWEEP_LIMIT = 256
_HTTP_TIMEOUT = 30
_REDIRECT_URI = "http://localhost:1455/auth/callback"
# Codex/gemini-cli's CLI-specific model IDs (not OpenAI/Google's standard
# API model names). Catalogue lives in jarvis/_subscription_models.py and
# is imported here so the chat-tier and oauth-tier validators agree on
# the same set of accepted models (previously this module declared sets
# and chat/api.py declared lists - 2026-06-16 punch-list drift item).
#
# Catalog sync constraints: these values must match openclaw 2026.6.4's
# bundled codex catalog (the version pinned by jarvis_admin.host_setup.
# DEFAULT_OPENCLAW_IMAGE). The script at
# jarvis-fleet-agent/scripts/verify-openclaw-assumptions.sh asserts at
# image-bump time that the catalog still contains "gpt-5.5"; if it ever
# fails because the catalog drifted, update jarvis/_subscription_models.py
# + the JS mirrors atomically and re-run the script before bumping the
# image pin.
from jarvis._subscription_models import DEFAULT_MODEL as _DEFAULT_MODEL
from jarvis._subscription_models import SUBSCRIPTION_MODELS as _SUBSCRIPTION_MODELS


def _coerce_subscription_model(provider: str, model: str) -> str:
	"""Return ``model`` if valid for ``provider``'s subscription mode,
	else fall back to ``_DEFAULT_MODEL[provider]``. Empty string for an
	unknown provider (begin_paste_signin already rejects those upstream)."""
	valid = _SUBSCRIPTION_MODELS.get(provider, [])
	if model and model in valid:
		return model
	return _DEFAULT_MODEL.get(provider, "")


# _ok / _err live in jarvis/_responses.py - single source of truth for the
# customer-facing envelope shape, shared with jarvis/api.py and any future
# bench endpoint. Punch-list item from the 2026-06-16 review.
from jarvis._responses import err as _err
from jarvis._responses import ok as _ok


def _generate_pkce() -> tuple[str, str]:
	"""Return (verifier, challenge) per RFC 7636."""
	verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
	challenge = base64.urlsafe_b64encode(
		hashlib.sha256(verifier.encode()).digest()
	).rstrip(b"=").decode()
	return verifier, challenge


def _gc_expired_nonces() -> None:
	"""Sweep ``_CACHE_KEY`` for entries past their ``expires_at_ts`` and drop
	them.

	The OAuth nonce cache is a Redis hash where each field is a per-flow
	nonce. ``frappe.cache.hset`` doesn't honour per-field TTLs (Redis HSET
	can't), so abandoned sign-ins (customer started the flow, closed the
	tab, never pasted the URL) leave their PKCE verifier + state hanging
	in the hash until the whole key gets wiped. Punch-list "stale PKCE
	verifiers + unconsumed nonces never GC'd" from the 2026-06-16 review.

	Called opportunistically from begin_paste_signin so the hash stays
	bounded without a separate scheduled job. Cost is one HGETALL per
	begin (~ms-cheap until N gets large; the sweep limit caps the
	worst case).
	"""
	try:
		entries = frappe.cache.hgetall(_CACHE_KEY) or {}
	except Exception:
		# Best-effort: a Redis hiccup mustn't block a fresh sign-in.
		return
	now_ts = int(time.time())
	for i, (field, value) in enumerate(entries.items()):
		if i >= _GC_SWEEP_LIMIT:
			break
		# hgetall on a freshly-wiped cache can return {} - any field shape
		# that doesn't carry expires_at_ts is something we didn't write
		# and shouldn't try to interpret.
		try:
			expires_at_ts = (value or {}).get("expires_at_ts")
		except AttributeError:
			continue
		if not expires_at_ts or expires_at_ts < now_ts:
			# Decode bytes-vs-str defensively - Frappe's redis hash returns
			# bytes on some configs and str on others.
			key = field.decode() if isinstance(field, bytes) else field
			frappe.cache.hdel(_CACHE_KEY, key)


def _begin_signin(provider: str, model: str, *, pool: bool) -> dict:
	"""Shared nonce/PKCE/state machinery behind ``begin_paste_signin`` (the
	DIRECT single-model flow) and ``begin_pool_account_signin`` (the POOL
	multi-account capture flow).

	Mints a nonce + PKCE pair, caches the verifier/state bound to
	``frappe.session.user``, and returns the authorize URL. ``pool`` tags
	the cached entry so ``complete_pool_account_signin`` can tell a POOL
	nonce apart from a DIRECT one. The caller is responsible for the
	System-Manager gate.
	"""
	try:
		get_provider(provider)
	except UnknownProviderError as e:
		return _err("unknown_provider", str(e))

	# GC abandoned sign-ins BEFORE writing the new nonce. Otherwise a
	# user who loops begin without ever completing (e.g. wizard reload
	# while debugging) grows the cache hash unboundedly.
	_gc_expired_nonces()

	nonce = secrets.token_hex(24)
	verifier, challenge = _generate_pkce()
	state = secrets.token_urlsafe(16)

	authorize_url = build_authorize_url(
		provider=provider,
		redirect_uri=_REDIRECT_URI,
		code_challenge=challenge,
		state=state,
		# Pool accounts feed cli-proxy-api, which needs the codex-scope
		# token audience; the direct flow keeps the connectors scope for
		# openclaw's own codex path. See providers.py pool_scope.
		pool=pool,
	)

	entry = {
		"provider": provider,
		"model": _coerce_subscription_model(provider, model),
		"status": "pending",
		"expires_at_ts": int(time.time()) + _NONCE_TTL_SECS,
		"verifier": verifier,
		"state": state,
		"originator_user": frappe.session.user,
	}
	if pool:
		entry["pool"] = True
	frappe.cache.hset(_CACHE_KEY, nonce, entry)

	return _ok({
		"nonce": nonce,
		"authorize_url": authorize_url,
		"expires_in": _NONCE_TTL_SECS,
	})


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
	return _begin_signin(provider, model, pool=False)


@frappe.whitelist()
def begin_pool_account_signin(provider: str, model: str) -> dict:
	"""POOL variant of ``begin_paste_signin``: mint a nonce + PKCE pair for
	capturing ONE more account into a pool "subscription" model.

	Same nonce/PKCE/state machinery and same System-Manager + per-user
	binding as the DIRECT flow; the only difference is the cached entry is
	tagged ``pool`` so ``complete_pool_account_signin`` can distinguish it.
	Unlike the DIRECT flow this captures a blob and hands it back to the
	caller (see ``complete_pool_account_signin``) instead of writing creds
	to Jarvis Settings / pushing to the container.
	"""
	frappe.only_for("System Manager")
	return _begin_signin(provider, model, pool=True)


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


def _validate_signin_nonce(nonce: str):
	"""Validate a cached sign-in nonce shared by the DIRECT and POOL complete
	endpoints: existence, expiry (evicts on read), pending status, and the
	per-user binding.

	Returns ``(entry, None)`` on success or ``(None, err_envelope)`` on any
	failure. The error message for a user-binding mismatch is deliberately
	the same as "unknown_nonce" so live nonces aren't leaked.
	"""
	entry = frappe.cache.hget(_CACHE_KEY, nonce)
	if not entry:
		return None, _err("unknown_nonce", "nonce not recognized")
	if entry["expires_at_ts"] < int(time.time()):
		# Drop the expired field so the hash doesn't grow with dead
		# entries waiting on the periodic GC sweep. Companion to the
		# _gc_expired_nonces sweep on begin.
		frappe.cache.hdel(_CACHE_KEY, nonce)
		return None, _err("expired", "nonce has expired; generate a new sign-in URL")
	if entry["status"] != "pending":
		return None, _err("not_pending", f"nonce status is {entry['status']!r}")
	# Per-user binding: the user who began the sign-in must be the same
	# one completing it. Without this, a second System Manager on the same
	# site could complete a peer's pending OAuth with a redirect they
	# control. The error message is the same as "unknown_nonce" on purpose
	# (don't leak which nonces are live).
	if entry.get("originator_user") != frappe.session.user:
		return None, _err("unknown_nonce", "nonce not recognized")
	return entry, None


def _exchange_and_build_blob(entry: dict, redirected_url: str):
	"""Parse the pasted redirect, verify state (constant-time), exchange the
	code, and build the openclaw auth-profile blob.

	Shared by the DIRECT (``complete_paste_signin``) and POOL
	(``complete_pool_account_signin``) flows so both build an identically
	shaped blob. Returns ``(result, None)`` on success where ``result`` is
	``{"provider", "model", "email", "blob"}``, or ``(None, err_envelope)``
	on any validation / token-exchange failure. Does NOT push the blob,
	save creds, or touch Jarvis Settings — those side effects belong to the
	DIRECT caller only.
	"""
	parsed = _parse_redirected_url(redirected_url)
	if not parsed["code"]:
		return None, _err("missing_code", "no `code` parameter found in the pasted URL")
	# Constant-time compare on the state parameter. The state value is the
	# OAuth CSRF nonce - if an attacker can observe how long the
	# comparison takes, plain ``!=`` short-circuits on the first
	# differing byte and leaks a prefix-recovery oracle. secrets.compare_digest
	# runs in constant time over the longer of the two inputs.
	# Punch-list "state comparison non-constant-time" from the 2026-06-16 review.
	if not secrets.compare_digest(parsed["state"] or "", entry["state"] or ""):
		return None, _err("state_mismatch",
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
		return None, _err(e.code, str(e))

	access_token = tokens.get("access_token")
	if not access_token:
		return None, _err("token_exchange_failed", "provider returned no access_token")

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
		# Retain the id_token: a downstream reformat to CLIProxyAPI-codex
		# format needs it. Harmless to the DIRECT push path, which ignores
		# unknown blob keys.
		"id_token": tokens.get("id_token") or "",
	}
	return {"provider": provider, "model": model, "email": email, "blob": blob}, None


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
	entry, err = _validate_signin_nonce(nonce)
	if err:
		return err

	result, err = _exchange_and_build_blob(entry, redirected_url)
	if err:
		return err

	provider = result["provider"]
	model = result["model"]
	email = result["email"]
	blob = result["blob"]

	p = get_provider(provider)
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


@frappe.whitelist()
def complete_pool_account_signin(nonce: str, redirected_url: str) -> dict:
	"""Capture ONE more chat-subscription account for a pool "subscription"
	model, and RETURN the blob for the caller to stash in a pool
	subscription-account row.

	Same validation as ``complete_paste_signin`` (nonce+user binding,
	constant-time state compare, code exchange) and builds the same
	openclaw blob shape (WITH ``id_token``) — but this endpoint is
	capture-only: it does NOT call ``save_llm_creds``, does NOT push the
	blob to the container, and does NOT write to Jarvis Settings. The
	frontend collects N of these into a pool subscription and persists them
	later via ``save_llm_pool`` (which routes accounts[].oauth_blob through
	``pool_serialize.build_pool_payload`` into the oauth_blobs map).

	Gated on System Manager + per-user nonce binding; the nonce must have
	been minted by ``begin_pool_account_signin`` (carries ``pool=True``).
	Returns ``{account_ref, label, oauth_blob, account_email}`` where
	``account_ref`` is a freshly generated ``SUB_<hex>`` id that satisfies
	``^[A-Za-z0-9_-]{1,64}$`` and ``oauth_blob`` is the JSON-encoded blob.
	"""
	frappe.only_for("System Manager")
	entry, err = _validate_signin_nonce(nonce)
	if err:
		return err
	# Only nonces minted by begin_pool_account_signin may be completed here;
	# a DIRECT paste-signin nonce must go through complete_paste_signin. Same
	# opaque message as unknown_nonce so live nonces aren't leaked.
	if not entry.get("pool"):
		return _err("unknown_nonce", "nonce not recognized")

	result, err = _exchange_and_build_blob(entry, redirected_url)
	if err:
		return err

	email = result["email"]
	# account_ref is the stable per-account key the pool subscription row is
	# stored under (and later fed to build_pool_payload -> oauth_blobs). It
	# must match ^[A-Za-z0-9_-]{1,64}$; "SUB_" + 16 hex chars = 20 chars.
	account_ref = "SUB_" + secrets.token_hex(8)

	# Capture-only: clear the nonce (single-use, like complete_paste_signin)
	# and hand the blob back. No push, no save_llm_creds, no Settings write.
	frappe.cache.hdel(_CACHE_KEY, nonce)
	return _ok({
		"account_ref": account_ref,
		"label": email,
		"oauth_blob": json.dumps(result["blob"]),
		"account_email": email,
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
		detail = resp.text
		try:
			body = resp.json()
			err = body.get("error")
			# RFC-6749 says `error` is a STRING code, but some providers return
			# it as an object. Only a string is a valid (hashable) opaque-code
			# lookup key; for an object, pull a nested code if one is present,
			# else fall through to the generic message. This guards the
			# `unhashable type: 'dict'` crash from using `error` as a dict key.
			if isinstance(err, str):
				raw_error = err
			elif isinstance(err, dict):
				nested = err.get("type") or err.get("code") or err.get("error")
				raw_error = nested if isinstance(nested, str) else ""
			detail = body.get("error_description") or err or resp.text
		except ValueError:
			pass
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
	except Exception:
		# ValueError used to be listed explicitly but it's a subclass
		# of Exception - the union was redundant. Anything that goes
		# wrong parsing a JWT id_token (malformed base64, broken JSON,
		# missing dots) is non-fatal: id_token is a best-effort source
		# for the email hint, callers always have a fallback.
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
	# DON'T wipe _CACHE_KEY here. The previous shape called
	# frappe.cache.delete_key(_CACHE_KEY), which nukes every pending
	# OAuth sign-in across the whole site - so a second System Manager
	# mid-paste-signin would see their nonce vanish under them when a
	# peer happened to click Disconnect. The cache holds only short-TTL
	# (10 min) per-user-bound nonces; _gc_expired_nonces sweeps them on
	# the next begin call. Punch-list "disconnect() wipes entire OAuth
	# signin cache hash" from the 2026-06-16 review.
	return _ok({})


# Auth modes that mean "a single chat subscription, served DIRECT via the
# container's auth-profiles.json (codex / gemini-cli runtime)" - NOT the pooled
# cliproxy path. "oauth" is the REV-1 canonical value; "subscription" is the
# legacy value some migrated tenants still carry.
_DIRECT_SUBSCRIPTION_MODES = {"oauth", "subscription"}


def _is_direct_subscription(auth_mode: str, has_models: bool,
                            proxy_active: bool, provider_is_oauth: bool) -> bool:
	"""True when the tenant is on the legacy DIRECT chat-subscription path.

	These tenants keep their LLM config in the flat ``llm_*`` / ``llm_oauth_*``
	fields (the ``v1_seed_llm_models`` migration deliberately skips oauth /
	subscription tenants) and are served by the container's
	``auth-profiles.json``, NOT the pooled cliproxy sidecar. ``get_llm_config``
	reads only the ``models[]`` child table, so the unified LlmPoolEditor can
	neither see nor re-authorize them. This predicate lets the SPA fall back to
	the DIRECT re-authorize (``begin_paste_signin`` / ``complete_paste_signin``)
	instead of silently offering only the pool editor.

	``has_models`` keys on the PRESENCE of ANY ``models[]`` row (enabled or
	not), matching ``get_llm_config``'s enabled-agnostic read — a pooled tenant
	mid-reconfiguration with all rows disabled must NOT be misclassified as
	direct (that would hide their real pool behind the direct card).

	``provider_is_oauth`` gates on ``llm_provider`` being an OAuth-capable
	provider: a tenant left in ``oauth`` mode with a non-OAuth provider (e.g.
	``Anthropic`` after ``reset_onboarding``) is NOT offered a re-authorize card
	that would only ever error ``unknown_provider``.

	Pure (no DB access) so the branch logic is unit-testable without a site.
	"""
	return (
		(auth_mode or "") in _DIRECT_SUBSCRIPTION_MODES
		and not proxy_active
		and not has_models
		and provider_is_oauth
	)


@frappe.whitelist()
def get_direct_subscription_status() -> dict:
	"""Surface the flat-field DIRECT chat-subscription connection to the SPA.

	The Account SPA's ``LlmPoolEditor`` is fed by ``onboarding.get_llm_config``,
	which reads ONLY the ``models[]`` child table. Existing direct
	chat-subscription (OAuth) tenants have an empty ``models[]`` and their
	connection lives in the flat ``llm_*`` / ``llm_oauth_*`` fields - invisible
	to that editor, so after the desk->SPA account migration they had no way to
	re-authorize. This read-only endpoint lets ``AccountView`` detect such a
	tenant and render a DIRECT re-authorize / disconnect card, WITHOUT migrating
	them onto the proxy path (a lone subscription row in ``models[]`` would force
	``compute_proxy_active`` true and re-architect them onto cliproxy with no
	credential blob).

	System-Manager only (matches the rest of the LLM-config surface). Never
	returns token material - only display metadata.
	"""
	frappe.only_for("System Manager")
	settings = frappe.get_single("Jarvis Settings")
	auth_mode = (settings.get("llm_auth_mode") or "").strip()
	provider = settings.get("llm_provider") or ""
	proxy_active = bool(settings.get("proxy_active"))
	has_models = bool(settings.get("models"))
	connected_at = settings.get("llm_oauth_connected_at")
	is_direct = _is_direct_subscription(
		auth_mode, has_models, proxy_active, is_oauth_provider(provider),
	)
	return {
		"is_direct_subscription": is_direct,
		"connected": bool(connected_at),
		"auth_mode": auth_mode,
		"provider": provider,
		"model": settings.get("llm_model") or "",
		"account_email": settings.get("llm_oauth_account_email") or "",
		"connected_at": str(connected_at) if connected_at else "",
		# Lets AccountView gate the container-OAuth "Connection" card to proxy
		# tenants: direct tenants are covered by DirectSubscriptionCard, and an
		# api_key tenant has no OAuth profile so the card would misleadingly read
		# "Not connected".
		"proxy_active": proxy_active,
	}
