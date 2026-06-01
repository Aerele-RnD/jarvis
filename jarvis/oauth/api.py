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
