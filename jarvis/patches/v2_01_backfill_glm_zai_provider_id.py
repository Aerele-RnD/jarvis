"""Backfill Jarvis LLM Pool Model rows collapsed into "openai_compat" that were
actually GLM / Z.ai, restoring their first-class "zai" provider id.

Root cause (fixed in the same deploy as this patch): jarvis.onboarding.save_llm_pool
normalized the incoming provider label BEFORE persisting it into
Jarvis Settings.models[].provider, and pool_serialize._PROVIDER_ALIASES mapped
"glm / z.ai" straight to "openai_compat" - a different provider's canonical id,
unlike every other alias in that table (which maps a label to ITS OWN id). So a
row saved as "GLM / Z.ai" was permanently stored as provider="openai_compat";
the row's `model` (glm-4.6) and `base_url` (https://api.z.ai/...) survived, but
the Provider dropdown and the AI-models row chip both rendered
"OpenAI-Compatible" on every reload, with no way for the customer to tell the
row was ever GLM without re-checking the base_url.

The fix moves that collapse to WIRE-serialization time only (inside
pool_serialize.build_pool_payload, via _wire_provider()), so new saves store
the first-class "zai" id and the label renders correctly, while the Bifrost
wire payload is unchanged (still emits "openai_compat" + base_url for a zai
row - Bifrost has no native zai provider).

This patch backfills rows written under the old (storage-collapsing) code:
provider == "openai_compat" AND base_url points at a Z.ai host
(api.z.ai - covers both the standard .../api/paas/v4 and coding-plan
.../coding/paas/v4 endpoints) -> provider = "zai".

Conservative by design: a genuine openai_compat row (a Claude-CLI gateway
shim, a local relay, anything NOT hosted at api.z.ai) is left untouched -
matching on base_url host, not merely "has a base_url", avoids
misclassifying unrelated custom-endpoint rows as GLM.

Direct field update via frappe.db.set_value on the child row, bypassing
Jarvis Settings.save()/on_update entirely (mirrors v1_seed_llm_models's
insert-not-save pattern): this is a label-only correction of already-applied
config, so it must not re-validate, re-render openclaw.json, or make any
admin/fleet-agent network call during bench migrate.
"""

import frappe

# Both known Z.ai API hosts: the standard endpoint and the coding-plan
# endpoint (different path, same host) - either identifies a GLM / Z.ai row.
_ZAI_HOST = "api.z.ai"


def execute():
	rows = frappe.get_all(
		"Jarvis LLM Pool Model",
		filters={"parenttype": "Jarvis Settings", "provider": "openai_compat"},
		fields=["name", "base_url"],
	)
	for row in rows:
		base_url = (row.base_url or "").strip().lower()
		if _ZAI_HOST in base_url:
			frappe.db.set_value(
				"Jarvis LLM Pool Model", row.name, "provider", "zai",
				update_modified=False,
			)
	frappe.db.commit()
