"""Per-provider OAuth metadata + authorize URL builder.

Used by jarvis.oauth.api to drive the paste-back OAuth flow against
the provider's own /oauth/authorize endpoint, with the codex-CLI-specific
parameter set that auth.openai.com requires for codex's client_id.
"""
import base64
import json
from urllib.parse import urlencode

from jarvis.exceptions import JarvisError
from jarvis.hooks import OAUTH_CLIENT_IDS, get_oauth_client_secret


class UnknownProviderError(JarvisError):
	"""Provider label not in PROVIDER_OAUTH_MAP."""


_PROVIDER_OAUTH_MAP: dict[str, dict] = {
	"OpenAI": {
		"authorize": "https://auth.openai.com/oauth/authorize",
		"token":     "https://auth.openai.com/oauth/token",
		"userinfo":  "https://api.openai.com/v1/userinfo",
		"scope":     "openid profile email offline_access api.connectors.read api.connectors.invoke",
		# POOL sign-ins (CLIProxyAPI subscription accounts) MUST use the
		# codex-CLI scope set - no connectors scopes. The connectors scope
		# yields an access_token with aud=https://api.openai.com/v1 (fine for
		# openclaw's codex app-server, which is why the DIRECT flow keeps it),
		# but cli-proxy-api's codex backend needs aud=chatgpt.com/backend-api
		# and rejects the connectors-audience token: the account loads, then
		# /v1/models returns [] and every call 502s "unknown provider".
		# Live-verified 2026-07-03; this scope set is exactly what
		# cli-proxy-api's own --codex-login requests.
		"pool_scope": "openid email profile offline_access",
		# openclaw_provider keys the auth-profiles.json entry that openclaw
		# looks up at request time. After fix/oauth-model-provider-key on
		# fleet-agent + fix/chat-worker-mapped-model-provider on this app,
		# openclaw queries by the MODEL-provider key ("openai"), not the
		# OAuth flow id ("openai-codex"). The OAuth login flow itself uses
		# the metadata above (authorize URL, scopes, codex-cli params); only
		# the storage/lookup identity is the mapped name.
		"openclaw_provider": "openai",
		# codex-cli-specific authorize params - auth.openai.com returns a
		# generic "unknown_error" page mid-flow without these.
		"extra_authorize_params": {
			"id_token_add_organizations": "true",
			"codex_cli_simplified_flow":   "true",
			"originator":                  "codex_cli_rs",
		},
	},
	"Google Gemini": {
		"authorize": "https://accounts.google.com/o/oauth2/v2/auth",
		"token":     "https://oauth2.googleapis.com/token",
		# Use Google's standard userinfo endpoint - the bundled gemini-cli
		# OAuth client doesn't have `openid` registered, so no id_token comes
		# back. Email is fetched via Bearer-authenticated userinfo instead.
		"userinfo":  "https://www.googleapis.com/oauth2/v1/userinfo?alt=json",
		# Scopes MUST match what the bundled gemini-cli OAuth client has
		# registered in its Google Cloud Console consent screen. Verified
		# against openclaw/extensions/google/oauth.shared.ts:19-23.
		# `https://www.googleapis.com/auth/generative-language` is NOT a real
		# Google OAuth scope - Google returns Error 403 restricted_client
		# "Unregistered scope(s) in the request" if anything else is sent.
		"scope":     "https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile",
		# Gemini OAuth tokens are read by the `gemini` binary which
		# openclaw spawns via the CliBackend registered at
		# extensions/google/cli-backend.ts:16 (id "google-gemini-cli").
		# auth-profiles.json must key the credential by this exact id -
		# mapping to "google" makes openclaw's CLI dispatch path miss the
		# stored credential (different lookup key).
		"openclaw_provider": "google-gemini-cli",
		"extra_authorize_params": {
			"access_type": "offline",
			"prompt":      "consent",
		},
	},
	# xAI Grok — SAME authorization_code + PKCE paste-back flow as codex. The
	# only deltas: a distinct loopback redirect_uri (xAI's server validates it
	# as an exact string, so mirror cli-proxy-api's default) and a fresh per-
	# request `nonce` param on the authorize URL (requires_nonce). Public/PKCE
	# client, so client_secret stays empty. Pooled accounts feed cli-proxy-api's
	# `xai` channel; there is no distinct pool_scope (one scope constant).
	"xAI Grok": {
		"authorize":   "https://auth.x.ai/oauth2/authorize",
		"token":       "https://auth.x.ai/oauth2/token",
		"userinfo":    "https://auth.x.ai/oauth2/userinfo",
		"scope":       "openid profile email offline_access grok-cli:access api:access",
		"openclaw_provider": "xai",
		"redirect_uri": "http://127.0.0.1:56121/callback",
		"requires_nonce": True,
		"extra_authorize_params": {"plan": "generic", "referrer": "cli-proxy-api"},
	},
	# Kimi (Moonshot) — DEVICE-CODE flow (RFC 8628), NOT paste-back: there is no
	# authorize URL / redirect / code to paste. begin_pool_account_signin routes
	# grant_type=="device_code" providers to _begin_device_signin; the frontend
	# shows user_code + verification_uri and polls poll_pool_account_signin.
	# Public device client (no secret, no PKCE). Custom X-Msh-* headers required.
	"Kimi (Moonshot)": {
		"grant_type":    "device_code",
		"device_authorization": "https://auth.kimi.com/api/oauth/device_authorization",
		"token":         "https://auth.kimi.com/api/oauth/token",
		"openclaw_provider": "kimi",
		"device_headers": {"X-Msh-Platform": "cli-proxy-api", "X-Msh-Version": "1.0.0"},
		"poll_interval_s": 5,
	},
}


