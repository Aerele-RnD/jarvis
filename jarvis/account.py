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
