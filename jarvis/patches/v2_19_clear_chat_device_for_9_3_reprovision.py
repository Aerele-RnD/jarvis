"""9.3 reprovision: clear the stale chat-device pairing so it re-bootstraps clean.

The 6.8 -> 9.3 upgrade rebuilds each tenant's container FRESH (the old openclaw state
can't migrate in place), so the bench's stored chat-device token is stale -- the new
container's SQLite has no record of it, and every connect would fail with
"device token mismatch" until something re-pairs. Clearing the four chat_device_*
credentials flips ``device.needs_bootstrap`` True, so the bench's NEXT connection
re-pairs cleanly -- via Mechanism A on a 9.3 container, or the legacy forge if the
container is somehow still 6.8 (the re-pair adapts to the tenant's image).

Why a patch and not only the connect-time self-heal: this fires PROACTIVELY on the
post-reprovision app upgrade, so the re-pair does not depend on the reactive
device_token_mismatch detection firing, nor on the customer chatting first. The
self-heal still covers any future stale-token case; this just de-risks the bulk roll.

One-time (patches run once, tracked). Idempotent -- a second run on already-empty
fields is a no-op. ``chat_device_token`` / ``chat_device_private_key`` are Password
fields (stored in __Auth); ``db.set_value`` clears both those and the two plain
fields. Dropping the keypair is safe: the next bootstrap regenerates a stable one.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Jarvis Settings"):
		return
	frappe.db.set_value(
		"Jarvis Settings",
		"Jarvis Settings",
		{
			"chat_device_id": "",
			"chat_device_public_key": "",
			"chat_device_token": "",
			"chat_device_private_key": "",
		},
	)
	frappe.clear_cache(doctype="Jarvis Settings")
