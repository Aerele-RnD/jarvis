"""Per-provider OAuth metadata + authorize URL builder.

Used by jarvis.oauth.api to drive the paste-back OAuth flow against
the provider's own /oauth/authorize endpoint, with the codex-CLI-specific
parameter set that auth.openai.com requires for codex's client_id.
"""
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
}


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


def build_authorize_url(*, provider: str, redirect_uri: str,
                         code_challenge: str, state: str) -> str:
	"""Construct the /oauth/authorize URL with all required parameters."""
	p = get_provider(provider)
	params = {
		"response_type": "code",
		"client_id": p["client_id"],
		"redirect_uri": redirect_uri,
		"scope": p["scope"],
		"code_challenge": code_challenge,
		"code_challenge_method": "S256",
		"state": state,
	}
	params.update(p["extra_authorize_params"])
	return f"{p['authorize']}?{urlencode(params)}"
