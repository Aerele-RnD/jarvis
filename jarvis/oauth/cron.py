"""Scheduled OAuth-status reconciliation between bench and container.

Sprint-3 (2026-06-16 review): the previous flow set
``llm_oauth_account_email`` + ``llm_oauth_connected_at`` ONCE at
``complete_paste_signin`` and never re-checked. If the container's
auth-profiles.json later loses the profile (refresh-token failure,
operator manually cleared, container re-provisioned without the bench
re-pushing), the bench UI keeps showing "Connected" until the user
hits a chat-time ``ProviderAuthError`` mid-turn.

This module's ``poll_oauth_refresh_status`` runs hourly. For tenants in
``llm_auth_mode == "oauth"`` it asks admin/fleet whether the container
actually holds a usable profile right now. If not, it flips
``last_sync_status`` to ``"oauth_expired"`` and clears
``llm_oauth_account_email`` so the UI can render a "reconnect" banner.

Failure modes are noisy on purpose: an AdminUnreachableError is logged
but does NOT flip the status (we can't tell the difference between
"container forgot the profile" and "we can't reach the container").
Only an authoritative ``auth_profile_present == False`` flips state.
"""

from __future__ import annotations

import frappe


_LAST_SYNC_OAUTH_EXPIRED = "oauth_expired"


def poll_oauth_refresh_status() -> None:
	"""Hourly scheduled job: reconcile bench-side OAuth state with the
	container's actual auth-profile presence.

	No-op when:
	  - llm_auth_mode != "oauth" (api-key tenants don't have a refresh path)
	  - last_sync_status already reflects oauth_expired (avoid status flap)
	  - admin is unreachable / auth fails (ambiguous; don't flip)
	"""
	settings = frappe.get_single("Jarvis Settings")
	if (settings.llm_auth_mode or "api_key") != "oauth":
		return

	# Cheap early-exit: if we never connected (or already flipped to
	# expired), there's nothing to check.
	if not (settings.llm_oauth_account_email or "").strip():
		return

	from jarvis import admin_client
	try:
		result = admin_client.post_llm_auth_status() or {}
	except admin_client.AdminUnreachableError as e:
		# Network blip - can't distinguish container-lost-profile from
		# admin-down. Log once and skip; the next hourly tick will retry.
		frappe.logger().info(
			"oauth_refresh_poll: admin unreachable; skipping (%s)", e,
		)
		return
	except admin_client.AdminAuthError as e:
		# Bench credentials problem - flag in last_sync_status separately
		# from oauth_expired so the operator can tell them apart.
		settings.db_set({
			"last_sync_status": f"failed: auth: {e}",
			"last_sync_at": frappe.utils.now(),
		})
		frappe.log_error(
			title="oauth_refresh_poll: admin auth failed",
			message=frappe.get_traceback(),
		)
		return
	except admin_client.AdminRateLimitedError as e:
		retry = e.retry_after_seconds or 0
		frappe.logger().info(
			"oauth_refresh_poll: admin rate-limited (retry_after=%ds); skipping",
			retry,
		)
		return

	data = (result or {}).get("data") or result or {}
	# Admin returns wrapped or unwrapped depending on the _post helper;
	# the inner shape is the one we care about.
	present = bool(data.get("auth_profile_present"))
	if present:
		# Still healthy. Don't touch last_sync_status - leave whatever
		# the last legitimate save wrote there.
		return

	# Container reports the profile is absent. Flip to expired so the
	# UI can show a reconnect banner. Clear the cached account email
	# so the "Connected as <email>" UI element flips off.
	current_status = settings.last_sync_status or ""
	settings.db_set({
		"last_sync_status": _LAST_SYNC_OAUTH_EXPIRED,
		"last_sync_at": frappe.utils.now(),
		"llm_oauth_account_email": "",
	})
	frappe.logger().info(
		"oauth_refresh_poll: container reports auth profile absent; "
		"flipped last_sync_status %r -> %r",
		current_status, _LAST_SYNC_OAUTH_EXPIRED,
	)
