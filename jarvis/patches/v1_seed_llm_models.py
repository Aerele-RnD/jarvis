# Migration: seed Jarvis Settings.models from legacy llm_* fields
# Idempotent: only runs if models table is empty AND llm_model is set

import frappe


def execute():
    frappe.set_user("Administrator")
    settings = frappe.get_single("Jarvis Settings")
    if settings.get("models"):
        return  # Already migrated
    if not settings.get("llm_model"):
        return  # Nothing to migrate

    credential_type = (
        "api_key"
        if settings.get("llm_auth_mode") in ("api_key", "", None)
        else "subscription"
    )
    api_key = settings.get_password("llm_api_key", raise_exception=False) or ""

    settings.append("models", {
        "provider": settings.get("llm_provider") or "",
        "model": settings.get("llm_model"),
        "base_url": settings.get("llm_base_url") or "",
        "credential_type": credential_type,
        "tier": "strong",
        "order": 0,
        "enabled": 1,
        "api_key": api_key,
    })
    settings.save(ignore_permissions=True)
