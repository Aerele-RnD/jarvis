"""Pure serialization: Jarvis Settings.models -> (PoolSpec dict, api_keys, oauth_blobs).

Secrets are pulled OUT of the spec and keyed by a deterministic ref so the
rendered config stays secret-free.

All functions here are defensive: no function raises on bad input.
- get_password() calls use raise_exception=False (masked-empty → "").
- json.loads() is guarded; errors are reported via validate_models(), not raised.
"""
import json


def _get_password(doc, fieldname: str, raise_exception: bool = False) -> str:
    """Read a password field from a doc (BaseDocument) or plain dict/frappe._dict.

    - BaseDocument rows support .get_password() which handles DB-stored encrypted
      values and in-memory plaintext. raise_exception=False so masked-empty → "".
    - frappe._dict / plain dict rows (used in tests / in-memory) just have the
      raw value; read it directly.

    FT4 hardening: if the field is non-empty but get_password raises, propagate
    the error rather than collapsing it to "". Collapsing a real decryption failure
    to blank would silently drop the credential and send an empty secret to admin.
    """
    if callable(getattr(doc, "get_password", None)):
        try:
            return doc.get_password(fieldname, raise_exception=raise_exception) or ""
        except Exception:
            # Check if the raw in-memory field has content (masked) — if so,
            # this is a real decryption error, not "field unset".
            raw = getattr(doc, fieldname, None) or (doc.get(fieldname) if hasattr(doc, "get") else None)
            if raw and raw != "":
                raise  # Real decryption error: propagate
            return ""  # Field genuinely unset
    return (doc.get(fieldname) or "") if hasattr(doc, "get") else (getattr(doc, fieldname, "") or "")


def _key_ref(idx: int) -> str:
    return f"POOL_KEY_{idx}"


def _model_accounts(m) -> list:
    """Return a subscription model's accounts as a list of dicts.

    Accounts are stored as a JSON array string in the ENCRYPTED
    `subscription_accounts` Password field ON the model row (a child of the
    Jarvis Settings Single). We read it via _get_password so DB-backed rows are
    decrypted, then json.loads. Never raises: empty / malformed / non-list → [].

    Back-compat: in-memory rows / unit-test objects that still carry a plain
    `accounts` list attribute (the pre-migration grandchild shape) are honored
    when `subscription_accounts` is empty. Real persisted rows no longer have an
    `accounts` field, so production always takes the JSON path.
    """
    try:
        raw = _get_password(m, "subscription_accounts")
    except Exception:
        raw = ""
    if raw:
        try:
            parsed = json.loads(raw)
        except Exception:
            return []
        return parsed if isinstance(parsed, list) else []
    # Legacy in-memory fallback (never a DB read — the grandchild is gone).
    legacy = getattr(m, "accounts", None)
    if legacy is None and hasattr(m, "get"):
        legacy = m.get("accounts")
    return list(legacy) if legacy else []


def _safe_json_loads(blob: str):
    """Try to parse blob as JSON. Returns (parsed, error_str).

    error_str is None on success, a human-readable message on failure.
    FT4: also rejects blobs that parse successfully but are not a dict (e.g. lists).
    """
    try:
        parsed = json.loads(blob)
        if not isinstance(parsed, dict):
            return None, f"oauth_blob must be a JSON object (dict), got {type(parsed).__name__}"
        return parsed, None
    except Exception as exc:
        return None, f"malformed oauth_blob JSON: {exc}"


# ---------------------------------------------------------------------------
# compute_auto_enable — kept for back-compat with test_jarvis_llm_pool.py
# ---------------------------------------------------------------------------

def compute_auto_enable(pool) -> bool:
    """Legacy helper used by the old Jarvis LLM Pool on_update (kept for back-compat)."""
    return len([m for m in pool.models if m.enabled]) >= 2 or any(
        m.credential_type == "subscription" and _model_accounts(m)
        for m in pool.models
        if m.enabled
    )


# ---------------------------------------------------------------------------
# compute_proxy_active — new helper (re-sourced from settings)
# ---------------------------------------------------------------------------