def is_oauth_provider(label: str) -> bool:
	"""True when ``label`` is a PASTE-BACK (authorization_code) OAuth provider —
	exactly the providers ``begin_paste_signin`` can mint an authorize URL for.

	Device-code providers (Kimi) are deliberately EXCLUDED: they are in
	``_PROVIDER_OAUTH_MAP`` but have no authorize URL, so ``build_authorize_url``
	would KeyError on ``p["authorize"]``. Callers use this to gate the DIRECT
	"Re-authorize" affordance for a stored ``llm_provider`` (e.g. skip it for a
	non-OAuth default like ``Anthropic`` left behind by ``reset_onboarding``, and
	for a device-code provider that can only be captured via the pool flow).
	"""
	entry = _PROVIDER_OAUTH_MAP.get(label)
	return entry is not None and entry.get("grant_type") != "device_code"


def get_provider(label: str) -> dict:
	"""Look up provider metadata, including the lazy-resolved client_id +
	client_secret. ``client_secret`` is an empty string for PKCE-only
	providers (OpenAI codex); for confidential-client providers (Google
	Gemini) the resolver falls back to the bundled gemini-cli package when
	no env override is set."""
	if label not in _PROVIDER_OAUTH_MAP:
		raise UnknownProviderError(f"OAuth not supported for provider {label!r}")
	entry = dict(_PROVIDER_OAUTH_MAP[label])
	entry["client_id"] = OAUTH_CLIENT_IDS[label]
	entry["client_secret"] = get_oauth_client_secret(label)
	return entry


def extract_account_id(provider: str, access_token: str) -> str:
	"""Pull openclaw's `accountId` claim out of the access JWT.

	openclaw's codex auth resolver gates on this field: profiles without
	an accountId are treated as unusable and chat fails with "No API key
	found for provider openai". See openclaw/docs/concepts/oauth.md step
	6 of the codex OAuth exchange.

	OpenAI codex: ``payload["https://api.openai.com/auth"]["chatgpt_account_id"]``.
	Gemini: claim shape not yet verified against a real Gemini Advanced
	account; returns ``""`` until that lands (per the live-verification
	caveat in oauth-implementation.md).

	Best-effort: returns ``""`` on any parse / claim-lookup failure,
	mirroring ``_fetch_account_email``'s never-raise contract.
	"""
	if provider != "OpenAI":
		return ""
	if not access_token or access_token.count(".") < 2:
		return ""
	try:
		_, payload_b64, _ = access_token.split(".", 2)
		padded = payload_b64 + "=" * (-len(payload_b64) % 4)
		claims = json.loads(base64.urlsafe_b64decode(padded))
	except (ValueError, TypeError):
		return ""
	if not isinstance(claims, dict):
		return ""
	namespace = claims.get("https://api.openai.com/auth")
	if not isinstance(namespace, dict):
		return ""
	value = namespace.get("chatgpt_account_id")
	return value if isinstance(value, str) else ""


def build_authorize_url(*, provider: str, redirect_uri: str,
                         code_challenge: str, state: str,
                         pool: bool = False, oidc_nonce: str = "") -> str:
	"""Construct the /oauth/authorize URL with all required parameters.

	``pool=True`` selects the provider's ``pool_scope`` when it defines one
	(subscription-pool accounts consumed by cli-proxy-api need a different
	token audience than the direct openclaw flow - see the OpenAI entry).

	``oidc_nonce`` is added to the authorize params only for providers that set
	``requires_nonce`` (xAI's authorize endpoint 400s without a fresh nonce, the
	same way ``state`` is minted per request). Ignored for providers that don't.
	``redirect_uri`` is the effective per-provider redirect the caller resolved.
	"""
	p = get_provider(provider)
	params = {
		"response_type": "code",
		"client_id": p["client_id"],
		"redirect_uri": redirect_uri,
		"scope": (p.get("pool_scope") or p["scope"]) if pool else p["scope"],
		"code_challenge": code_challenge,
		"code_challenge_method": "S256",
		"state": state,
	}
	if p.get("requires_nonce") and oidc_nonce:
		params["nonce"] = oidc_nonce
	params.update(p["extra_authorize_params"])
	return f"{p['authorize']}?{urlencode(params)}"


def provider_redirect_uri(provider: str, default: str) -> str:
	"""The effective OAuth redirect_uri for ``provider``: its own value when it
	pins one (xAI mirrors cli-proxy-api's exact loopback callback), else the
	shared default. build_authorize_url and the token exchange MUST use the same
	value, so this is resolved once in _begin_signin and cached on the nonce."""
	return _PROVIDER_OAUTH_MAP.get(provider, {}).get("redirect_uri") or default
