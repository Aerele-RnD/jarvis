"""HTTPS client for the Jarvis admin (jarvis_admin) app.

Used by Jarvis Settings.on_update when the customer's bench is configured
to talk to a remote admin (jarvis_admin_url is set). 3.2.4 will grow this
module with /signup-status, /subscription, /token/regenerate calls.

When jarvis_admin_url is empty (dev / Phase 1), callers route to
openclaw_push instead and admin_client is not invoked at all.
"""

import frappe
import requests

from jarvis.exceptions import AdminAuthError, AdminUnreachableError


# Admin's provision_healthz_timeout_s defaults to 60s for restart operations;
# 90s leaves 30s buffer for network round-trip + handler overhead.
DEFAULT_TIMEOUT_S = 90

# Hardcoded prod admin URL; override via Jarvis Settings.jarvis_admin_url (dev/staging).
DEFAULT_ADMIN_URL = "https://admin.jarvis.aerele.in"


def _admin_url(settings) -> str:
	return ((settings.jarvis_admin_url or "").rstrip("/")) or DEFAULT_ADMIN_URL


def signup(email: str, company_name: str, plan: str, coupon: str | None = None) -> dict:
	"""Guest signup against admin. Returns admin's data dict
	{api_token, razorpay_key_id, razorpay_order_id, amount_inr}. Both annual and
	monthly are one-shot orders (manual renew — no Razorpay subscription)."""
	settings = frappe.get_single("Jarvis Settings")
	body = {"email": email, "company_name": company_name, "plan": plan,
			"frappe_site_url": frappe.utils.get_url()}
	if coupon:
		body["coupon"] = coupon
	return _post(path="/api/method/jarvis_admin.billing.signup.signup",
				 body=body, admin_url=_admin_url(settings), token="")


def dev_signup(email: str, company_name: str, plan: str) -> dict:
	"""Razorpay-free dev signup. Returns admin's flat dict incl. api_token + connection."""
	settings = frappe.get_single("Jarvis Settings")
	return _post(path="/api/method/jarvis_admin.billing.signup.dev_force_signup",
				 body={"email": email, "company_name": company_name, "plan": plan,
					   "frappe_site_url": frappe.utils.get_url()},
				 admin_url=_admin_url(settings), token="")


def get_plans() -> list:
	settings = frappe.get_single("Jarvis Settings")
	return _post(path="/api/method/jarvis_admin.billing.signup.get_plans",
				 body={}, admin_url=_admin_url(settings), token="")


def confirm_payment(payload: dict) -> dict:
	"""POST Razorpay Checkout result; returns {agent_url, agent_token, tenant_status}."""
	settings = frappe.get_single("Jarvis Settings")
	token = settings.get_password("jarvis_admin_api_key", raise_exception=False) or ""
	return _post(path="/api/method/jarvis_admin.api.tenant.confirm_payment",
				 body=payload, admin_url=_admin_url(settings), token=token)


def get_connection() -> dict:
	"""Fetch the assigned container connection (fallback / scheduled sync)."""
	settings = frappe.get_single("Jarvis Settings")
	token = settings.get_password("jarvis_admin_api_key", raise_exception=False) or ""
	return _post(path="/api/method/jarvis_admin.api.tenant.get_connection",
				 body={}, admin_url=_admin_url(settings), token=token)


def renew() -> dict:
	"""Existing customer pays again to extend (manual one-shot). Returns admin's
	data dict {razorpay_order_id, razorpay_key_id, amount_inr} for Checkout."""
	settings = frappe.get_single("Jarvis Settings")
	token = settings.get_password("jarvis_admin_api_key", raise_exception=False) or ""
	return _post(path="/api/method/jarvis_admin.api.tenant.renew",
				 body={}, admin_url=_admin_url(settings), token=token)


def post_update_llm_creds(
	provider: str, model: str, base_url: str, api_key: str,
) -> dict:
	"""POST customer's new LLM creds to admin's /tenant/update-llm-creds.

	Returns admin's unwrapped data envelope on success, e.g.
	  {"action": "reload", "result": "ok"}
	Raises:
	  AdminAuthError      — 401/403 from admin
	  AdminUnreachableError — network error, 5xx, ok:false envelope,
	                          non-JSON response, or missing local config.
	"""
	settings = frappe.get_single("Jarvis Settings")
	admin_url = (settings.jarvis_admin_url or "").rstrip("/")
	token = settings.get_password("jarvis_admin_api_key", raise_exception=False) or ""
	if not admin_url or not token:
		raise AdminUnreachableError(
			"jarvis_admin_url or jarvis_admin_api_key not configured"
		)
	return _post(
		path="/api/method/jarvis_admin.api.tenant.update_llm_creds",
		body={
			"provider": provider, "model": model,
			"base_url": base_url, "api_key": api_key,
		},
		admin_url=admin_url,
		token=token,
	)


def _post(path: str, body: dict, admin_url: str, token: str,
		  timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
	headers = {
		"X-Jarvis-Site": frappe.utils.get_url(),
		"Content-Type": "application/json",
	}
	# Guest endpoints (get_plans, signup) pass an empty token — send NO
	# Authorization header then, since Frappe rejects an empty "Bearer " with 401
	# before the allow_guest method runs.
	if token:
		headers["Authorization"] = f"Bearer {token}"
	try:
		resp = requests.post(
			admin_url + path, json=body, headers=headers, timeout=timeout_s,
		)
	except (requests.ConnectionError, requests.Timeout) as e:
		raise AdminUnreachableError(f"admin {admin_url}: {e}") from e

	try:
		payload = resp.json()
	except ValueError:
		raise AdminUnreachableError(
			f"admin {admin_url} returned non-JSON (status {resp.status_code})"
		)

	# Frappe wraps whitelisted method returns as {"message": <returned dict>}
	envelope = payload.get("message", payload) if isinstance(payload, dict) else payload

	if resp.status_code in (401, 403):
		err = (envelope or {}).get("error", {}) if isinstance(envelope, dict) else {}
		raise AdminAuthError(err.get("message") or f"admin returned {resp.status_code}")
	if resp.status_code >= 400 or (isinstance(envelope, dict) and not envelope.get("ok", True)):
		err = (envelope or {}).get("error", {}) if isinstance(envelope, dict) else {}
		raise AdminUnreachableError(
			f"admin {admin_url} returned error: "
			f"{err.get('code', '?')}: {err.get('message', resp.text[:200])}"
		)
	return envelope.get("data", envelope) if isinstance(envelope, dict) else envelope