def compute_proxy_active(settings) -> bool:
    """Return True when the proxy should be engaged.

    True when ≥2 models are enabled OR (a preset is selected AND ≥1 model enabled).
    An empty enabled-model list with a preset does NOT count as proxy-valid.
    """
    enabled = [m for m in (settings.models or []) if m.enabled]
    return len(enabled) >= 2 or (bool(settings.preset) and len(enabled) >= 1)


# ---------------------------------------------------------------------------
# validate_models — collect clean human-readable errors; never raises
# ---------------------------------------------------------------------------

def validate_models(settings) -> list:
    """Validate settings.models and return a list of human-readable error strings.

    Empty list means the configuration is clean.
    No exception is ever raised from this function.
    """
    errors = []
    seen_account_refs = {}  # account_ref -> model index (for duplicate detection)

    # If models has rows but ALL are disabled → at least 1 must be enabled.
    if settings.models:
        enabled_count = sum(1 for m in settings.models if m.enabled)
        if enabled_count == 0:
            errors.append("at least 1 model must be enabled when models are configured")
            return errors  # Early exit — rest of validation is moot

    for i, m in enumerate(settings.models):
        label = f"Model[{i}] ({getattr(m, 'model', None) or m.get('model', '?')})"

        if not m.enabled:
            continue

        cred_type = m.credential_type if hasattr(m, "credential_type") else m.get("credential_type", "api_key")

        if cred_type == "api_key":
            # Blank api_key on an enabled model → dangling key_ref
            try:
                key_val = _get_password(m, "api_key")
            except Exception:
                errors.append(f"cannot read api_key for model '{getattr(m, 'model', None) or m.get('model', '?')}' (decryption error)")
                continue
            if not key_val:
                errors.append(f"{label}: api_key is blank on an enabled model (would produce a dangling key_ref)")

        elif cred_type == "subscription":
            accounts = _model_accounts(m)

            # Empty accounts list
            if not accounts:
                errors.append(f"{label}: enabled subscription model has no accounts configured")
                continue

            # Per-account upstream consistency + anthropic ToS check + malformed oauth_blob
            upstreams = set()
            for j, a in enumerate(accounts):
                acc_ref = a.account_ref if hasattr(a, "account_ref") else a.get("account_ref", "")
                upstream = a.upstream if hasattr(a, "upstream") else a.get("upstream", "")

                # Blank account_ref on enabled subscription account
                if not acc_ref:
                    errors.append(
                        f"{label} account[{j}]: subscription account is missing account_ref"
                    )

                # anthropic upstream is ToS-banned
                if upstream == "anthropic":
                    errors.append(
                        f"{label} account[{j}] ({acc_ref}): upstream='anthropic' is not permitted (ToS)"
                    )

                upstreams.add(upstream)

                # Malformed oauth_blob — use _get_password so DB-backed masked rows
                # are decrypted correctly (avoids "malformed" error on re-save).
                try:
                    blob_raw = _get_password(a, "oauth_blob") if callable(getattr(a, "get_password", None)) else (a.oauth_blob if hasattr(a, "oauth_blob") else a.get("oauth_blob", ""))
                except Exception:
                    errors.append(f"cannot read oauth_blob for account '{acc_ref}' (decryption error)")
                    continue
                if blob_raw:
                    _, parse_err = _safe_json_loads(blob_raw)
                    if parse_err:
                        errors.append(f"{label} account[{j}] ({acc_ref}): {parse_err}")

                # Duplicate account_ref detection
                if acc_ref:
                    if acc_ref in seen_account_refs:
                        errors.append(
                            f"Duplicate account_ref '{acc_ref}' found in {label} account[{j}]"
                            f" (also in Model[{seen_account_refs[acc_ref]}])"
                        )
                    else:
                        seen_account_refs[acc_ref] = i

            # Mixed upstreams within one subscription model
            if len(upstreams) > 1:
                errors.append(
                    f"{label}: all accounts must share the same upstream;"
                    f" found mixed upstreams: {sorted(upstreams)}"
                )

    return errors


# ---------------------------------------------------------------------------
# build_pool_payload — re-sourced from settings (not pool single)
# ---------------------------------------------------------------------------

