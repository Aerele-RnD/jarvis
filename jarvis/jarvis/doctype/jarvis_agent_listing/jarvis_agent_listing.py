"""Jarvis Agent Listing DocType controller.

One row per marketplace agent, synced from the BUNDLED
``jarvis/agents/registry.json`` by ``jarvis.chat.agent_catalog.sync_agent_listings``
(never fetched at runtime — bundles are reviewed deploy artifacts, S2).

A read-only catalog to customers (``All`` role has read only; ``System Manager``
writes via the sync). The controller is intentionally thin: all upsert logic
lives in the sync so a re-sync is idempotent.
"""

from frappe.model.document import Document


class JarvisAgentListing(Document):
	pass
