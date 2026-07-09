"""Backfill Jarvis Settings.llm_pool_synced_at for pre-marker pool tenants.

The marker ("this pool config has been APPLIED to the container at least
once") was introduced with the honest is_ready_for_chat gate; the pool-sync
worker stamps it on every successful apply. Tenants provisioned BEFORE the
field existed have it empty, and the gate reads that as "never applied" -
without this backfill they would be bounced to onboarding on their next
pool re-save (the save flips last_sync_status to "pending:", so the
one-shot "current status is ok" signal disappears exactly when they need
it).

Backfill rule: every pre-marker pool tenant (proxy_active=1) whose sync
has EVER reached a terminal state (last_sync_at set) is stamped. The
patch's job is grandfathering, not retroactive enforcement: before this
deploy the gate was proxy_active alone, so an existing pool tenant whose
LATEST re-save happens to be transiently "pending:"/"failed:" at migrate
time - while the container keeps serving the previously applied pool -
was chat-ready and must stay so. Conditioning the stamp on a current
"ok" status would demote exactly those working tenants to "never
provisioned" mid-upgrade (onboarding banner, wizard shove).

The one tenant NOT stamped: last_sync_at empty, i.e. no sync ever
completed - their pool has demonstrably never been applied, chat has
never worked, and stamping would permanently mark the broken pool as
ready and permanently disarm the llm_pool_provisioning gate for them.
Leaving them unstamped routes them to the onboarding poster, which is an
improvement over their pre-deploy state (a chat surface where every
turn failed), not a regression. Their marker sets on the first
successful sync.

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
	if not settings.last_sync_at:
		# No sync ever completed: nothing to grandfather (see module doc).
		return
	frappe.db.set_single_value("Jarvis Settings", "llm_pool_synced_at", settings.last_sync_at)
