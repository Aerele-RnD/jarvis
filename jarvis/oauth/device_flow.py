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


def poll(provider: str, device_code: str, client_id: str):
	"""Exchange ``device_code`` for tokens.

	Returns:
		- ``PENDING`` if provider says ``authorization_pending``
		- ``SLOW_DOWN`` if provider asks us to extend interval
		- ``dict`` with access_token / refresh_token / expires_in / account_email on success

	Raises:
		AccessDenied, CodeExpired, InvalidGrant: terminal failures.
		ProviderUnavailable: 5xx / network error.
	"""
	entry = get_provider(provider)
	try:
		resp = requests.post(
			entry["token_endpoint"],
			data={
				"client_id": client_id,
				"device_code": device_code,
				"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
			},
			timeout=_HTTP_TIMEOUT,
		)
	except requests.RequestException as e:
		raise ProviderUnavailable(f"network error polling {provider}: {e}") from e

	if resp.status_code >= 500:
		raise ProviderUnavailable(f"{provider} returned HTTP {resp.status_code}")

	body = resp.json()

	if resp.ok:
		access_token = body["access_token"]
		email = _fetch_userinfo_email(entry, access_token)
		return {
			"access_token": access_token,
			"refresh_token": body.get("refresh_token"),
			"expires_in": int(body.get("expires_in", 3600)),
			"account_email": email,
		}

	error_code = body.get("error", "")
	if error_code == "authorization_pending":
		return PENDING
	if error_code == "slow_down":
		return SLOW_DOWN
	exc_cls = _TERMINAL_ERRORS.get(error_code)
	if exc_cls:
		raise exc_cls(body.get("error_description") or error_code)
	raise InvalidArgumentError(f"unexpected error from {provider}: {body!r}")


def refresh(provider: str, refresh_token: str, client_id: str) -> dict:
	"""Swap a refresh token for a fresh access token.

	Returns dict with access_token, refresh_token (``None`` if not rotated),
	and expires_in.

	Raises:
		InvalidGrant: refresh token is no longer valid (revoked, expired,
			or rotated and we missed the rotation).
		ProviderUnavailable: 5xx / network error.
	"""
	entry = get_provider(provider)
	try:
		resp = requests.post(
			entry["token_endpoint"],
			data={
				"client_id": client_id,
				"grant_type": "refresh_token",
				"refresh_token": refresh_token,
			},
			timeout=_HTTP_TIMEOUT,
		)
	except requests.RequestException as e:
		raise ProviderUnavailable(f"network error refreshing {provider}: {e}") from e

	if resp.status_code >= 500:
		raise ProviderUnavailable(f"{provider} returned HTTP {resp.status_code}")

	body = resp.json()
	if not resp.ok:
		if body.get("error") == "invalid_grant":
			raise InvalidGrant(body.get("error_description") or "invalid_grant")
		raise InvalidArgumentError(f"refresh failed at {provider}: {body!r}")

	return {
		"access_token": body["access_token"],
		"refresh_token": body.get("refresh_token"),  # None if no rotation
		"expires_in": int(body.get("expires_in", 3600)),
	}


def _fetch_userinfo_email(entry: dict, access_token: str) -> str | None:
	"""Best-effort fetch of the connected account email. Never blocks the flow."""
	try:
		resp = requests.get(
			entry["userinfo_endpoint"],
			headers={"Authorization": f"Bearer {access_token}"},
			timeout=_HTTP_TIMEOUT,
		)
		if resp.ok:
			return resp.json().get("email")
	except requests.RequestException:
		pass
	return None