def build_pool_payload(settings):
    """Return (spec_dict, api_keys, oauth_blobs).

    Reads settings.models (enabled rows) + settings.routing_mode / settings.preset.
    Pure; no I/O except get_password (which uses raise_exception=False).

    Hygiene guarantees:
    - Secrets never appear in the returned spec dict.
    - Subscription models never emit 'provider' or 'base_url'.
    - key_ref is only emitted when the secret is non-empty (no dangling refs).
    - json.loads on oauth_blob is guarded; errors are silently skipped here
      (validate_models() catches them before save).
    """
    models, api_keys, oauth_blobs = [], {}, {}
    key_idx = 0

    for m in settings.models:
        if not m.enabled:
            continue

        cred_type = m.credential_type if hasattr(m, "credential_type") else m.get("credential_type", "api_key")

        entry = {
            "model": m.model if hasattr(m, "model") else m.get("model"),
            "tier": (m.tier if hasattr(m, "tier") else m.get("tier")) or "strong",
            "order": (m.order if hasattr(m, "order") else m.get("order")) or 0,
            "enabled": True,
        }

        if cred_type == "subscription":
            # Omit provider and base_url for subscription models (avoids subscription_field_conflict)
            accounts = _model_accounts(m)
            serialized_accounts = []
            upstream = "openai"  # default; overridden by consistent account upstreams

            upstreams_seen = []
            for a in accounts:
                acc_ref = a.account_ref if hasattr(a, "account_ref") else a.get("account_ref", "")
                a_upstream = (a.upstream if hasattr(a, "upstream") else a.get("upstream", "")) or "openai"
                upstreams_seen.append(a_upstream)

                serialized_accounts.append({
                    "account_ref": acc_ref,
                    "label": (a.label if hasattr(a, "label") else a.get("label", "")) or "",
                })

                # Defensively guard json.loads; errors surfaced via validate_models
                blob_raw = (a.oauth_blob if hasattr(a, "oauth_blob") else a.get("oauth_blob", "")) or ""
                if blob_raw:
                    parsed, _ = _safe_json_loads(blob_raw)
                    if parsed is not None and acc_ref:
                        oauth_blobs[acc_ref] = parsed

            # Use common upstream if consistent; fall back to "openai"
            if upstreams_seen:
                unique_upstreams = set(upstreams_seen)
                if len(unique_upstreams) == 1:
                    upstream = upstreams_seen[0]
                # else: mixed — validate_models will catch this; emit "openai" as safe default

            rotation = (m.rotation if hasattr(m, "rotation") else m.get("rotation", "")) or "sticky"
            entry["subscription"] = {
                "upstream": upstream,
                "accounts": serialized_accounts,
                "rotation": rotation,
            }

        else:
            # api_key model: only emit key_ref when secret is actually present
            # Guard: if get_password raises (decrypt error), treat as blank —
            # no key_ref emitted; validate_models will already have flagged this.
            try:
                val = _get_password(m, "api_key")
            except Exception:
                val = ""
            if val:
                ref = _key_ref(key_idx)
                key_idx += 1
                entry["key_ref"] = ref
                api_keys[ref] = val
            # else: no key_ref emitted — dangling ref avoided; validate_models flags this
            # Also emit provider/base_url for api_key models
            provider = (m.provider if hasattr(m, "provider") else m.get("provider", "")) or ""
            base_url = (m.base_url if hasattr(m, "base_url") else m.get("base_url", "")) or ""
            if base_url:
                entry["base_url"] = base_url
            if provider:
                entry["provider"] = provider

        models.append(entry)

    routing_mode = (
        (settings.routing_mode if hasattr(settings, "routing_mode") else settings.get("routing_mode", "")) or "dynamic"
    )

    # Tier-fallback: dynamic is meaningless without BOTH cheap + strong tiers
    tiers = {(m.get("tier") or "strong") for m in models}
    if routing_mode == "dynamic" and not ({"cheap", "strong"} <= tiers):
        routing_mode = "failover"  # fall back gracefully

    spec = {
        "name": _pool_name(),
        "routing_mode": routing_mode,
        "models": models,
    }
    if routing_mode == "dynamic":
        spec["classifier"] = {}  # pydantic defaults ClassifierConfig(); satisfies validate

    return spec, api_keys, oauth_blobs


def _pool_name() -> str:
    import frappe
    return (frappe.local.site or "jarvis-pool").split(".")[0]
