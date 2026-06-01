"""REV-2 OAuth endpoints. Wizard calls these; the laptop helper POSTs
to receive_blob. No bench-side OAuth dance — the helper does it all
on the customer's machine."""
import secrets
import time

import frappe

from jarvis import admin_client, onboarding

_CACHE_KEY = "jarvis.oauth.codex_signin"
_NONCE_TTL_SECS = 600
_SHARE_LIMIT = 5
_VALID_PROVIDERS = ("OpenAI", "Google Gemini")
_PROVIDER_LABEL_TO_HELPER = {"OpenAI": "openai", "Google Gemini": "gemini"}
_PROVIDER_LABEL_TO_OPENCLAW = {
	"OpenAI": "openai-codex", "Google Gemini": "google-gemini-cli",
}
_DEFAULT_MODEL = {"OpenAI": "gpt-4o", "Google Gemini": "gemini-2.0-pro"}


def _ok(data: dict) -> dict:
	return {"ok": True, "data": data}


def _err(code: str, message: str) -> dict:
	return {"ok": False, "error": {"code": code, "message": message}}


def _bench_url() -> str:
	# frappe.utils.get_url() returns the customer-facing URL (with scheme).
	from frappe.utils import get_url
	return get_url().rstrip("/")


def _build_one_liner(*, bench_url: str, nonce: str, provider_label: str) -> str:
	helper_provider = _PROVIDER_LABEL_TO_HELPER[provider_label]
	return (
		f"curl -sSL {bench_url}/codex-login | "
		f"JARVIS_BENCH={bench_url} "
		f"JARVIS_NONCE={nonce} "
		f"JARVIS_PROVIDER={helper_provider} python3"
	)


@frappe.whitelist()
def begin_codex_signin(provider: str) -> dict:
	"""Mint a nonce and return the one-liner the wizard renders."""
	if provider not in _VALID_PROVIDERS:
		return _err("unknown_provider",
		            f"OAuth not supported for provider {provider!r}")
	nonce = secrets.token_hex(24)
	bench = _bench_url()
	frappe.cache.hset(_CACHE_KEY, nonce, {
		"provider": provider,
		"status": "pending",
		"expires_at_ts": int(time.time()) + _NONCE_TTL_SECS,
		"send_count": 0,
		"blob": None,
		"account_email": None,
	})
	return _ok({
		"nonce": nonce,
		"one_liner": _build_one_liner(
			bench_url=bench, nonce=nonce, provider_label=provider
		),
	})


_REQUIRED_BLOB_KEYS = ("type", "provider", "access", "refresh",
                       "expires", "clientId")
_VALID_OPENCLAW_PROVIDERS = set(_PROVIDER_LABEL_TO_OPENCLAW.values())


def _validate_blob(blob: dict, expected_provider_label: str) -> str | None:
	"""Return None if valid, else an error message."""
	if not isinstance(blob, dict):
		return "blob must be an object"
	for k in _REQUIRED_BLOB_KEYS:
		if k not in blob:
			return f"missing required key {k!r}"
	if blob["type"] != "oauth":
		return "type must be 'oauth'"
	if blob["provider"] not in _VALID_OPENCLAW_PROVIDERS:
		return f"unknown openclaw provider {blob['provider']!r}"
	expected_openclaw = _PROVIDER_LABEL_TO_OPENCLAW[expected_provider_label]
	if blob["provider"] != expected_openclaw:
		return (f"provider mismatch: cached {expected_openclaw!r}, "
		        f"got {blob['provider']!r}")
	from jarvis.hooks import OAUTH_CLIENT_IDS
	if blob["clientId"] not in OAUTH_CLIENT_IDS.values():
		return f"unknown clientId {blob['clientId']!r}"
	return None


@frappe.whitelist(allow_guest=True)
def receive_blob(nonce: str, blob: dict) -> dict:
	"""Called by the laptop helper. No Frappe session — auth is via nonce."""
	entry = frappe.cache.hget(_CACHE_KEY, nonce)
	if not entry:
		return _err("unknown_nonce", "nonce not recognized")
	if entry["expires_at_ts"] < int(time.time()):
		return _err("expired", "nonce has expired")
	if entry["status"] != "pending":
		return _err("not_pending", f"nonce status is {entry['status']!r}")
	err = _validate_blob(blob, entry["provider"])
	if err:
		return _err("invalid_blob", err)
	entry["status"] = "connected"
	entry["blob"] = blob
	entry["account_email"] = blob.get("email") or ""
	frappe.cache.hset(_CACHE_KEY, nonce, entry)
	return _ok({})


@frappe.whitelist()
def poll_signin(nonce: str) -> dict:
	"""Wizard polls every 2s. Returns 'pending' or 'connected'."""
	entry = frappe.cache.hget(_CACHE_KEY, nonce)
	if not entry:
		return _err("unknown_nonce", "nonce not recognized")
	if entry["expires_at_ts"] < int(time.time()):
		return _err("expired", "nonce has expired")
	data = {"status": entry["status"]}
	if entry["status"] == "connected":
		data["account_email"] = entry.get("account_email") or ""
	return _ok(data)


@frappe.whitelist()
def commit_signin(nonce: str) -> dict:
	"""Wizard calls this after `poll_signin` returns 'connected'.
	Forwards the cached blob to admin → fleet-agent and saves bench-side
	mode flags."""
	entry = frappe.cache.hget(_CACHE_KEY, nonce)
	if not entry:
		return _err("unknown_nonce", "nonce not recognized")
	if entry["status"] != "connected":
		return _err("not_connected", f"nonce status is {entry['status']!r}")
	provider_label = entry["provider"]
	blob = entry["blob"]
	openclaw_provider = _PROVIDER_LABEL_TO_OPENCLAW[provider_label]

	admin_client.post_push_oauth_blob(openclaw_provider, blob)
	onboarding.save_llm_creds(
		provider=provider_label,
		model=_DEFAULT_MODEL[provider_label],
		api_key="",
		base_url="",
		auth_mode="oauth",
	)
	frappe.cache.hdel(_CACHE_KEY, nonce)
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
	frappe.cache.delete_key(_CACHE_KEY)
	return _ok({})


@frappe.whitelist()
def share_signin(nonce: str, recipient_email: str) -> dict:
	"""Email the one-liner to a colleague. Rate-limited per nonce."""
	from jarvis.oauth.email_templates import build_share_signin_email

	entry = frappe.cache.hget(_CACHE_KEY, nonce)
	if not entry:
		return _err("unknown_nonce", "nonce not recognized")
	if entry["expires_at_ts"] < int(time.time()):
		return _err("expired", "nonce has expired")
	if entry["send_count"] >= _SHARE_LIMIT:
		return _err("rate_limited",
		            f"Already shared {_SHARE_LIMIT} times.")
	minutes_left = max(0, (entry["expires_at_ts"] - int(time.time())) // 60)
	one_liner = _build_one_liner(
		bench_url=_bench_url(), nonce=nonce,
		provider_label=entry["provider"],
	)
	sender = getattr(frappe.session, "user_fullname", None) or frappe.session.user
	email = build_share_signin_email(
		sender_name=sender,
		company=frappe.local.site,
		provider=entry["provider"],
		one_liner=one_liner,
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
