"""Backfill Jarvis Settings.llm_pool_synced_at for pre-marker pool tenants.

The marker ("this pool config has been APPLIED to the container at least
once") was introduced with the honest is_ready_for_chat gate; the pool-sync
worker stamps it on every successful apply. Tenants provisioned BEFORE the
field existed have it empty, and the gate reads that as "never applied" -
without this backfill they would be bounced to onboarding on their next
pool re-save (the save flips last_sync_status to "pending:", so the
one-shot "current status is ok" signal disappears exactly when they need
it).

Backfill rule: EVERY pre-marker pool tenant (proxy_active=1) is stamped.
The patch's job is grandfathering, not retroactive enforcement: before
this deploy the gate was proxy_active alone, so every existing pool
tenant - including one whose LATEST re-save happens to be transiently
"pending:"/"failed:" at migrate time while the container keeps serving
the previously applied pool - was chat-ready. Conditioning the stamp on
a current "ok" status would demote exactly those working tenants to
"never provisioned" mid-upgrade (onboarding banner, wizard shove). A
truly never-applied pre-marker pool tenant is theoretical (the old gate
let them into chat anyway); the honest gate applies to tenants created
AFTER this deploy, whose marker lifecycle starts clean.

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
	synced_at = settings.last_sync_at or frappe.utils.now()
	frappe.db.set_single_value("Jarvis Settings", "llm_pool_synced_at", synced_at)
