"""Customer-side wrappers for the /jarvis-account page.

Thin shims over admin_client (so the browser never holds admin api_key /
api_secret). Errors are normalized via the shared ``_surface`` helper from
onboarding so admin ValidationErrors arrive as clean ``frappe.throw`` toasts.

The page also reuses these existing onboarding endpoints directly under
their published names - no duplicates:

  - jarvis.onboarding.save_llm_creds  (LLM section save)
  - jarvis.onboarding.renew           (renew / reactivate / resume CTAs)
  - jarvis.onboarding.finish_payment  (post-Razorpay confirm)
"""

import frappe

from jarvis import admin_client
from jarvis.onboarding import _surface


@frappe.whitelist()
def is_onboarded() -> dict:
	"""True iff Jarvis Settings holds an admin api_key. The wizard's
	completion-card branch and the account page's redirect guard share this.

	Pool-pending customers (paid but no tenant yet) still count as onboarded -
	they've completed signup; the agent_url just hasn't been wired up. The
	account page handles that state via tenant_status: pending.
	"""
	settings = frappe.get_single("Jarvis Settings")
	api_key = (settings.get_password(
		"jarvis_admin_api_key", raise_exception=False,
	) or "").strip()
	return {"onboarded": bool(api_key)}


@frappe.whitelist()
def is_ready_for_chat() -> dict:
	"""Pre-flight check used by /jarvis-chat's page load to decide whether to
	render the chat surface or redirect the customer to /jarvis-onboarding.

	Stricter than ``is_onboarded`` - signup (admin api_key) AND a usable LLM
	credential for the active ``llm_auth_mode`` must be in place. Pool-pending
	customers count as ready here (the chat surface has its own waiting state
	while the tenant is being provisioned).

	Returns ``{ready: bool, reason: str | None}`` where ``reason`` is one of:

	- ``"signup"`` - jarvis_admin_api_key is empty (customer hasn't completed
	  the wizard's signup step).
	- ``"llm_credentials"`` - signup done, but LLM creds for the active
	  auth mode are missing. api_key mode needs llm_api_key + llm_provider +
	  llm_model; subscription / oauth modes need llm_oauth_connected_at
	  (the timestamp set when the oauth grant completes).
	- ``None`` when ``ready`` is True.
	"""
	settings = frappe.get_single("Jarvis Settings")

	admin_api_key = (settings.get_password(
		"jarvis_admin_api_key", raise_exception=False,
	) or "").strip()
	if not admin_api_key:
		return {"ready": False, "reason": "signup"}

	auth_mode = (getattr(settings, "llm_auth_mode", "") or "api_key").strip()

	if auth_mode == "api_key":
		llm_key = (settings.get_password(
			"llm_api_key", raise_exception=False,
		) or "").strip()
		provider = (getattr(settings, "llm_provider", "") or "").strip()
		model = (getattr(settings, "llm_model", "") or "").strip()
		if not (llm_key and provider and model):
			return {"ready": False, "reason": "llm_credentials"}
	elif auth_mode in ("subscription", "oauth"):
		# Both modes use the same local signal: llm_oauth_connected_at is
		# set (read-only) when the oauth grant completes and the admin
		# pushes the auth-profile blob to the container.
		if not getattr(settings, "llm_oauth_connected_at", None):
			return {"ready": False, "reason": "llm_credentials"}
	else:
		# Unknown auth_mode - treat as misconfigured; the wizard owns it.
		return {"ready": False, "reason": "llm_credentials"}

	return {"ready": True, "reason": None}


@frappe.whitelist()
def get_account() -> dict:
	"""Plan + validity + upgrade-eligible plans for the account page."""
	return _surface(admin_client.get_account_summary)


@frappe.whitelist()
def preview_upgrade(target_plan: str) -> dict:
	"""Prorated amount for the upgrade modal's per-plan cards."""
	return _surface(admin_client.preview_upgrade, target_plan)


@frappe.whitelist()
def start_upgrade(target_plan: str) -> dict:
	"""Create the prorated Razorpay order; the page then opens Checkout."""
	return _surface(admin_client.start_upgrade, target_plan)
