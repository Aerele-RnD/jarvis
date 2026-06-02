"""Per-provider OAuth metadata + authorize URL builder.

Used by jarvis.oauth.api to drive the paste-back OAuth flow against
the provider's own /oauth/authorize endpoint, with the codex-CLI-specific
parameter set that auth.openai.com requires for codex's client_id.
"""
from urllib.parse import urlencode

from jarvis.exceptions import JarvisError
from jarvis.hooks import OAUTH_CLIENT_IDS


class UnknownProviderError(JarvisError):
	"""Provider label not in PROVIDER_OAUTH_MAP."""


_PROVIDER_OAUTH_MAP: dict[str, dict] = {
	"OpenAI": {
		"authorize": "https://auth.openai.com/oauth/authorize",
		"token":     "https://auth.openai.com/oauth/token",
		"userinfo":  "https://api.openai.com/v1/userinfo",
		"scope":     "openid profile email offline_access api.connectors.read api.connectors.invoke",
		"openclaw_provider": "openai-codex",
		# codex-cli-specific authorize params — auth.openai.com returns a
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
		# Gemini's id_token carries the email claim — no separate userinfo.
		"userinfo":  None,
		"scope":     "openid email profile https://www.googleapis.com/auth/generative-language",
		"openclaw_provider": "google-gemini-cli",
		"extra_authorize_params": {
			"access_type": "offline",
			"prompt":      "consent",
		},
	},
}


def get_provider(label: str) -> dict:
	"""Look up provider metadata, including the lazy-resolved client_id."""
	if label not in _PROVIDER_OAUTH_MAP:
		raise UnknownProviderError(f"OAuth not supported for provider {label!r}")
	entry = dict(_PROVIDER_OAUTH_MAP[label])
	entry["client_id"] = OAUTH_CLIENT_IDS[label]
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
