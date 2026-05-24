"""Operator-facing diagnostics for the Jarvis Settings page.

Three whitelisted endpoints exposed as buttons:

- ping_admin: hits an authenticated admin endpoint to verify the
  customer's jarvis_admin_api_key works against jarvis_admin_url.
- ping_openclaw: opens a WS to agent_url with agent_token and completes
  the connect handshake only. No restart, no reload.
- force_resync: re-runs the same sync path as Jarvis Settings.on_update
  without depending on its change-detection. Useful when an LLM key
  change didn't register as a change (Password field UX bites).

All three return {ok: bool, ...} envelopes; the JS button shows a
green / red toast based on `ok`.
"""

import frappe


@frappe.whitelist()
def ping_admin() -> dict:
	"""Hit the admin's get_connection endpoint with the customer's stored
	jarvis_admin_api_key. Distinguishes auth failure from unreachable."""
	from jarvis import admin_client
	settings = frappe.get_single("Jarvis Settings")
	if not (settings.get_password("jarvis_admin_api_key", raise_exception=False) or "").strip():
		return {
			"ok": False, "kind": "config",
			"error": "jarvis_admin_api_key is not set; complete onboarding first.",
		}
	try:
		result = admin_client.get_connection()
		return {
			"ok": True,
			"admin_url": admin_client._admin_url(settings),
			"connection": result,
		}
	except admin_client.AdminAuthError as e:
		return {"ok": False, "kind": "auth", "error": str(e)}
	except admin_client.AdminUnreachableError as e:
		return {"ok": False, "kind": "unreachable", "error": str(e)}


@frappe.whitelist()
def ping_openclaw() -> dict:
	"""Open WS to agent_url with agent_token; connect handshake only."""
	from jarvis import openclaw_push
	from jarvis.exceptions import OpenclawUnreachableError
	settings = frappe.get_single("Jarvis Settings")
	url = (settings.agent_url or "").strip()
	token = settings.get_password("agent_token", raise_exception=False) or ""
	if not url:
		return {"ok": False, "kind": "config", "error": "agent_url is not set."}
	if not token:
		return {"ok": False, "kind": "config", "error": "agent_token is not set."}
	try:
		openclaw_push.ping(url, token)
		return {"ok": True, "agent_url": url}
	except OpenclawUnreachableError as e:
		return {"ok": False, "kind": "unreachable", "error": str(e)}
	except Exception as e:
		return {"ok": False, "kind": "error", "error": f"{type(e).__name__}: {e}"}


@frappe.whitelist()
def force_resync(action: str = "reload") -> dict:
	"""Bypass on_update change-detection. Run the same sync path on
	current Settings values. action in {'reload', 'restart'}."""
	if action not in ("reload", "restart"):
		raise frappe.ValidationError(f"invalid action {action!r}; expected reload or restart")
	settings = frappe.get_single("Jarvis Settings")
	if (settings.get_password("jarvis_admin_api_key", raise_exception=False) or "").strip():
		settings._sync_via_admin(action)
	else:
		settings._sync_via_local_openclaw(action)
	settings.reload()
	return {
		"action": action,
		"last_sync_at": str(settings.get("last_sync_at") or ""),
		"last_sync_status": settings.get("last_sync_status") or "",
	}
