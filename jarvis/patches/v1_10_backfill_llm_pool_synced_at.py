"""Backfill Jarvis Settings.llm_pool_synced_at for pre-marker pool tenants.

The marker ("this pool config has been APPLIED to the container at least
once") was introduced with the honest is_ready_for_chat gate; the pool-sync
worker stamps it on every successful apply. Tenants provisioned BEFORE the
field existed have it empty, and the gate reads that as "never applied" -
without this backfill they would be bounced to onboarding on their next
pool re-save (the save flips last_sync_status to "pending:", so the
one-shot "current status is ok" signal disappears exactly when they need
it).

Backfill rule: a pool tenant (proxy_active=1) whose last_sync_status
currently starts with "ok" demonstrably has an applied pool - stamp the
marker with last_sync_at (or now as a fallback). Tenants mid-sync or in a
failed state at migrate time are left empty; their next successful sync
stamps it.

Reads go through the document API, NOT frappe.db.get_single_value: the
latter coerces an EMPTY Datetime single to the truthy sentinel
datetime(1, 1, 1), which would make the "already set" short-circuit fire
on exactly the tenants this patch exists to backfill.
"""

import frappe


def execute():
	settings = frappe.get_single("Jarvis Settings")
	if not settings.proxy_active:
		return
	if settings.llm_pool_synced_at:
		return
	status = (settings.last_sync_status or "").strip()
	if not status.startswith("ok"):
		return
	synced_at = settings.last_sync_at or frappe.utils.now()
	frappe.db.set_single_value("Jarvis Settings", "llm_pool_synced_at", synced_at)
