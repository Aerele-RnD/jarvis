"""Keep the control plane's Jarvis Tenant.installed_apps in step with the bench.

installed_apps reaches admin ONLY inside post_update_llm_creds (fired from an
LLM-settings save). Installing or removing an app never fired that, so the
fleet kept gating persona skill families and shortcut-tool denies off a stale
app list until the next unrelated creds save - a tenant that added hrms got
no hrms-* skills AND kept the hrms shortcut tools denied. Every app change
ends with bench migrate, so after_migrate compares the live list against the
last-synced snapshot and enqueues the existing creds-restart sync (whose
payload carries the fresh list; admin re-renders openclaw.json and restarts
the container) when they differ.

The snapshot (Jarvis Settings.installed_apps_synced) is written only after
post_update_llm_creds RETURNS (admin persists installed_apps desired-first) -
a failed send leaves it stale so the next migrate retries. Safe direction:
a stale snapshot costs one redundant resync; a premature one would silence
the gap forever.

An EMPTY snapshot (first migrate after this feature deploys) seeds the
baseline WITHOUT a sync: onboarding already sent the then-current list, and
seeding quietly avoids a fleet-wide restart wave on the deploy migrate. A
tenant that was ALREADY stale pre-feature converges on its next app change
or creds save.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import cint

SETTINGS = "Jarvis Settings"
FIELD = "installed_apps_synced"


def after_migrate() -> None:
	"""Best-effort resync check; never blocks a migrate."""
	try:
		from jarvis import selfhost

		if selfhost.is_self_hosted():
			return  # no control plane; skill gating is a managed-fleet feature
		if not _admin_configured():
			return  # pre-onboarding bench - nothing to sync against yet
		current = _current_apps()
		synced = _synced_apps()
		if synced is None:
			record_synced_snapshot()
			return
		if current == synced:
			return
		pool = _pool_active()
		if pool is None:
			# Can't tell which leg is safe - defer rather than guess (the
			# single-model leg on a pool tenant would break Bifrost routing).
			# The snapshot stays stale, so the next migrate retries.
			frappe.logger("jarvis.installed_apps").warning(
				"proxy_active unreadable; deferring installed-apps resync")
			return
		_enqueue_resync(synced, current, pool=pool)
	except Exception:
		frappe.log_error(
			title="installed-apps resync check failed",
			message=frappe.get_traceback(),
		)


def record_synced_snapshot() -> None:
	"""Stamp the live app list as synced. Called from _sync_via_admin right
	after a post_update_llm_creds that carried it. Never raises."""
	try:
		frappe.db.set_single_value(
			SETTINGS, FIELD, json.dumps(_current_apps()), update_modified=False
		)
	except Exception:
		pass


def _current_apps() -> list[str]:
	return sorted(frappe.get_installed_apps())


def _synced_apps() -> list[str] | None:
	"""The last-synced snapshot, or None when never recorded / unreadable
	(unreadable reads as never-recorded: the seed path rewrites it)."""
	raw = frappe.db.get_single_value(SETTINGS, FIELD)
	if not raw:
		return None
	try:
		val = json.loads(raw)
	except ValueError:
		return None
	if not isinstance(val, list):
		return None
	return sorted(str(a) for a in val if a)


def _admin_configured() -> bool:
	"""True when the bench points at a control plane (jarvis_admin_url set -
	site config outranks the Settings field, matching admin_client)."""
	try:
		if (frappe.conf.get("jarvis_admin_url") or "").strip():
			return True
		settings = frappe.get_cached_doc(SETTINGS)
		return bool((settings.get("jarvis_admin_url") or "").strip())
	except Exception:
		return False


def _pool_active() -> bool | None:
	"""True when the tenant runs the LLM pool (proxy) config. The resync MUST
	take the pool leg then: the single-model restart would re-render
	openclaw.json in direct mode and knock the container off Bifrost pool
	routing. None when unreadable - the caller defers instead of guessing a
	leg (defense in depth; a wrong single-model guess IS the routing bug)."""
	try:
		return bool(cint(frappe.db.get_single_value(SETTINGS, "proxy_active")))
	except Exception:
		return None


def _enqueue_resync(synced: list[str], current: list[str], pool: bool) -> None:
	"""Ride the existing sync machinery verbatim - the POOL leg for
	proxy_active tenants (payload carries installed_apps; admin persists +
	pool-renders, preserving Bifrost routing), the single-model creds-restart
	leg otherwise. Same job ids as the real ops so close-together triggers
	coalesce; the workers re-read Settings at run time, so admin lands the
	LIVE list even if it changes again before the job runs."""
	from jarvis.jarvis.doctype.jarvis_settings.jarvis_settings import (
		ADMIN_SYNC_RQ_TIMEOUT_S,
	)

	frappe.logger("jarvis.installed_apps").info(
		"installed_apps changed %s -> %s; enqueueing %s resync",
		synced, current, "pool" if pool else "creds-restart",
	)
	run_inline = bool(frappe.flags.in_test or frappe.flags.run_admin_sync_inline)
	common = {
		"queue": "long",
		"timeout": ADMIN_SYNC_RQ_TIMEOUT_S,
		"enqueue_after_commit": not run_inline,
		"now": run_inline,
		"deduplicate": True,
	}
	if pool:
		frappe.enqueue(
			"jarvis.jarvis.doctype.jarvis_settings.jarvis_settings"
			"._enqueued_sync_via_admin_pool",
			job_id="jarvis_settings_sync:pool",
			**common,
		)
	else:
		frappe.enqueue(
			"jarvis.jarvis.doctype.jarvis_settings.jarvis_settings"
			"._enqueued_sync_via_admin",
			job_id="jarvis_settings_sync:restart",
			action="restart",
			**common,
		)
