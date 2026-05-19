"""Rename openclaw_* fields on Jarvis Settings to agent_* and jarvis_admin_*.

Background: Phase 1 reserved two placeholder fields (openclaw_endpoint,
openclaw_api_key) for the future SaaS control plane. Phase 3 finally
fills that role with `jarvis_admin`, so the placeholders get their real
names. The operator-tab fields (gateway URL/token/paths) get brand-
neutral `agent_*` names so customers never see "openclaw" in the UI.

Module file names (openclaw_bootstrap.py, etc.) are intentionally NOT
renamed — they're implementation detail, not customer-visible.
"""

import frappe
from frappe.model.utils.rename_field import rename_field


RENAMES = [
    ("openclaw_endpoint", "jarvis_admin_url"),
    ("openclaw_api_key", "jarvis_admin_api_key"),
    ("openclaw_gateway_url", "agent_url"),
    ("openclaw_gateway_token", "agent_token"),
    ("openclaw_compose_dir", "agent_compose_dir"),
    ("openclaw_config_path", "agent_config_path"),
    ("openclaw_llm_key_path", "agent_llm_key_path"),
]


def execute():
    """Rename each field on the Jarvis Settings Single DocType."""
    doctype = "Jarvis Settings"
    meta = frappe.get_meta(doctype)
    existing_fields = {f.fieldname for f in meta.fields}

    for old_name, new_name in RENAMES:
        if new_name in existing_fields:
            # Already migrated — skip (patch is idempotent)
            continue
        if old_name not in existing_fields:
            # Neither old nor new — fresh install, nothing to rename
            continue
        rename_field(doctype, old_name, new_name)

    frappe.clear_cache(doctype=doctype)
