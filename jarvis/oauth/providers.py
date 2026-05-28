"""Per-provider OAuth device-flow metadata.

Each entry describes how to drive RFC 8628 device flow against one provider
plus the openclaw ``auth_mode`` string to ship in the rendered config so the
container plugin routes to the right endpoint.

Anthropic Claude is deliberately absent — openclaw has no compatible
adapter for Claude Pro/Max subscriptions.
"""
from jarvis.exceptions import InvalidArgumentError

REQUIRED_KEYS = (
	"device_code_endpoint",
	"token_endpoint",
	"userinfo_endpoint",
	"revocation_endpoint",
	"scope",
	"openclaw_auth_mode",
)

PROVIDER_OAUTH_MAP: dict[str, dict[str, str]] = {
	"OpenAI": {
		"device_code_endpoint": "https://auth.openai.com/oauth/device/code",
		"token_endpoint": "https://auth.openai.com/oauth/token",
		"userinfo_endpoint": "https://api.openai.com/v1/userinfo",
		"revocation_endpoint": "https://auth.openai.com/oauth/revoke",
		"scope": "openid email profile offline_access",
		"openclaw_auth_mode": "subscription",
	},
	"Google Gemini": {
		"device_code_endpoint": "https://oauth2.googleapis.com/device/code",
		"token_endpoint": "https://oauth2.googleapis.com/token",
		"userinfo_endpoint": "https://openidconnect.googleapis.com/v1/userinfo",
		"revocation_endpoint": "https://oauth2.googleapis.com/revoke",
		"scope": "openid email profile https://www.googleapis.com/auth/generative-language",
		"openclaw_auth_mode": "subscription",
	},
}


def get_provider(label: str) -> dict[str, str]:
	if label not in PROVIDER_OAUTH_MAP:
		raise InvalidArgumentError(
			f"OAuth not supported for provider {label!r} "
			f"(supported: {sorted(PROVIDER_OAUTH_MAP)})"
		)
	return PROVIDER_OAUTH_MAP[label]
