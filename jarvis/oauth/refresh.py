"""Bench-side cron handler — refreshes OAuth access tokens before expiry.

Fired every 5 min by ``scheduler_events`` in ``hooks.py``. Reads Jarvis
Settings (a Single), refreshes if within :data:`REFRESH_WINDOW` of expiry,
pushes the new access token to openclaw via the existing
``secrets.reload`` path.
"""
from datetime import datetime, timedelta

import frappe

from jarvis import openclaw_push
from jarvis.exceptions import JarvisError
from jarvis.hooks import get_oauth_client_id
from jarvis.oauth import device_flow

REFRESH_WINDOW = timedelta(minutes=15)
TRANSIENT_FAIL_THRESHOLD = 3
_FAIL_COUNT_KEY = "jarvis.oauth.refresh.fail_count"


def tick():
	"""Scheduler entry. Idempotent; safe to call when nothing needs doing."""
	settings = frappe.get_single("Jarvis Settings")
	if settings.llm_auth_mode != "subscription":
		return

	expires_at = settings.llm_oauth_access_token_expires_at
	if expires_at:
		# Frappe stores Datetime as string; coerce.
		if isinstance(expires_at, str):
			expires_at = frappe.utils.get_datetime(expires_at)
		if (expires_at - datetime.utcnow()) > REFRESH_WINDOW:
			return  # Token still fresh.

	refresh_token = settings.get_password("llm_oauth_refresh_token", raise_exception=False)
	if not refresh_token:
		return  # Nothing to refresh (disconnected); noop.

	provider = settings.llm_provider
	try:
		client_id = get_oauth_client_id(provider)
	except ValueError:
		frappe.logger().error(f"oauth.refresh: no client_id for {provider}")
		return

	try:
		result = device_flow.refresh(provider, refresh_token=refresh_token, client_id=client_id)
	except device_flow.InvalidGrant:
		_mark_revoked(settings)
		return
	except (device_flow.ProviderUnavailable, JarvisError) as e:
		_record_transient_failure(settings, str(e))
		return

	_apply_refresh(settings, result)


def _apply_refresh(settings, result: dict):
	new_expiry = datetime.utcnow() + timedelta(seconds=result["expires_in"])
	settings.db_set("llm_oauth_access_token", result["access_token"], update_modified=False)
	settings.db_set("llm_oauth_access_token_expires_at", new_expiry, update_modified=False)
	settings.db_set("llm_oauth_last_refresh_at", datetime.utcnow(), update_modified=False)
	if result.get("refresh_token"):
		settings.db_set("llm_oauth_refresh_token", result["refresh_token"], update_modified=False)
	settings.db_set("last_sync_status", "subscription_connected", update_modified=False)
	# Reset transient-fail counter
	frappe.cache.delete_value(_FAIL_COUNT_KEY)
	# Push new access token to openclaw via existing reload path
	try:
		openclaw_push.push_creds_reload(settings)
	except Exception as e:
		frappe.log_error(
			title="Jarvis: openclaw reload after oauth refresh failed",
			message=frappe.get_traceback(),
		)
		settings.db_set("last_sync_status", f"failed: openclaw reload: {e}", update_modified=False)
		return
	frappe.logger().info(
		f"oauth.refresh provider={settings.llm_provider} "
		f"email={settings.llm_oauth_account_email} status=ok "
		f"next_expiry={new_expiry.isoformat()}"
	)


def _mark_revoked(settings):
	from frappe.utils.password import remove_encrypted_password
	for f in ("llm_oauth_refresh_token", "llm_oauth_access_token"):
		# Clear both layers: the encrypted row in __Auth and the plaintext in
		# the main table column (db_set on a Password field writes plaintext
		# to the column; remove_encrypted_password only clears __Auth).
		remove_encrypted_password("Jarvis Settings", "Jarvis Settings", f)
		settings.db_set(f, None, update_modified=False)
	settings.db_set("llm_oauth_access_token_expires_at", None, update_modified=False)
	settings.db_set("last_sync_status", "subscription_revoked", update_modified=False)
	frappe.logger().warning(
		f"oauth.refresh provider={settings.llm_provider} status=revoked"
	)


def _record_transient_failure(settings, error_str: str):
	count = int(frappe.cache.get_value(_FAIL_COUNT_KEY) or 0) + 1
	frappe.cache.set_value(_FAIL_COUNT_KEY, count, expires_in_sec=3600)
	if count >= TRANSIENT_FAIL_THRESHOLD:
		settings.db_set("last_sync_status", "subscription_refresh_failing", update_modified=False)
	frappe.logger().info(
		f"oauth.refresh provider={settings.llm_provider} status=transient_fail "
		f"count={count} error={error_str!r}"
	)
