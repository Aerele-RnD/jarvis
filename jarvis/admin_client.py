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
		"Authorization": f"Bearer {token}",
		"X-Jarvis-Site": frappe.utils.get_url(),
		"Content-Type": "application/json",
	}
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
