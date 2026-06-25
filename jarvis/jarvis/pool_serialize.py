"""Pure serialization: Jarvis LLM Pool doc -> (PoolSpec dict, api_keys, oauth_blobs).
Secrets are pulled OUT of the spec and keyed by a deterministic ref so the rendered
config stays secret-free."""
import json


def _get_password(doc, fieldname: str) -> str:
    """Read a password field from a doc (BaseDocument) or plain dict/frappe._dict.

    - BaseDocument rows support .get_password() which handles DB-stored encrypted
      values and in-memory plaintext.
    - frappe._dict / plain dict rows (used in tests / in-memory) just have the
      raw value; read it directly.
    """
    if callable(getattr(doc, "get_password", None)):
        return doc.get_password(fieldname) or ""
    return (doc.get(fieldname) or "") if hasattr(doc, "get") else (getattr(doc, fieldname, "") or "")


def _key_ref(idx: int) -> str:
    return f"POOL_KEY_{idx}"


def compute_auto_enable(pool) -> bool:
    return len([m for m in pool.models if m.enabled]) >= 2 or any(
        m.credential_type == "subscription" and m.get("accounts")
        for m in pool.models
        if m.enabled
    )


def build_pool_payload(pool):
    """Return (spec_dict, api_keys, oauth_blobs). Pure; no I/O except get_password."""
    models, api_keys, oauth_blobs = [], {}, {}
    key_idx = 0
    for m in pool.models:
        if not m.enabled:
            continue
        entry = {
            "model": m.model,
            "tier": m.tier or "strong",
            "order": m.order or 0,
            "enabled": True,
        }
        if m.base_url:
            entry["base_url"] = m.base_url
        if m.provider:
            entry["provider"] = m.provider
        if m.credential_type == "subscription":
            accounts = []
            upstream = "openai"
            for a in (m.get("accounts") or []):
                if not accounts:
                    upstream = a.upstream or "openai"
                accounts.append({
                    "account_ref": a.account_ref,
                    "label": a.label or "",
                })
                blob = _get_password(a, "oauth_blob") if a.oauth_blob else ""
                if blob:
                    oauth_blobs[a.account_ref] = json.loads(blob)
            entry["subscription"] = {
                "upstream": upstream,
                "accounts": accounts,
                "rotation": (m.rotation or "sticky"),
            }
        else:
            ref = _key_ref(key_idx)
            key_idx += 1
            entry["key_ref"] = ref
            val = _get_password(m, "api_key") if m.api_key else ""
            if val:
                api_keys[ref] = val
        models.append(entry)
    eff_mode = pool.routing_mode or "dynamic"
    # preset is honored as Custom in 2b; preset→tier templates deferred to 2c
    tiers = {(m.get("tier") or "strong") for m in models}
    if eff_mode == "dynamic" and not ({"cheap", "strong"} <= tiers):
        eff_mode = "failover"   # dynamic is meaningless without BOTH tiers; fall back
    spec = {
        "name": _pool_name(),
        "routing_mode": eff_mode,
        "models": models,
    }
    if eff_mode == "dynamic":
        spec["classifier"] = {}   # pydantic defaults ClassifierConfig(); satisfies validate
    return spec, api_keys, oauth_blobs


def _pool_name() -> str:
    import frappe
    return (frappe.local.site or "jarvis-pool").split(".")[0]
