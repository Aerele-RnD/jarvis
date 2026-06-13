"""Dev-only helpers for the customer bench.

Gated by sandbox mode (Jarvis Settings.sandbox_mode, with legacy
frappe.conf.developer_mode as a one-release backwards-compat fallback)
+ the System Manager role. Used by the Jarvis Settings form to wipe local
state so the operator can run the onboarding wizard fresh without manual
DB surgery.

Companion to ``jarvis_admin.api.dev.purge_customer`` on the admin side -
the admin button wipes admin-side records; this clears the customer bench.
"""

import frappe
from frappe.utils.password import remove_encrypted_password


SETTINGS = "Jarvis Settings"

# Password fieldtype stores the real value in __Auth, not the doctype row.
# db_set("") only blanks the row's masked placeholder; __Auth retains the
# prior secret, so get_password() keeps returning it. We explicitly drop
# the __Auth row for these fields.
_PASSWORD_FIELDS = {
	"jarvis_admin_api_key", "jarvis_admin_api_secret",
	"agent_token",
	"chat_device_private_key", "chat_device_token",
	"llm_api_key",
}


def is_sandbox_mode() -> bool:
	"""Return True iff this site is in sandbox mode.

	Resolution:
	  1. ``Jarvis Settings.sandbox_mode = 1`` (the canonical flag)
	  2. legacy fallback: ``frappe.conf.developer_mode`` is truthy
	     (kept for one release so existing dev installs don't break;
	     remove this branch in the release after this one)

	Either condition opens the dev surface (dev_onboard, reset_onboarding,
	the DEV-only reset button in Jarvis Settings). Customer responsibility:
	flip this only on dev/test benches. The trust model is self-attested -
	same as the legacy developer_mode behavior - so this is not a security
	hardening, just a UX improvement (discoverable in the settings form,
	doesn't bleed across apps, doesn't require a bench restart)."""
	try:
		if frappe.get_single_value(SETTINGS, "sandbox_mode"):
			return True
	except Exception:
		# DocType may not be migrated yet on a fresh install; fall through
		# to the legacy check rather than crashing.
		pass
	return bool(frappe.conf.get("developer_mode"))


def _dev_guard():
	"""Reject unless sandbox mode is enabled AND the caller is a System
	Manager. Sets HTTP 403 + throws so the form action surfaces the standard
	red dialog."""
	if not is_sandbox_mode():
		frappe.local.response.http_status_code = 403
		frappe.throw(
			"Sandbox mode is not enabled. Set Jarvis Settings -> "
			"Enable Sandbox Mode (or, legacy: developer_mode in site_config)."
		)
	if "System Manager" not in frappe.get_roles():
		frappe.local.response.http_status_code = 403
		frappe.throw("System Manager role required")


@frappe.whitelist()
def is_dev_mode_active() -> dict:
	"""Cheap probe so the Jarvis Settings form JS can decide whether to
	surface the reset button. Returns ``{active: True}`` iff both gates
	(sandbox mode + System Manager) pass for the current user."""
	try:
		_dev_guard()
		return {"ok": True, "data": {"active": True}}
	except frappe.ValidationError:
		frappe.local.response.http_status_code = 200
		return {"ok": True, "data": {"active": False}}


# Fields cleared by reset_onboarding(). Grouped here so tests can iterate
# without re-listing field names.
_RESET_CLEAR_FIELDS = (
	# Admin connection
	"jarvis_admin_api_key", "jarvis_admin_api_secret",
	# Agent / container
	"agent_url", "agent_token",
	# Chat device pairing
	"chat_device_id", "chat_device_public_key",
	"chat_device_private_key", "chat_device_token",
	# Last sync trace
	"last_sync_at", "last_sync_status",
	# LLM credentials (caller asked for a clean slate)
	"llm_model", "llm_api_key", "llm_base_url",
)


@frappe.whitelist()
def reset_onboarding() -> dict:
	"""Wipe local Jarvis Settings connection + LLM credentials so the
	customer bench can run the onboarding wizard from step 1 again.

	Preserved (these are settings, not onboarded session state):
	  - jarvis_admin_url        (so the bench remembers which admin to point at)
	  - enabled, token_budget_monthly
	  - sampling: llm_temperature, llm_max_output_tokens
	  - llm_provider (reset to the doctype default "Anthropic" so the form
	    stays valid - it's a Select field, can't be blank)

	Does NOT call the admin-side purge - use
	``jarvis_admin.api.dev.purge_customer`` on admin for that. Both buttons
	together give a clean two-step reset; this one alone is enough when the
	admin record was already removed or never created.
	"""
	_dev_guard()
	s = frappe.get_single(SETTINGS)
	for field in _RESET_CLEAR_FIELDS:
		s.db_set(field, "")
		if field in _PASSWORD_FIELDS:
			remove_encrypted_password(SETTINGS, SETTINGS, field)
	# Select field - must hold a valid option; reset to default.
	s.db_set("llm_provider", "Anthropic")
	frappe.db.commit()
	return {"ok": True, "data": {"cleared_fields": list(_RESET_CLEAR_FIELDS) + ["llm_provider"]}}
