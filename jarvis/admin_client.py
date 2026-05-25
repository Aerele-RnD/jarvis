"""HTTPS client for the Jarvis admin (jarvis_admin) app.

Authenticated calls use Frappe's native api_key:api_secret. The customer's
bench reads both from Jarvis Settings (set at signup) and sends them as
`Authorization: token <api_key>:<api_secret>`.

Guest calls (signup, get_plans) skip the header entirely; their admin
endpoints are @frappe.whitelist(allow_guest=True).
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
	{api_key, api_secret, razorpay_key_id, razorpay_order_id, amount_inr}.
	Both annual and monthly are one-shot orders (manual renew — no Razorpay subscription)."""
	settings = frappe.get_single("Jarvis Settings")
	body = {"email": email, "company_name": company_name, "plan": plan,
			"frappe_site_url": frappe.utils.get_url()}
	if coupon:
		body["coupon"] = coupon
	return _post_guest(path="/api/method/jarvis_admin.billing.signup.signup",
					   body=body, admin_url=_admin_url(settings))


def dev_signup(email: str, company_name: str, plan: str) -> dict:
	"""Razorpay-free dev signup. Returns admin's flat dict incl. api_key + api_secret + connection."""
	settings = frappe.get_single("Jarvis Settings")
	return _post_guest(path="/api/method/jarvis_admin.billing.signup.dev_force_signup",
					   body={"email": email, "company_name": company_name, "plan": plan,
							 "frappe_site_url": frappe.utils.get_url()},
					   admin_url=_admin_url(settings))


def get_plans() -> list:
	settings = frappe.get_single("Jarvis Settings")
	return _post_guest(path="/api/method/jarvis_admin.billing.signup.get_plans",
					   body={}, admin_url=_admin_url(settings))


def confirm_payment(payload: dict) -> dict:
	"""POST Razorpay Checkout result; returns {agent_url, agent_token, tenant_status}."""
	settings = frappe.get_single("Jarvis Settings")
	return _post(path="/api/method/jarvis_admin.api.tenant.confirm_payment",
				 body=payload, admin_url=_admin_url(settings))


def get_connection() -> dict:
	"""Fetch the assigned container connection (fallback / scheduled sync)."""
	settings = frappe.get_single("Jarvis Settings")
	return _post(path="/api/method/jarvis_admin.api.tenant.get_connection",
				 body={}, admin_url=_admin_url(settings))


def renew() -> dict:
	"""Existing customer pays again to extend (manual one-shot). Returns admin's
	data dict {razorpay_order_id, razorpay_key_id, amount_inr} for Checkout."""
	settings = frappe.get_single("Jarvis Settings")
	return _post(path="/api/method/jarvis_admin.api.tenant.renew",
				 body={}, admin_url=_admin_url(settings))


def post_update_llm_creds(
	provider: str, model: str, base_url: str, api_key: str,
) -> dict:
	"""POST customer's new LLM creds to admin's /tenant/update-llm-creds."""
	settings = frappe.get_single("Jarvis Settings")
	return _post(
		path="/api/method/jarvis_admin.api.tenant.update_llm_creds",
		body={
			"provider": provider, "model": model,
			"base_url": base_url, "api_key": api_key,
		},
		admin_url=_admin_url(settings),
	)


def _post(path: str, body: dict, admin_url: str,
		  timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
	"""Authenticated POST. Reads native api_key + api_secret from Jarvis
	Settings. Raises AdminAuthError early if either is empty."""
	settings = frappe.get_single("Jarvis Settings")
	# Both are Password fields — attribute access would return the masked
	# "*****" placeholder Frappe stores in the row. get_password decrypts
	# the real value out of __Auth.
	api_key = (settings.get_password(
		"jarvis_admin_api_key", raise_exception=False
	) or "").strip()
	api_secret = settings.get_password(
		"jarvis_admin_api_secret", raise_exception=False
	) or ""
	if not api_key or not api_secret:
		raise AdminAuthError(
			"not onboarded (Jarvis Settings: admin api_key + api_secret empty)"
		)
	headers = {
		"Authorization": f"token {api_key}:{api_secret}",
		"Content-Type": "application/json",
	}
	return _do_post(admin_url + path, body, headers, timeout_s, admin_url)


def _post_guest(path: str, body: dict, admin_url: str,
				timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
	"""Unauthenticated POST (signup, get_plans). No Authorization header."""
	headers = {"Content-Type": "application/json"}
	return _do_post(admin_url + path, body, headers, timeout_s, admin_url)


def _do_post(url: str, body: dict, headers: dict, timeout_s: int, admin_url: str) -> dict:
	try:
		resp = requests.post(url, json=body, headers=headers, timeout=timeout_s)
	except (requests.ConnectionError, requests.Timeout) as e:
		raise AdminUnreachableError(f"admin {admin_url}: {e}") from e

	try:
		payload = resp.json()
	except ValueError:
		raise AdminUnreachableError(
			f"admin {admin_url} returned non-JSON (status {resp.status_code})"
		)

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
