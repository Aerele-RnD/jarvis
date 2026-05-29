"""Onboarding — store the admin token + container connection into Jarvis
Settings, and thin server wrappers the onboarding page calls (so the browser
never holds admin creds). admin_client returns already-unwrapped admin data."""

import json

import frappe

from jarvis import admin_client
from jarvis.exceptions import AdminValidationError


def _surface(fn, *args, **kwargs):
	"""Run an admin_client call; re-raise admin validation errors as
	frappe.ValidationError so the onboarding page gets a clean operator-facing
	message (and Frappe's standard red toast) instead of a long traceback dump
	from AdminUnreachableError."""
	try:
		return fn(*args, **kwargs)
	except AdminValidationError as e:
		frappe.throw(str(e))


def write_connection(data: dict) -> None:
	"""Persist native admin credentials + container connection into Jarvis
	Settings via db_set (no on_update creds-push retrigger during onboarding)."""
	if not isinstance(data, dict):
		return
	s = frappe.get_single("Jarvis Settings")
	if data.get("api_key"):
		s.db_set("jarvis_admin_api_key", data["api_key"])
	if data.get("api_secret"):
		s.db_set("jarvis_admin_api_secret", data["api_secret"])
	if data.get("agent_url"):
		s.db_set("agent_url", data["agent_url"])
	if data.get("agent_token"):
		s.db_set("agent_token", data["agent_token"])


@frappe.whitelist()
def sync_connection() -> dict:
	"""Pull the container connection from admin and store it. Daily scheduled +
	the page's 'Sync connection' button. No-op until onboarded/assigned."""
	settings = frappe.get_single("Jarvis Settings")
	api_key = settings.get_password("jarvis_admin_api_key", raise_exception=False) or ""
	api_secret = settings.get_password("jarvis_admin_api_secret", raise_exception=False) or ""
	if not (api_key and api_secret):
		return {"synced": False, "reason": "not onboarded"}
	data = admin_client.get_connection()
	if data.get("agent_url"):
		write_connection(data)
		return {"synced": True, "tenant_status": data.get("tenant_status")}
	return {"synced": False, "tenant_status": data.get("tenant_status", "pending")}


@frappe.whitelist()
def list_plans() -> list:
	return admin_client.get_plans()


@frappe.whitelist()
def start_signup(email: str, company: str, plan: str) -> dict:
	"""Guest signup → store the api_token → return the Razorpay handles for Checkout."""
	data = _surface(admin_client.signup, email, company, plan)
	if data.get("api_token"):
		write_connection({"api_token": data["api_token"]})
	return data


@frappe.whitelist()
def finish_payment(payload) -> dict:
	"""Confirm Checkout success → store the returned container connection."""
	if isinstance(payload, str):
		payload = json.loads(payload)
	data = _surface(admin_client.confirm_payment, payload)
	write_connection(data)
	return data


@frappe.whitelist()
def renew() -> dict:
	"""Existing customer initiates a renewal payment; returns the Razorpay handles
	for Checkout. The page then completes Checkout and calls finish_payment."""
	return _surface(admin_client.renew)


@frappe.whitelist()
def save_llm_creds(provider: str, model: str, api_key: str = "",
                   base_url: str = "", auth_mode: str = "api_key") -> dict:
	"""Save LLM provider/model/auth mode + (api_key when applicable) and let
	on_update re-render openclaw.json. Returns the on_update outcome
	(last_sync_status) so the page can tell the customer whether their
	agent is fully ready.

	REV-1: ``auth_mode="oauth"`` lets the OAuth poll-success path save
	without requiring an api_key — credentials live in the container's
	auth-profiles.json (pushed via the separate push_oauth_blob path)."""
	if not provider or not model:
		raise frappe.ValidationError("provider and model are required")
	if auth_mode not in {"api_key", "oauth"}:
		raise frappe.ValidationError(f"unsupported auth_mode: {auth_mode}")
	if auth_mode == "api_key" and not api_key:
		raise frappe.ValidationError("api_key is required when auth_mode=api_key")
	s = frappe.get_single("Jarvis Settings")
	s.llm_provider = provider
	s.llm_model = model
	s.llm_auth_mode = auth_mode
	s.llm_base_url = (base_url or "").strip()
	if auth_mode == "api_key":
		s.llm_api_key = api_key
	s.save(ignore_permissions=True)
	frappe.db.commit()
	s = frappe.get_single("Jarvis Settings")
	return {
		"last_sync_at": str(s.get("last_sync_at") or ""),
		"last_sync_status": s.get("last_sync_status") or "",
	}


@frappe.whitelist()
def dev_onboard(email: str, company: str, plan: str) -> dict:
	"""Local Razorpay-free onboarding: dev_force_signup → store token+connection.

	Single-bench dev shortcut: if jarvis_admin_url isn't already set, default
	it to this site's URL (customer site == admin site in local dev). Without
	this, admin_client._admin_url falls back to the hardcoded prod URL and the
	call DNS-fails immediately."""
	settings = frappe.get_single("Jarvis Settings")
	if not (settings.jarvis_admin_url or "").strip():
		settings.db_set("jarvis_admin_url", frappe.utils.get_url())
	data = _surface(admin_client.dev_signup, email, company, plan)
	write_connection(data)
	return data
