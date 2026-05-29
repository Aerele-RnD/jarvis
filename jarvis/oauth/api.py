"""Whitelisted endpoints called by the onboarding wizard."""
import time
from datetime import datetime, timedelta

import frappe

from jarvis import admin_client, onboarding
from jarvis.exceptions import JarvisError
from jarvis.hooks import get_oauth_client_id
from jarvis.oauth import device_flow
from jarvis.oauth.email_templates import build_share_code_email

_CACHE_KEY = "jarvis.oauth.device_codes"
_SHARE_LIMIT = 5


def _ok(data: dict) -> dict:
	return {"ok": True, "data": data}


def _err(code: str, message: str) -> dict:
	return {"ok": False, "error": {"code": code, "message": message}}


@frappe.whitelist()
def start_signin(provider: str) -> dict:
	"""Begin OAuth device flow. Caches device_code so poll_signin can find it."""
	try:
		client_id = get_oauth_client_id(provider)
		envelope = device_flow.start(provider, client_id=client_id)
	except Exception as e:
		return _err("start_failed", str(e))

	frappe.cache.hset(_CACHE_KEY, envelope["device_code"], {
		"provider": provider,
		"user_code": envelope["user_code"],
		"verification_uri": envelope["verification_uri"],
		"expires_at_ts": int(time.time()) + envelope["expires_in"],
		"send_count": 0,
	})
	return _ok(envelope)


@frappe.whitelist()
def poll_signin(device_code: str) -> dict:
	"""Poll once. Wizard calls this every ``interval`` seconds."""
	cached = frappe.cache.hget(_CACHE_KEY, device_code)
	if not cached:
		return _err("unknown_device_code", "Device code not recognized or expired.")
	provider = cached["provider"]
	try:
		client_id = get_oauth_client_id(provider)
		result = device_flow.poll(provider, device_code=device_code, client_id=client_id)
	except device_flow.AccessDenied:
		frappe.cache.hdel(_CACHE_KEY, device_code)
		return _err("access_denied", "Sign-in was cancelled.")
	except device_flow.CodeExpired:
		frappe.cache.hdel(_CACHE_KEY, device_code)
		return _err("code_expired", "The code expired. Generate a new one.")
	except JarvisError as e:
		return _err("poll_failed", str(e))

	if result is device_flow.PENDING:
		return _ok({"status": "pending"})
	if result is device_flow.SLOW_DOWN:
		return _ok({"status": "pending", "slow_down": True})

	# Connected — write to Jarvis Settings, kick on_update
	_persist_subscription(provider, result)
	frappe.cache.hdel(_CACHE_KEY, device_code)
	return _ok({
		"status": "connected",
		"account_email": result.get("account_email"),
	})


@frappe.whitelist()
def disconnect() -> dict:
	"""Clear OAuth credentials. Mode stays 'subscription' until user re-saves."""
	from frappe.utils.password import remove_encrypted_password

	settings = frappe.get_single("Jarvis Settings")

	# Best-effort revocation at provider — silently swallow failures.
	try:
		_best_effort_revoke(settings)
	except Exception:
		pass

	for f in ("llm_oauth_refresh_token", "llm_oauth_access_token"):
		remove_encrypted_password("Jarvis Settings", "Jarvis Settings", f)
		settings.db_set(f, None, update_modified=False)
	for f in ("llm_oauth_access_token_expires_at", "llm_oauth_account_email",
	          "llm_oauth_connected_at", "llm_oauth_last_refresh_at"):
		settings.db_set(f, None, update_modified=False)
	# Trigger openclaw re-render (will use STUB_DEFAULTS since creds gone).
	settings.run_method("on_update")
	return _ok({})


@frappe.whitelist()
def share_code(device_code: str, recipient_email: str) -> dict:
	"""Send the code + URL to a colleague via email. Rate-limited."""
	cached = frappe.cache.hget(_CACHE_KEY, device_code)
	if not cached:
		return _err("unknown_device_code", "Device code expired.")
	if cached["send_count"] >= _SHARE_LIMIT:
		return _err("rate_limited", f"Code already shared {_SHARE_LIMIT} times.")

	minutes_left = max(0, (cached["expires_at_ts"] - int(time.time())) // 60)
	email = build_share_code_email(
		site=frappe.local.site,
		provider=cached["provider"],
		verification_uri=cached["verification_uri"],
		user_code=cached["user_code"],
		minutes_left=minutes_left,
		sender_name=frappe.session.user_fullname or frappe.session.user,
	)
	frappe.sendmail(
		recipients=[recipient_email],
		subject=email["subject"],
		message=email["body"],
		now=True,
	)
	cached["send_count"] += 1
	frappe.cache.hset(_CACHE_KEY, device_code, cached)
	return _ok({})


# Provider label → openclaw provider id for subscription mode. Matches the
# admin-side OAUTH_PROVIDER_MAP in jarvis_admin.fleet.llm_providers.
_PROVIDER_LABEL_TO_ID = {
	"OpenAI": "openai-codex",
	"Google Gemini": "google-gemini-cli",
}

# Default model per subscription provider. Customers can change the model
# later via the AI provider card if they want a different default.
_DEFAULT_MODEL = {
	"OpenAI": "gpt-4o",
	"Google Gemini": "gemini-2.0-pro",
}


def _persist_subscription(provider: str, tokens: dict):
	"""Push the OAuth credential blob into the customer's container via
	admin, then save the auth_mode/provider on bench so on_update reshapes
	the openclaw config to Branch B (oauth) + restarts the container.

	openclaw owns refresh from here on (pi-ai uses the same client_id we
	issued the refresh token against), so the bench doesn't keep any OAuth
	state beyond provider + auth_mode.
	"""
	provider_id = _PROVIDER_LABEL_TO_ID.get(provider)
	if not provider_id:
		raise JarvisError(f"no openclaw subscription provider for {provider!r}")

	now_ms = int(time.time() * 1000)
	expires_ms = now_ms + int(tokens["expires_in"]) * 1000
	blob = {
		"type": "oauth",
		"provider": provider_id,
		"access": tokens["access_token"],
		"refresh": tokens.get("refresh_token") or "",
		"expires": expires_ms,
		"email": tokens.get("account_email") or "",
		"clientId": get_oauth_client_id(provider),
	}

	admin_client.post_push_oauth_blob(provider_id, blob)

	onboarding.save_llm_creds(
		provider=provider,
		model=_DEFAULT_MODEL.get(provider, ""),
		api_key="",
		base_url="",
		auth_mode="oauth",
	)


def _best_effort_revoke(settings):
	"""POST to provider revocation endpoint. Failures ignored."""
	import requests

	from jarvis.oauth.providers import get_provider

	provider = settings.llm_provider
	token = settings.get_password("llm_oauth_refresh_token", raise_exception=False)
	if not provider or not token:
		return
	try:
		entry = get_provider(provider)
	except JarvisError:
		return
	try:
		requests.post(
			entry["revocation_endpoint"],
			data={"token": token, "client_id": get_oauth_client_id(provider)},
			timeout=10,
		)
	except Exception:
		pass
