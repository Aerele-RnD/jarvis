"""RFC 8628 device-flow plumbing — provider-agnostic.

All three calls (start, poll, refresh) read endpoint URLs and scope from
:mod:`jarvis.oauth.providers`. The HTTP wire format is the same across
providers that follow the RFC; the bits that differ are URLs + scope.
"""
import requests

from jarvis.exceptions import InvalidArgumentError, JarvisError
from jarvis.oauth.providers import get_provider

_HTTP_TIMEOUT = 15


class ProviderUnavailable(JarvisError):
	"""Provider's OAuth endpoint returned 5xx or was unreachable."""


class AccessDenied(JarvisError):
	"""User denied authorization at the provider."""


class CodeExpired(JarvisError):
	"""Device code expired before user authorized."""


class InvalidGrant(JarvisError):
	"""Refresh/device token rejected — typically revoked or rotated."""


PENDING = object()    # sentinel: keep polling
SLOW_DOWN = object()  # sentinel: keep polling, extend interval per RFC 8628


_TERMINAL_ERRORS = {
	"access_denied": AccessDenied,
	"expired_token": CodeExpired,
	"invalid_grant": InvalidGrant,
}


def start(provider: str, client_id: str) -> dict:
	"""Begin a device flow. Returns the envelope from the provider.

	Raises:
		InvalidArgumentError: ``provider`` not in PROVIDER_OAUTH_MAP.
		ProviderUnavailable: 5xx or network error.
	"""
	entry = get_provider(provider)
	try:
		resp = requests.post(
			entry["device_code_endpoint"],
			data={"client_id": client_id, "scope": entry["scope"]},
			timeout=_HTTP_TIMEOUT,
		)
	except requests.RequestException as e:
		raise ProviderUnavailable(f"network error contacting {provider}: {e}") from e
	if resp.status_code >= 500:
		raise ProviderUnavailable(f"{provider} returned HTTP {resp.status_code}")
	if not resp.ok:
		raise InvalidArgumentError(
			f"{provider} rejected device-code request: HTTP {resp.status_code}"
		)
	body = resp.json()
	return {
		"device_code": body["device_code"],
		"user_code": body["user_code"],
		"verification_uri": body["verification_uri"],
		"interval": int(body.get("interval", 5)),
		"expires_in": int(body.get("expires_in", 600)),
	}
