import frappe
from frappe.model.document import Document
from jarvis.jarvis.pool_serialize import build_pool_payload, compute_auto_enable


class JarvisLLMPool(Document):
    def on_update(self):
        self.auto_enabled = compute_auto_enable(self)
        if self.auto_enabled and not self.enabled:
            self.db_set("enabled", 1, update_modified=False)
            self.db_set("auto_enabled", 1, update_modified=False)
        # Only sync when the proxy is on (managed path). Single-model stays on /llm-creds.
        if not self.enabled:
            return
        spec, api_keys, oauth_blobs = build_pool_payload(self)
        self.db_set("last_sync_status", "pending", update_modified=False)
        run_inline = bool(frappe.flags.in_test or frappe.flags.run_admin_sync_inline)
        frappe.enqueue(
            "jarvis.jarvis.doctype.jarvis_llm_pool.jarvis_llm_pool._enqueued_pool_sync",
            queue="long",
            timeout=120,
            enqueue_after_commit=not run_inline,
            now=run_inline,
            job_id="jarvis_llm_pool_sync",
            deduplicate=True,
            spec=spec,
            api_keys=api_keys,
            oauth_blobs=oauth_blobs,
        )


def _enqueued_pool_sync(spec, api_keys, oauth_blobs):
    from jarvis import admin_client
    try:
        admin_client.post_update_llm_pool(spec=spec, api_keys=api_keys, oauth_blobs=oauth_blobs)
        frappe.db.set_single_value("Jarvis LLM Pool", "last_sync_status", "ok")
        frappe.db.set_single_value("Jarvis LLM Pool", "last_sync_error", "")
    except Exception as e:
        frappe.db.set_single_value("Jarvis LLM Pool", "last_sync_status", "error")
        frappe.db.set_single_value("Jarvis LLM Pool", "last_sync_error", str(e)[:500])
        raise
