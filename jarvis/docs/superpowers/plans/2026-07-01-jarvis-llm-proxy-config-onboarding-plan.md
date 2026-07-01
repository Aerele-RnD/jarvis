# LLM-Proxy Config + Onboarding + Manage UI Implementation Plan — Plan 2 of 3

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a customer configure a multi-model LLM pool (preset or custom, failover) from the desk onboarding step and from a new Vue `/ai` Manage tab, writing through the existing unified `Jarvis Settings` pipeline.

**Architecture:** One new write endpoint `save_llm_pool` + reads `get_preset_catalog`/`get_llm_config` in `jarvis.onboarding`; the write mutates `Jarvis Settings.models[]` and lets the existing `on_update` derive direct-vs-proxy and sync via admin. Frontend: extend the vanilla-JS desk page (Quick/Preset/Custom) and add a Vue `/ai` route (Manage tab), both consuming ONE shared pure-logic module `frontend/src/llm/pool.js`.

**Tech Stack:** Frappe v16 (Python), FrappeTestCase; vanilla-JS Frappe desk page (jQuery, frappe.call); Vue 3 + vue-router + frappe-ui `call()`; Node built-in test runner (`node --test`) for pure logic.

**This is Plan 2 of 3.** Spec: `jarvis/docs/superpowers/specs/2026-07-01-jarvis-llm-proxy-ui-design.md`. **Depends on Plan 1** for the admin catalog endpoint `jarvis_admin.billing.catalog.get_preset_catalog` — but every task here mocks admin_client, so Plan 2 builds/tests without Plan 1 deployed. Plan 3 (monitor) depends on this plan's `/ai` AiView shell + api.js wrappers.

## Global Constraints

- **Canonical endpoint module map** (do not deviate): `jarvis.onboarding.save_llm_pool`, `jarvis.onboarding.get_preset_catalog`, `jarvis.onboarding.get_llm_config`, `jarvis.onboarding.get_llm_sync_status` (already exists). (`get_llm_usage`/`get_llm_connection_status` are Plan 3, in `jarvis.account`.)
- **Contract shapes (verbatim):** `save_llm_pool(models, preset=None, routing_mode="failover")`; catalog entry `{key,label,kind:"single_vendor"|"cross_vendor",blurb,enabled,models:[{provider,model,order}],vendors:[...]}`; Settings `models[]` row `{provider,model,api_key,base_url?,tier?,order,subscription?}`; `get_llm_config() -> {models[],preset,routing_mode,proxy_active}`.
- **Catalog keys are hyphenated slugs**, identical to Plan 1's admin seed: `openai-resilient`, `anthropic-resilient`, `gemini-resilient`, `mistral-resilient`, `cost-saver`, `balanced`, `max-reliability`.
- **routing_mode is ALWAYS `"failover"` in v1** — `save_llm_pool` sets it explicitly and rejects any other value; no routing UI control.
- **Proxy is DERIVED, never a written flag:** 1 model & no preset → direct; ≥2 models or a preset → proxy. `save_llm_pool` must NOT set `proxy_active`, must NOT re-validate, must NOT set legacy `llm_*` — the `on_update` pipeline (`_on_update_unified_llm`) owns all of that; a bad pool surfaces as `frappe.ValidationError` from `s.save()`.
- **Never return secrets.** `get_llm_config` returns a `has_key` boolean, never `api_key`. Read `models[]`, NOT the legacy `llm_*` mirror fields.
- **All config writes + reads are System-Manager-only** (`frappe.only_for("System Manager")`), per spec §7.
- **Presets are all-or-nothing (L8):** saving a preset requires a key for every unique vendor; single-vendor ladder = one key. Quick/Custom is the escape hatch.
- **Quick mode is unchanged:** keep the existing single-model `save_llm_creds` + Chat-subscription path byte-for-byte; do NOT reroute Quick through `save_llm_pool`.
- **ONE shared pure-logic module** `frontend/src/llm/pool.js` (created in Task B1) is consumed by BOTH the desk page (via a bundle exposing `window.jarvis_onboarding_llm`) and the Vue app (direct import) — no second copy.
- **Run commands:** Python tests `bench --site site.jarvis run-tests --module jarvis.tests.<module>` (schema changes need `bench --site site.jarvis migrate` first); JS `cd /Users/kavin/frappe/v16/bench-16/apps/jarvis/frontend && node --test <file>`; Vue build `npm run build` (from `frontend/`). Frontend node commands may need node20 on PATH: `export PATH="$HOME/.nvm/versions/node/v20.19.6/bin:$PATH"`.

## File Structure

**Phase A — backend (`apps/jarvis/jarvis/`):**
- `_preset_catalog.py` (new) — `BUNDLED_PRESET_CATALOG` fallback
- `admin_client.py` (edit) — `get_preset_catalog()` fetch/cache/fallback
- `onboarding.py` (edit) — whitelisted `get_preset_catalog`, `save_llm_pool`, `get_llm_config`
- `jarvis/doctype/jarvis_settings/jarvis_settings.json` (edit) — `preset` Select→Data
- `tests/test_preset_catalog.py`, `tests/test_llm_pool_endpoints.py` (new); `tests/test_unified_llm_config.py` (edit assertion)

**Phase B — onboarding desk (`apps/jarvis/`):**
- `frontend/src/llm/pool.js` + `pool.test.js` (new) — shared pure logic
- `jarvis/public/js/jarvis_onboarding_llm.bundle.js` (new) + `jarvis/hooks.py` (edit) — expose to desk
- `jarvis/jarvis/page/jarvis_onboarding/jarvis_onboarding.js` (edit) — modes, cards, custom, CSS, rename

**Phase C — Vue Manage (`apps/jarvis/frontend/src/`):**
- `theme.js` + `theme.test.js` (new); `views/ChatView.vue` (edit — import theme)
- `api.js` (edit) — `getLlmConfig`/`getPresetCatalog`/`getLlmSyncStatus`/`saveLlmPool`
- `router/index.js` (edit) + `jarvis/www/jarvis.py` (edit) — `/ai` route + `is_system_manager` boot
- `views/AiView.vue` (new) — Manage tab + Monitor-tab placeholder (Plan 3 fills it)

---

## Phase A — Customer backend

### Task A1 — `admin_client.get_preset_catalog()` + bundled fallback + whitelisted wrapper

**Files:** Create `jarvis/_preset_catalog.py`, `jarvis/tests/test_preset_catalog.py`; edit `jarvis/admin_client.py`, `jarvis/onboarding.py`.

**Interfaces:**
- Produces: `admin_client.get_preset_catalog() -> list` (fetch via `_post_guest`, cache, bundled fallback, never raises); `onboarding.get_preset_catalog() -> list` (whitelisted wrapper).

- [ ] **Step 1 (RED): write `jarvis/tests/test_preset_catalog.py`:**
```python
from unittest.mock import patch
from frappe.tests.utils import FrappeTestCase
import frappe
from jarvis import admin_client
from jarvis.exceptions import AdminUnreachableError


class TestGetPresetCatalog(FrappeTestCase):
    def setUp(self):
        frappe.cache().delete_value(admin_client._PRESET_CATALOG_CACHE_KEY)

    def test_fetches_and_caches_admin_catalog(self):
        payload = [{"key": "openai-resilient", "label": "OpenAI — resilient",
                    "kind": "single_vendor", "blurb": "", "enabled": True,
                    "models": [{"provider": "openai", "model": "gpt-5.5", "order": 0}],
                    "vendors": ["openai"]}]
        with patch.object(admin_client, "_post_guest", return_value=payload) as gp:
            out = admin_client.get_preset_catalog()
        self.assertEqual(out, payload)
        gp.assert_called_once()
        self.assertIn("get_preset_catalog", gp.call_args.kwargs.get("path", ""))
        with patch.object(admin_client, "_post_guest",
                          side_effect=AssertionError("must use cache")):
            self.assertEqual(admin_client.get_preset_catalog(), payload)

    def test_falls_back_to_cache_when_admin_unreachable(self):
        cached = [{"key": "cost-saver", "label": "Cost-saver", "kind": "cross_vendor",
                   "blurb": "", "enabled": True, "models": [], "vendors": []}]
        frappe.cache().set_value(admin_client._PRESET_CATALOG_CACHE_KEY, cached,
                                 expires_in_sec=admin_client._PRESET_CATALOG_TTL_S)
        with patch.object(admin_client, "_post_guest",
                          side_effect=AdminUnreachableError("down")):
            self.assertEqual(admin_client.get_preset_catalog(), cached)

    def test_falls_back_to_bundled_when_admin_down_and_cache_empty(self):
        from jarvis._preset_catalog import BUNDLED_PRESET_CATALOG
        with patch.object(admin_client, "_post_guest",
                          side_effect=AdminUnreachableError("down")):
            out = admin_client.get_preset_catalog()
        self.assertEqual(out, BUNDLED_PRESET_CATALOG)
        self.assertTrue(all("key" in e and "models" in e for e in out))

    def test_wrapper_delegates_to_admin_client(self):
        from jarvis import onboarding
        with patch.object(admin_client, "get_preset_catalog",
                          return_value=[{"key": "k"}]) as m:
            self.assertEqual(onboarding.get_preset_catalog(), [{"key": "k"}])
        m.assert_called_once()
```
Run: `bench --site site.jarvis run-tests --module jarvis.tests.test_preset_catalog` → RED (ImportError/AttributeError).

- [ ] **Step 2 (GREEN): create `jarvis/_preset_catalog.py`** with the spec §3 presets (hyphenated keys, NO secrets). Use the same 7 entries and model IDs as Plan 1's `_V1_CATALOG` — copied verbatim as `BUNDLED_PRESET_CATALOG: list[dict]` with the added `enabled: True` and `vendors` fields per entry, e.g.:
```python
"""Bundled fallback for the Aerele LLM preset catalog. Returned only when admin
is unreachable AND the Redis cache is empty, so onboarding never hard-fails
(spec L7). Keys/model IDs MUST match the admin seed (Plan 1). NO secrets."""
from __future__ import annotations

BUNDLED_PRESET_CATALOG: list[dict] = [
    {"key": "openai-resilient", "label": "OpenAI — resilient", "kind": "single_vendor",
     "blurb": "One OpenAI key. Your first model runs every turn; the others are backups if it fails.",
     "enabled": True, "vendors": ["openai"],
     "models": [{"provider": "openai", "model": "gpt-5.5", "order": 0},
                {"provider": "openai", "model": "gpt-5.4", "order": 1},
                {"provider": "openai", "model": "gpt-5.4-mini", "order": 2}]},
    {"key": "anthropic-resilient", "label": "Anthropic — resilient", "kind": "single_vendor",
     "blurb": "One Anthropic key. Your first model runs every turn; the others are backups if it fails.",
     "enabled": True, "vendors": ["anthropic"],
     "models": [{"provider": "anthropic", "model": "claude-opus-4-8", "order": 0},
                {"provider": "anthropic", "model": "claude-sonnet-4-6", "order": 1},
                {"provider": "anthropic", "model": "claude-haiku-4-5", "order": 2}]},
    {"key": "gemini-resilient", "label": "Google (Gemini API) — resilient", "kind": "single_vendor",
     "blurb": "One Gemini API key. Your first model runs every turn; the others are backups if it fails.",
     "enabled": True, "vendors": ["gemini"],
     "models": [{"provider": "gemini", "model": "gemini-2.5-pro", "order": 0},
                {"provider": "gemini", "model": "gemini-3.5-flash", "order": 1},
                {"provider": "gemini", "model": "gemini-3.1-flash-lite", "order": 2}]},
    {"key": "mistral-resilient", "label": "Mistral — resilient", "kind": "single_vendor",
     "blurb": "One Mistral key. Your first model runs every turn; the others are backups if it fails.",
     "enabled": True, "vendors": ["mistral"],
     "models": [{"provider": "mistral", "model": "mistral-large-latest", "order": 0},
                {"provider": "mistral", "model": "mistral-medium-latest", "order": 1},
                {"provider": "mistral", "model": "mistral-small-latest", "order": 2}]},
    {"key": "cost-saver", "label": "Cost-saver", "kind": "cross_vendor",
     "blurb": "Cheapest primary with cross-vendor fallbacks. Needs one key per vendor.",
     "enabled": True, "vendors": ["gemini", "mistral", "openai"],
     "models": [{"provider": "gemini", "model": "gemini-3.1-flash-lite", "order": 0},
                {"provider": "mistral", "model": "mistral-large-latest", "order": 1},
                {"provider": "openai", "model": "gpt-5.4", "order": 2}]},
    {"key": "balanced", "label": "Balanced", "kind": "cross_vendor",
     "blurb": "Balanced quality/cost with cross-vendor fallbacks. Needs one key per vendor.",
     "enabled": True, "vendors": ["anthropic", "gemini"],
     "models": [{"provider": "anthropic", "model": "claude-sonnet-4-6", "order": 0},
                {"provider": "gemini", "model": "gemini-3.5-flash", "order": 1},
                {"provider": "anthropic", "model": "claude-opus-4-8", "order": 2}]},
    {"key": "max-reliability", "label": "Max-reliability", "kind": "cross_vendor",
     "blurb": "Strongest primary with cross-vendor outage resilience. Needs one key per vendor.",
     "enabled": True, "vendors": ["anthropic", "openai", "gemini"],
     "models": [{"provider": "anthropic", "model": "claude-opus-4-8", "order": 0},
                {"provider": "openai", "model": "gpt-5.5", "order": 1},
                {"provider": "gemini", "model": "gemini-2.5-pro", "order": 2}]},
]
```
Add to `jarvis/admin_client.py` (near `get_plans`, reusing `_post_guest` + the `frappe.cache()` pattern):
```python
# Admin-owned preset catalog (spec 3.3). Guest-safe fetch (get_plans pattern),
# cached in per-site Redis, bundled fallback so onboarding never hard-fails.
_PRESET_CATALOG_PATH = "/api/method/jarvis_admin.billing.catalog.get_preset_catalog"
_PRESET_CATALOG_CACHE_KEY = "jarvis:preset_catalog"
_PRESET_CATALOG_TTL_S = 6 * 60 * 60


def get_preset_catalog() -> list:
    """Fetch the enabled Aerele preset catalog from admin (guest-safe), cache it,
    and fall back to the last cached copy then the bundled default so onboarding
    never hard-fails (spec L7). Never raises."""
    from jarvis._preset_catalog import BUNDLED_PRESET_CATALOG
    cache = frappe.cache()
    try:
        catalog = _post_guest(path=_PRESET_CATALOG_PATH, body={})
    except (AdminUnreachableError, AdminAuthError,
            AdminValidationError, AdminRateLimitedError):
        return cache.get_value(_PRESET_CATALOG_CACHE_KEY) or BUNDLED_PRESET_CATALOG
    if isinstance(catalog, dict):
        catalog = catalog.get("data") or catalog.get("catalog") or catalog.get("presets") or []
    if isinstance(catalog, list) and catalog:
        cache.set_value(_PRESET_CATALOG_CACHE_KEY, catalog, expires_in_sec=_PRESET_CATALOG_TTL_S)
        return catalog
    return cache.get_value(_PRESET_CATALOG_CACHE_KEY) or BUNDLED_PRESET_CATALOG
```
Add the whitelisted wrapper to `jarvis/onboarding.py` (mirror `list_plans`):
```python
@frappe.whitelist()
def get_preset_catalog() -> list:
    """Preset catalog for the desk onboarding step + the /ai SPA route.
    Thin wrapper over admin_client (fetch/cache/bundled fallback)."""
    return admin_client.get_preset_catalog()
```
Run: `bench --site site.jarvis run-tests --module jarvis.tests.test_preset_catalog` → GREEN.

- [ ] **Step 3: Commit**
```bash
cd /Users/kavin/frappe/v16/bench-16/apps/jarvis
git add jarvis/_preset_catalog.py jarvis/admin_client.py jarvis/onboarding.py jarvis/tests/test_preset_catalog.py
git commit -m "feat: customer-side preset catalog fetch (cache + bundled fallback)"
```

---

### Task A2 — `save_llm_pool()` writes `models[]` through the unified pipeline (+ preset Select→Data)

**Files:** edit `jarvis/jarvis/doctype/jarvis_settings/jarvis_settings.json`, `jarvis/tests/test_unified_llm_config.py`, `jarvis/onboarding.py`; create `jarvis/tests/test_llm_pool_endpoints.py`.

**Interfaces:**
- Produces: `save_llm_pool(models, preset=None, routing_mode="failover") -> {last_sync_at, last_sync_status, proxy_active}`.

- [ ] **Step 1: Schema fix (preset Select→Data).** In `jarvis_settings.json` change the `preset` field from `Select` (options `\nCost-saver\nBalanced\nMax-reliability`) to a plain `Data` field (so a dynamic catalog key stores without Select validation, spec §3.3). Then update the existing assertion in `test_unified_llm_config.py` (the current `test_settings_has_preset_select_field`):
```python
def test_settings_preset_is_free_form(self):
    self.assertIn("preset", self.settings_fields)
    self.assertEqual(self.settings_fields["preset"].fieldtype, "Data",
                     "preset must be Data (validated against fetched catalog keys, not a Select)")
```
Apply schema: `bench --site site.jarvis migrate`. Run: `bench --site site.jarvis run-tests --module jarvis.tests.test_unified_llm_config` → GREEN.

- [ ] **Step 2 (RED): create `jarvis/tests/test_llm_pool_endpoints.py`** (reuse the existing snapshot helpers):
```python
from unittest.mock import patch
import frappe
from jarvis import onboarding, admin_client
from jarvis.tests.test_unified_llm_config import _RT3SettingsTestCase
from jarvis.tests.test_settings_on_update import _reset_settings

_CATALOG = [{"key": "cost-saver", "label": "Cost-saver", "kind": "cross_vendor",
             "blurb": "", "enabled": True, "vendors": ["openai"], "models": []}]


class TestSaveLlmPool(_RT3SettingsTestCase):
    def setUp(self):
        super().setUp()
        self._clear_models()
        _reset_settings()
        s = frappe.get_single("Jarvis Settings")
        s.db_set("preset", "", update_modified=False)
        s.db_set("routing_mode", "failover", update_modified=False)
        s.db_set("proxy_active", 0, update_modified=False)
        frappe.db.commit()

    def test_two_models_writes_rows_and_routes_to_proxy(self):
        models = [
            {"provider": "openai", "model": "gpt-5.5", "api_key": "sk-a", "base_url": "", "tier": "strong", "order": 0},
            {"provider": "openai", "model": "gpt-5.4", "api_key": "sk-b", "base_url": "", "tier": "strong", "order": 1},
        ]
        pool_calls = []
        with patch("jarvis.admin_client.post_update_llm_pool",
                   side_effect=lambda **kw: pool_calls.append(kw) or {"action": "pool_update"}), \
             patch("jarvis.admin_client.post_update_llm_creds") as creds:
            out = onboarding.save_llm_pool(frappe.as_json(models), preset=None, routing_mode="failover")
        self.assertTrue(pool_calls, "proxy pool path must fire for >=2 models")
        creds.assert_not_called()
        s = frappe.get_single("Jarvis Settings")
        self.assertEqual(len(s.get("models")), 2)
        self.assertEqual(s.models[0].get_password("api_key"), "sk-a")
        self.assertEqual(int(s.proxy_active or 0), 1)
        self.assertEqual(s.routing_mode, "failover")
        self.assertIn("last_sync_status", out)

    def test_one_model_no_preset_is_direct(self):
        models = [{"provider": "openai", "model": "gpt-5.5", "api_key": "sk-x", "base_url": "", "tier": "strong", "order": 0}]
        with patch("jarvis.admin_client.post_update_llm_creds", return_value={"action": "restart"}), \
             patch("jarvis.admin_client.post_update_llm_pool") as pool:
            onboarding.save_llm_pool(frappe.as_json(models))
        pool.assert_not_called()
        s = frappe.get_single("Jarvis Settings")
        self.assertEqual(int(s.proxy_active or 0), 0)

    def test_preset_validated_against_catalog(self):
        models = [{"provider": "openai", "model": "gpt-5.5", "api_key": "sk-x", "base_url": "", "tier": "strong", "order": 0}]
        with patch("jarvis.admin_client.get_preset_catalog", return_value=_CATALOG):
            with self.assertRaises(frappe.ValidationError):
                onboarding.save_llm_pool(frappe.as_json(models), preset="does-not-exist")

    def test_non_failover_routing_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            onboarding.save_llm_pool(frappe.as_json([{"model": "m"}]), routing_mode="dynamic")

    def test_blank_key_surfaces_validation_error_from_pipeline(self):
        models = [
            {"provider": "openai", "model": "gpt-5.5", "api_key": "", "order": 0},
            {"provider": "openai", "model": "gpt-5.4", "api_key": "sk-b", "order": 1},
        ]
        with patch("jarvis.admin_client.post_update_llm_pool") as pool:
            with self.assertRaises(frappe.ValidationError):
                onboarding.save_llm_pool(frappe.as_json(models))
        pool.assert_not_called()  # on_update validate_models throws before enqueue
```
Run: `bench --site site.jarvis run-tests --module jarvis.tests.test_llm_pool_endpoints` → RED (no `save_llm_pool`).

- [ ] **Step 3 (GREEN): add `save_llm_pool` to `jarvis/onboarding.py`** (`import json` already at line 5; let `on_update` do all sync/derivation):
```python
@frappe.whitelist()
def save_llm_pool(models, preset: str | None = None, routing_mode: str = "failover") -> dict:
    """Write the customer's multi-model LLM pool into Jarvis Settings.models[]
    (+ preset, routing_mode) and let the existing on_update pipeline validate
    (validate_models), derive proxy_active, mirror models[0] into legacy llm_*,
    and sync DIRECT (/llm-creds) vs PROXY (/llm-pool) via admin.

    System-Manager-gated. routing_mode is always 'failover' in v1. preset is an
    admin-catalog key or None; validated against the fetched catalog."""
    frappe.only_for("System Manager")
    if isinstance(models, str):
        models = json.loads(models)
    if not isinstance(models, list) or not models:
        raise frappe.ValidationError("models must be a non-empty list")
    if routing_mode != "failover":
        raise frappe.ValidationError("routing_mode must be 'failover' in v1")

    preset = (preset or "").strip()
    if preset:
        keys = {e.get("key") for e in admin_client.get_preset_catalog()}
        if preset not in keys:
            raise frappe.ValidationError(f"unknown preset '{preset}'")

    s = frappe.get_single("Jarvis Settings")
    s.set("models", [])
    for i, m in enumerate(models):
        sub = m.get("subscription")
        cred_type = "subscription" if sub else "api_key"
        row = {
            "provider": (m.get("provider") or "").strip(),
            "model": (m.get("model") or "").strip(),
            "base_url": (m.get("base_url") or "").strip(),
            "tier": m.get("tier") or "strong",
            "order": m.get("order", i),
            "credential_type": cred_type,
            "enabled": 1,
        }
        if cred_type == "api_key":
            row["api_key"] = m.get("api_key") or ""
        else:
            row["rotation"] = (sub or {}).get("rotation") or "sticky"
            row["accounts"] = (sub or {}).get("accounts") or []
        s.append("models", row)

    s.preset = preset
    s.routing_mode = routing_mode
    # save() -> on_update -> _on_update_unified_llm: validate_models (throws),
    # compute_proxy_active, mirror models[0], enqueue pool/creds sync.
    s.save(ignore_permissions=True)
    frappe.db.commit()

    row = frappe.db.get_value("Jarvis Settings", "Jarvis Settings",
                              ["last_sync_at", "last_sync_status"], as_dict=True) or {}
    return {
        "last_sync_at": str(row.get("last_sync_at") or ""),
        "last_sync_status": row.get("last_sync_status") or "",
        "proxy_active": bool(frappe.db.get_single_value("Jarvis Settings", "proxy_active")),
    }
```
Run: `bench --site site.jarvis run-tests --module jarvis.tests.test_llm_pool_endpoints` → GREEN.

- [ ] **Step 4: Commit**
```bash
git add jarvis/jarvis/doctype/jarvis_settings/jarvis_settings.json jarvis/onboarding.py jarvis/tests/test_llm_pool_endpoints.py jarvis/tests/test_unified_llm_config.py
git commit -m "feat: save_llm_pool writes multi-model pool via unified pipeline; preset Select->Data"
```

---

### Task A3 — `get_llm_config()` reads the effective pool (never secrets, never mirrors)

**Files:** edit `jarvis/onboarding.py`; extend `jarvis/tests/test_llm_pool_endpoints.py`.

**Interfaces:**
- Produces: `get_llm_config() -> {models:[{provider,model,base_url,tier,order,enabled,credential_type,has_key}], preset, routing_mode, proxy_active}`.

- [ ] **Step 1 (RED): extend `test_llm_pool_endpoints.py`:**
```python
class TestGetLlmConfig(_RT3SettingsTestCase):
    def setUp(self):
        super().setUp()
        self._clear_models()
        _reset_settings()

    def test_reports_models_preset_routing_and_proxy_without_secrets(self):
        models = [
            {"provider": "openai", "model": "gpt-5.5", "api_key": "sk-a", "order": 0},
            {"provider": "openai", "model": "gpt-5.4", "api_key": "sk-b", "order": 1},
        ]
        with patch("jarvis.admin_client.post_update_llm_pool", return_value={"action": "pool_update"}):
            onboarding.save_llm_pool(frappe.as_json(models), routing_mode="failover")
        cfg = onboarding.get_llm_config()
        self.assertEqual(len(cfg["models"]), 2)
        self.assertEqual(cfg["models"][0]["model"], "gpt-5.5")
        self.assertTrue(cfg["models"][0]["has_key"])
        self.assertNotIn("api_key", cfg["models"][0])
        self.assertNotIn("sk-a", frappe.as_json(cfg))
        self.assertEqual(cfg["routing_mode"], "failover")
        self.assertTrue(cfg["proxy_active"])
```
Run: `bench --site site.jarvis run-tests --module jarvis.tests.test_llm_pool_endpoints` → RED.

- [ ] **Step 2 (GREEN): add `get_llm_config` to `jarvis/onboarding.py`:**
```python
@frappe.whitelist()
def get_llm_config() -> dict:
    """Current effective LLM pool for the desk step + /ai SPA: models[] rows,
    preset, routing_mode, derived proxy_active. Reads models[] (NOT the legacy
    llm_* mirrors). Never returns api_key secrets — only a has_key boolean.
    System-Manager-only (spec 7)."""
    frappe.only_for("System Manager")
    s = frappe.get_single("Jarvis Settings")
    models = []
    for m in (s.get("models") or []):
        cred_type = m.credential_type or "api_key"
        models.append({
            "provider": m.provider or "",
            "model": m.model or "",
            "base_url": m.base_url or "",
            "tier": m.tier or "strong",
            "order": m.order or 0,
            "enabled": bool(m.enabled),
            "credential_type": cred_type,
            "has_key": bool(m.get_password("api_key", raise_exception=False))
                       if cred_type == "api_key" else bool(m.get("accounts")),
        })
    return {
        "models": models,
        "preset": s.get("preset") or "",
        "routing_mode": s.get("routing_mode") or "failover",
        "proxy_active": bool(s.get("proxy_active")),
    }
```
Run: `bench --site site.jarvis run-tests --module jarvis.tests.test_llm_pool_endpoints` → GREEN.

- [ ] **Step 3: Regression sweep:** `bench --site site.jarvis run-tests --module jarvis.tests.test_settings_on_update` and `--module jarvis.tests.test_unified_llm_config` → GREEN (preset Select→Data + new endpoints didn't break the pipeline).

- [ ] **Step 4: Commit**
```bash
git add jarvis/onboarding.py jarvis/tests/test_llm_pool_endpoints.py
git commit -m "feat: get_llm_config reports effective pool (no secrets, reads models[])"
```

---

## Phase B — Onboarding desk step (Quick | Preset | Custom)

> Frontend TDD is limited to the pure logic module (Task B1, `node --test`). Desk-page rendering/wiring is verified manually/e2e (Task B9). Reference: `frontend/src/charts/chartTheme.test.js`.

### Task B1 — Shared pure pool-logic module `frontend/src/llm/pool.js` (TDD, `node:test`)

**Files:** Create `frontend/src/llm/pool.js`, `frontend/src/llm/pool.test.js`.

**Interfaces (the ONE shared API for desk + Vue):**
- `deriveMode(models, preset)` → `"direct"|"proxy"`
- `uniqueVendors(entry)` → `[provider]` (from `entry.vendors`, else derived from models, order-preserving)
- `missingVendorKeys(entry, keysByVendor)` → `[provider]` still needing a key (empty = complete)
- `presetToModels(entry, keysByVendor)` → `models[]` `{provider,model,api_key,order}` (one key per vendor, order preserved)
- `buildCustomModels(rows)` → `models[]` from `{provider,model,apiKey}` rows (order = index)
- `reorder(list, from, to)` → new array (pure move)
- `validatePool(models, preset)` → `{ok, error}`

- [ ] **Step 1 (RED): write `frontend/src/llm/pool.test.js`** (mirror `chartTheme.test.js`):
```js
import { test } from "node:test"
import assert from "node:assert/strict"
import { deriveMode, uniqueVendors, missingVendorKeys, presetToModels, buildCustomModels, reorder, validatePool } from "./pool.js"

const LADDER = { key: "anthropic-resilient", kind: "single_vendor", vendors: ["anthropic"],
  models: [{ provider: "anthropic", model: "claude-opus-4-8", order: 0 },
           { provider: "anthropic", model: "claude-sonnet-4-6", order: 1 }] }
const TRIO = { key: "max-reliability", kind: "cross_vendor", vendors: ["anthropic", "openai", "gemini"],
  models: [{ provider: "anthropic", model: "claude-opus-4-8", order: 0 },
           { provider: "openai", model: "gpt-5.5", order: 1 },
           { provider: "gemini", model: "gemini-2.5-pro", order: 2 }] }

test("deriveMode: 1 model & no preset => direct; else proxy", () => {
  assert.equal(deriveMode([{ provider: "openai", model: "gpt-5.5" }], null), "direct")
  assert.equal(deriveMode([{ provider: "openai", model: "gpt-5.5" }], "cost-saver"), "proxy")
  assert.equal(deriveMode([{}, {}], null), "proxy")
  assert.equal(deriveMode([], null), "direct")
})
test("uniqueVendors: dedup preserving order", () => {
  assert.deepEqual(uniqueVendors(LADDER), ["anthropic"])
  assert.deepEqual(uniqueVendors(TRIO), ["anthropic", "openai", "gemini"])
})
test("missingVendorKeys: all-or-nothing (L8)", () => {
  assert.deepEqual(missingVendorKeys(LADDER, { anthropic: "sk-a" }), [])
  assert.deepEqual(missingVendorKeys(LADDER, { anthropic: "  " }), ["anthropic"])
  assert.deepEqual(missingVendorKeys(TRIO, { anthropic: "a", openai: "o" }), ["gemini"])
})
test("presetToModels: one key reused per vendor, order preserved", () => {
  const models = presetToModels(TRIO, { anthropic: "sk-a", openai: "sk-o", gemini: "sk-g" })
  assert.deepEqual(models.map(m => m.order), [0, 1, 2])
  assert.equal(models[0].api_key, "sk-a")
  assert.equal(models[1].api_key, "sk-o")
  assert.equal(models[0].model, "claude-opus-4-8")
})
test("buildCustomModels: order = row index; trims; drops incomplete rows", () => {
  const rows = [{ provider: "openai", model: "gpt-5.5", apiKey: "sk-o" },
                { provider: "mistral", model: "mistral-large-latest", apiKey: "sk-m" },
                { provider: "", model: "", apiKey: "" }]
  const models = buildCustomModels(rows)
  assert.deepEqual(models.map(m => m.order), [0, 1])
  assert.equal(models[0].api_key, "sk-o")
})
test("reorder: pure move", () => {
  assert.deepEqual(reorder(["a", "b", "c"], 2, 0), ["c", "a", "b"])
})
test("validatePool: rejects empty pool", () => {
  assert.equal(validatePool([], null).ok, false)
  assert.equal(validatePool([{ provider: "openai", model: "gpt-5.5", api_key: "k" }], null).ok, true)
})
```
Run (RED): `cd /Users/kavin/frappe/v16/bench-16/apps/jarvis/frontend && node --test src/llm/pool.test.js`

- [ ] **Step 2 (GREEN): implement `frontend/src/llm/pool.js`** (NO Vue/frappe imports; rows use the CONTRACT shape):
```js
// Shared pure pool logic. Consumed by the Vue app (direct import) AND the desk
// onboarding page (via jarvis_onboarding_llm.bundle.js -> window). No framework imports.
export function deriveMode(models, preset) {
  const n = Array.isArray(models) ? models.length : 0
  return (n <= 1 && !preset) ? "direct" : "proxy"
}
export function uniqueVendors(entry) {
  if (entry && Array.isArray(entry.vendors) && entry.vendors.length) return entry.vendors.slice()
  const seen = new Set(), out = []
  for (const m of (entry?.models || [])) if (!seen.has(m.provider)) { seen.add(m.provider); out.push(m.provider) }
  return out
}
export function missingVendorKeys(entry, keysByVendor) {
  return uniqueVendors(entry).filter(v => !((keysByVendor?.[v]) || "").trim())
}
export function presetToModels(entry, keysByVendor) {
  return (entry?.models || []).slice().sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    .map((m, i) => ({ provider: m.provider, model: m.model, api_key: (keysByVendor?.[m.provider] || "").trim(), order: i }))
}
export function buildCustomModels(rows) {
  return (rows || []).filter(r => r && (r.provider || "").trim() && (r.model || "").trim())
    .map((r, i) => ({ provider: r.provider.trim(), model: r.model.trim(), api_key: (r.apiKey || "").trim(), order: i }))
}
export function reorder(list, from, to) {
  const a = list.slice(); const [x] = a.splice(from, 1); a.splice(to, 0, x); return a
}
export function validatePool(models, preset) {
  if (!Array.isArray(models) || models.length === 0) return { ok: false, error: "Add at least one model." }
  for (const m of models) {
    if (!(m.provider || "").trim() || !(m.model || "").trim()) return { ok: false, error: "Every model needs a provider and a model id." }
    if (!m.subscription && !(m.api_key || "").trim()) return { ok: false, error: `Model ${m.model} needs an API key.` }
  }
  return { ok: true, error: "" }
}
```
Run (GREEN): `node --test src/llm/pool.test.js`

- [ ] **Step 3: Commit**
```bash
cd /Users/kavin/frappe/v16/bench-16/apps/jarvis
git add frontend/src/llm/pool.js frontend/src/llm/pool.test.js
git commit -m "feat(fe): shared pure LLM pool-logic module (TDD)"
```

---

### Task B2 — Expose the shared module to the desk page via a bundle

**Files:** Create `jarvis/public/js/jarvis_onboarding_llm.bundle.js`; edit `jarvis/hooks.py`.

- [ ] **Step 1: Create the bundle** (re-exports the shared module to the global the desk page reads):
```js
import * as llmPool from "../../../frontend/src/llm/pool.js";
window.jarvis_onboarding_llm = llmPool;
```

- [ ] **Step 2: Append to `app_include_js` in `hooks.py`** (currently `["jarvis_immersive.bundle.js", "jarvis_widget.bundle.js"]`):
```python
app_include_js = ["jarvis_immersive.bundle.js", "jarvis_widget.bundle.js", "jarvis_onboarding_llm.bundle.js"]
```

- [ ] **Step 3: Build + verify** (from `/Users/kavin/frappe/v16/bench-16`): `bench build --app jarvis`, then in a desk console: `typeof jarvis_onboarding_llm.presetToModels === "function"` → `true`.

- [ ] **Step 4: Commit**
```bash
git add jarvis/public/js/jarvis_onboarding_llm.bundle.js jarvis/hooks.py
git commit -m "build: expose shared LLM pool module to the desk page"
```

---

### Task B3 — Prefetch preset catalog in `bootRender()`

**File:** `jarvis/jarvis/page/jarvis_onboarding/jarvis_onboarding.js`.

- [ ] **Step 1: Add a module-level cache** near `subscriptionModels` (~L57):
```js
let presetCatalog = [];
```
(No JS bundled copy needed: the backend `get_preset_catalog` already returns the bundled fallback when admin is down, so the frontend only needs to handle a total call failure with an empty list + a friendly message in the Preset tab.)

- [ ] **Step 2: Extend the `Promise.all` in `bootRender()`** with a third, never-hard-failing call:
```js
Promise.all([
  frappe.call({ method: "jarvis.account.is_onboarded" }),
  frappe.call({ method: "jarvis.chat.api.get_chat_ui_settings" }).catch(() => ({ message: {} })),
  frappe.call({ method: "jarvis.onboarding.get_preset_catalog" }).catch(() => ({ message: [] })),
]).then(([onboarded, chatUi, catalog]) => {
  const cui = (chatUi && chatUi.message) || {};
  subscriptionModels = cui.subscription_models || {};
  defaultModels = cui.default_models || {};
  presetCatalog = (catalog && catalog.message) || [];
  // ...existing onboarded / is_ready_for_chat branch unchanged...
});
```

- [ ] **Step 3: Manual check** + Commit
```bash
git add jarvis/jarvis/page/jarvis_onboarding/jarvis_onboarding.js
git commit -m "feat(onboarding): prefetch preset catalog"
```

---

### Task B4 — Quick | Preset | Custom mode selector in `renderLlm()`

**File:** `jarvis/jarvis/page/jarvis_onboarding/jarvis_onboarding.js` (wrap `renderLlm` L424-509).

- [ ] **Step 1: Add mode state** to `state` (L25-46): `llmMode: "quick", selectedPreset: null, presetKeys: {}, customRows: []`.

- [ ] **Step 2: Split `renderLlm()`** into a 3-segment `.jo-tabs` selector (reuse the existing tab component) + dispatch, moving the CURRENT body verbatim into `renderLlmQuick(modeTabs)`:
```js
function renderLlm() {
  const modeTabs = `
    <div class="jo-field">
      <label class="jo-tabs-label">Setup</label>
      <div class="jo-tabs" role="tablist" data-active="${state.llmMode}">
        <span class="jo-tabs-thumb" aria-hidden="true"></span>
        ${["quick","preset","custom"].map(m =>
          `<button type="button" class="jo-tab ${state.llmMode===m?"jo-tab-active":""}" data-llmmode="${m}" role="tab" aria-selected="${state.llmMode===m}"><span>${m[0].toUpperCase()+m.slice(1)}</span></button>`).join("")}
      </div>
    </div>`;
  if (state.llmMode === "preset") return renderLlmPreset(modeTabs);
  if (state.llmMode === "custom") return renderLlmCustom(modeTabs);
  return renderLlmQuick(modeTabs);
}
```
Move the current subscription+api_key body (L443-509) verbatim into `renderLlmQuick(modeTabs)`, injecting `${modeTabs}` above `${authModeHtml}`. Quick keeps calling `saveLlm()` → `jarvis.onboarding.save_llm_creds` unchanged.

- [ ] **Step 3: Wire the mode tabs** (mirror `wireAuthModeTabs`) and call `wireLlmModeTabs()` at the end of each render path:
```js
function wireLlmModeTabs() {
  $body.find(".jo-tab[data-llmmode]").on("click", function () {
    const m = $(this).data("llmmode");
    if (m === state.llmMode) return;
    state.llmMode = m;
    if (m !== "quick") cancelSubscriptionFlow();
    renderLlm();
  });
}
```

- [ ] **Step 4: Manual** (default lands on Quick, existing flows unchanged) + Commit
```bash
git add jarvis/jarvis/page/jarvis_onboarding/jarvis_onboarding.js
git commit -m "feat(onboarding): Quick/Preset/Custom mode selector"
```

---

### Task B5 — Preset cards + progressive per-vendor keys + all-or-nothing save

**File:** `jarvis/jarvis/page/jarvis_onboarding/jarvis_onboarding.js`.

- [ ] **Step 1: `renderLlmPreset(modeTabs)`** — one card per `presetCatalog` entry (group `single_vendor` vs `cross_vendor`), each showing `esc(entry.label)` + `esc(entry.blurb)` + the ladder (models[0] "runs every turn", rest "backups"). Selecting a card sets `state.selectedPreset = entry.key` and re-renders. When selected, render one password field per `jarvis_onboarding_llm.uniqueVendors(entry)` bound to `state.presetKeys[vendor]`; disable Save until `jarvis_onboarding_llm.missingVendorKeys(entry, state.presetKeys).length === 0`. If `presetCatalog` is empty, show "Couldn't load presets — use Quick or Custom."

- [ ] **Step 2: `savePreset()` handler** (reuses the existing async poll pipeline):
```js
function savePreset() {
  const entry = presetCatalog.find(e => e.key === state.selectedPreset);
  if (jarvis_onboarding_llm.missingVendorKeys(entry, state.presetKeys).length) {
    $body.find("#jo-llm-err").text("Presets need every vendor's key. Use Quick or Custom to finish with fewer keys.");
    return;
  }
  const models = jarvis_onboarding_llm.presetToModels(entry, state.presetKeys);
  setBusy("#jo-preset-save", true);
  frappe.call({ method: "jarvis.onboarding.save_llm_pool",
    args: { models: JSON.stringify(models), preset: entry.key, routing_mode: "failover" } })
    .then((r) => {
      const m = r.message || {}; const status = (m.last_sync_status || "").trim();
      if (status.startsWith("pending:")) pollSyncStatus(status);
      else { setBusy("#jo-preset-save", false); renderSuccess(state.successData || {}, status); }
    })
    .catch((e) => { setBusy("#jo-preset-save", false); $body.find("#jo-llm-err").text(e.message || "Couldn't save preset."); });
}
```

- [ ] **Step 3: Commit**
```bash
git add jarvis/jarvis/page/jarvis_onboarding/jarvis_onboarding.js
git commit -m "feat(onboarding): preset cards + progressive keys + all-or-nothing save"
```

---

### Task B6 — Custom failover rows + reorder + save

**File:** `jarvis/jarvis/page/jarvis_onboarding/jarvis_onboarding.js`.

- [ ] **Step 1: `renderLlmCustom(modeTabs)`** — render `state.customRows` (each `{provider, model, apiKey}`), reusing `PROVIDER_DEFAULTS` for the provider `<select>`; "+ Add model" pushes a row; each row has up/down (reorder) + remove buttons; show a live Direct/Proxy badge via `jarvis_onboarding_llm.deriveMode(state.customRows, null)`. Up/down use the helper:
```js
$body.find(".jo-row-up").on("click", function () {
  const i = +$(this).data("i");
  if (i > 0) { state.customRows = jarvis_onboarding_llm.reorder(state.customRows, i, i - 1); renderLlm(); }
});
```

- [ ] **Step 2: `saveCustom()` handler:**
```js
function saveCustom() {
  const models = jarvis_onboarding_llm.buildCustomModels(state.customRows);
  if (!models.length) { $body.find("#jo-llm-err").text("Add at least one model."); return; }
  setBusy("#jo-custom-save", true);
  frappe.call({ method: "jarvis.onboarding.save_llm_pool",
    args: { models: JSON.stringify(models), preset: null, routing_mode: "failover" } })
    .then((r) => {
      const m = r.message || {}; const status = (m.last_sync_status || "").trim();
      if (status.startsWith("pending:")) pollSyncStatus(status);
      else { setBusy("#jo-custom-save", false); renderSuccess(state.successData || {}, status); }
    })
    .catch((e) => { setBusy("#jo-custom-save", false); $body.find("#jo-llm-err").text(e.message || "Couldn't save models."); });
}
```

- [ ] **Step 3: Commit**
```bash
git add jarvis/jarvis/page/jarvis_onboarding/jarvis_onboarding.js
git commit -m "feat(onboarding): custom failover rows + reorder"
```

---

### Task B7 — CSS for the new surfaces (inside `injectStyles()`)

**File:** `jarvis/jarvis/page/jarvis_onboarding/jarvis_onboarding.js` (inside the single `#jo-styles` css template — NOT a new `<style>` tag).

- [ ] **Step 1: Generalize `.jo-tabs-thumb` for 3 segments + add card/row styles:**
```css
.jo-tabs .jo-tabs-thumb{width:calc(33.333% - 4px)}
.jo-tabs[data-active="preset"] .jo-tabs-thumb{transform:translateX(100%)}
.jo-tabs[data-active="custom"] .jo-tabs-thumb{transform:translateX(200%)}
.jo-preset-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.jo-preset-card{border:1.5px solid var(--border-color);border-radius:12px;padding:14px;cursor:pointer}
.jo-preset-card.selected{border-color:var(--jarvis-primary);box-shadow:0 0 0 2px var(--jarvis-primary-faint)}
.jo-custom-row{display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:8px;align-items:center;margin-bottom:8px}
```

- [ ] **Step 2: Commit**
```bash
git add jarvis/jarvis/page/jarvis_onboarding/jarvis_onboarding.js
git commit -m "style(onboarding): preset/custom/mode-selector CSS"
```

---

### Task B8 — Copy rename: "Aerele-managed" → "Aerele-hosted"

**File:** `jarvis/jarvis/page/jarvis_onboarding/jarvis_onboarding.js` (~L198).

- [ ] **Step 1: Change ONLY the display text**, keep `data-mode="managed"` and `state.mode==="managed"`:
```js
// before: <div class="jo-mode-name">Aerele-managed</div>
// after:  <div class="jo-mode-name">Aerele-hosted</div>
```

- [ ] **Step 2: Commit**
```bash
git add jarvis/jarvis/page/jarvis_onboarding/jarvis_onboarding.js
git commit -m "copy(onboarding): rename Aerele-managed -> Aerele-hosted"
```

---

### Task B9 — Manual / e2e verification matrix

- [ ] Reload assets: `cd /Users/kavin/frappe/v16/bench-16 && bench --site site.jarvis clear-cache && bench build --app jarvis`, hard-refresh.
- [ ] Open `/app/jarvis-onboarding` as a System Manager on `site.jarvis`. Drive with the `verify` / `e2e-feature` skill (Playwright / chrome-devtools MCP). Assert:
  - Quick is default; API-key save + Chat-subscription flows unchanged; pending polls to success.
  - Preset tab lists cards from `get_preset_catalog` (still renders with admin down via the backend bundled fallback).
  - single_vendor ladder → ONE key field; cross_vendor trio → one field per unique vendor; Save disabled until all keys present (all-or-nothing).
  - `save_llm_pool` network payload: correct `models[]` (`order` = priority, api_key reused per vendor), `preset` = key, `routing_mode:"failover"`.
  - Custom: add/remove/reorder; save sends `preset:null`, `routing_mode:"failover"`.
  - Mode chooser shows "Aerele-hosted".
- [ ] Final gate: `cd apps/jarvis/frontend && node --test src/llm/pool.test.js`.

---

## Phase C — Vue SPA `/ai` Manage tab

### Task C1 — Extract shared theme palette `src/theme.js` (TDD)

**Files:** Create `frontend/src/theme.js`, `frontend/src/theme.test.js`; edit `frontend/src/views/ChatView.vue`.

**Interfaces:** `export const LIGHT_VARS`, `export const DARK_VARS`, `export function isDark(themePref, prefersDark)`.

- [ ] **Step 1 (RED): `frontend/src/theme.test.js`:**
```js
import { test } from "node:test"
import assert from "node:assert/strict"
import { LIGHT_VARS, DARK_VARS, isDark } from "./theme.js"

test("palettes expose the core vars used across views", () => {
  for (const v of ["--surface", "--border", "--text", "--blue", "--red", "--green", "--amber"])
    assert.ok(LIGHT_VARS[v] && DARK_VARS[v], `${v} present in both`)
})
test("isDark: explicit wins, system follows OS", () => {
  assert.equal(isDark("dark", false), true)
  assert.equal(isDark("light", true), false)
  assert.equal(isDark("system", true), true)
  assert.equal(isDark("system", false), false)
})
```
Run (RED): `cd apps/jarvis/frontend && node --test src/theme.test.js`

- [ ] **Step 2 (GREEN):** create `src/theme.js` by moving the exact `LIGHT_VARS`/`DARK_VARS` objects out of `ChatView.vue` (~L946-964) and adding `export function isDark(pref, prefersDark){ return pref === "dark" || (pref === "system" && prefersDark) }`. In `ChatView.vue`, replace the inline consts with `import { LIGHT_VARS, DARK_VARS } from "@/theme"` (keep `effectiveDark`/`paletteVars`).
Run (GREEN): `node --test src/theme.test.js`; then `npm run build` (exit 0, no regression).

- [ ] **Step 3: Commit**
```bash
cd /Users/kavin/frappe/v16/bench-16/apps/jarvis
git add frontend/src/theme.js frontend/src/theme.test.js frontend/src/views/ChatView.vue
git commit -m "refactor(fe): extract shared theme palette (TDD)"
```

---

### Task C2 — api.js wrappers for the pool endpoints

**Files:** edit `frontend/src/api.js`.

**Interfaces:** `getLlmConfig()`, `getPresetCatalog()`, `getLlmSyncStatus()`, `saveLlmPool(models, preset, routingMode)`.

- [ ] **Step 1: Append to `src/api.js`** (wrapper shape matches `getUsage` at api.js:31; paths are the canonical map):
```js
// --- LLM pool / models config (System-Manager only, gated server-side) ---
export const getLlmConfig = () => call("jarvis.onboarding.get_llm_config")
export const getPresetCatalog = () => call("jarvis.onboarding.get_preset_catalog")
export const getLlmSyncStatus = () => call("jarvis.onboarding.get_llm_sync_status")
export const saveLlmPool = (models, preset = null, routingMode = "failover") =>
  call("jarvis.onboarding.save_llm_pool", {
    models: JSON.stringify(models),
    preset: preset || "",
    routing_mode: routingMode,
  })
```

- [ ] **Step 2: Verify** `npm run build` (exit 0) + Commit
```bash
git add frontend/src/api.js
git commit -m "feat(fe): api.js wrappers for LLM pool config"
```

---

### Task C3 — `/ai` route + System-Manager gate

**Files:** edit `frontend/src/router/index.js`, `jarvis/www/jarvis.py`.

- [ ] **Step 1: Add the boot key** in `www/jarvis.py` (emitted as `window.is_system_manager` by the jarvis.html boot loop):
```python
context.boot = {
    "csrf_token": frappe.sessions.get_csrf_token(),
    "site_name": str(frappe.local.site),
    "default_route": "/jarvis",
    "is_system_manager": "System Manager" in frappe.get_roles(),
}
```
(Preserve any other existing keys in `context.boot`.)

- [ ] **Step 2: Add the route with a guard** in `src/router/index.js`:
```js
{
  path: "/ai",
  name: "AiModels",
  component: () => import("@/views/AiView.vue"),
  beforeEnter: (to, from, next) => { next(window.is_system_manager ? undefined : { name: "Chat" }) },
},
```

- [ ] **Step 3: Verify** `npm run build` (exit 0) + Commit
```bash
git add frontend/src/router/index.js jarvis/www/jarvis.py
git commit -m "feat(fe): /ai route + is_system_manager boot gate"
```

---

### Task C4 — `AiView.vue` — tabbed shell + Manage tab (Monitor tab placeholder)

**Files:** Create `frontend/src/views/AiView.vue`.

**Interfaces:** consumes `@/llm/pool` (Task B1), `@/theme` (Task C1), `@/api` (Task C2). Renders a tab strip **Manage | Monitor**; Manage is the pool editor; **Monitor is a placeholder `<div>` that Plan 3 replaces with `<MonitorTab>`**.

- [ ] **Step 1: Scaffold the view** (own root with palette + a `activeTab` strip; NO frappe-ui components):
```vue
<template>
  <div class="jv-root" :class="{ 'jv-dark': dark }" :style="paletteVars"
       style="--rad:8px;font-family:'Inter',system-ui,sans-serif;min-height:100vh;color:var(--text);background:var(--surface);">
    <header style="height:52px;display:flex;align-items:center;gap:14px;padding:0 18px;border-bottom:1px solid var(--border);">
      <router-link to="/" style="color:var(--text-2);text-decoration:none;font-size:13px;">← Chat</router-link>
      <span style="font-size:14px;font-weight:600;">AI / Models</span>
      <nav style="margin-left:12px;display:flex;gap:4px;">
        <button v-for="t in ['manage','monitor']" :key="t" @click="activeTab=t"
          :style="{fontSize:'13px',padding:'6px 12px',border:'none',cursor:'pointer',background:'transparent',
                   borderBottom: activeTab===t ? '2px solid var(--blue)' : '2px solid transparent',
                   color: activeTab===t ? 'var(--text)' : 'var(--text-3)'}">{{ t[0].toUpperCase()+t.slice(1) }}</button>
      </nav>
      <span :style="{marginLeft:'auto',fontSize:'11px',fontWeight:600,padding:'3px 9px',borderRadius:'20px',
             background: mode==='proxy' ? 'var(--green-bg,#e6f4ea)' : 'var(--surface-2,#f4f4f5)',
             color: mode==='proxy' ? 'var(--green)' : 'var(--text-3)'}">
        {{ mode === 'proxy' ? 'Proxy' : 'Direct' }}<template v-if="cfg.proxy_active"> · active</template>
      </span>
    </header>

    <main v-show="activeTab==='manage'" style="max-width:760px;margin:0 auto;padding:22px 18px;">
      <div v-if="err" style="color:var(--red);font-size:13px;margin-bottom:12px;">{{ err }}</div>
      <section style="background:var(--surface-1,#fafafa);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:18px;">
        <div style="font-size:12px;color:var(--text-3);margin-bottom:8px;">{{ cfg.preset ? presetLabel(cfg.preset) : 'Custom pool' }} · failover</div>
        <div v-for="(m,i) in models" :key="i" style="display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid var(--border);">
          <span style="font-size:13px;font-weight:550;">{{ m.provider }} / {{ m.model }}</span>
          <span style="font-size:11px;color:var(--text-3);">{{ i === 0 ? 'runs every turn' : 'backup' }}</span>
          <div style="margin-left:auto;display:flex;gap:6px;">
            <button @click="move(i,-1)" :disabled="i===0" title="Up">▲</button>
            <button @click="move(i,1)" :disabled="i===models.length-1" title="Down">▼</button>
            <button @click="remove(i)" title="Remove">✕</button>
          </div>
        </div>
      </section>
      <!-- Preset picker (cards from catalog, split by kind) + Custom "+ Add model" row + progressive
           per-vendor key fields (missingVendorKeys) go here; block Save until complete for a preset. -->
      <div style="display:flex;align-items:center;gap:12px;">
        <button @click="save" :disabled="saving" style="padding:8px 16px;background:var(--blue);color:#fff;border:none;border-radius:8px;cursor:pointer;">
          {{ saving ? 'Saving…' : 'Save configuration' }}
        </button>
        <span style="font-size:12px;color:var(--text-3);">{{ syncLabel }}</span>
      </div>
    </main>

    <!-- Monitor tab: Plan 3 replaces this placeholder with <MonitorTab :dark="dark" /> -->
    <main v-show="activeTab==='monitor'" style="max-width:900px;margin:0 auto;padding:22px 18px;">
      <div style="font-size:13px;color:var(--text-3);">Usage monitoring arrives with the monitor build.</div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from "vue"
import * as api from "@/api"
import { LIGHT_VARS, DARK_VARS, isDark } from "@/theme"
import { deriveMode, reorder, presetToModels, missingVendorKeys, validatePool } from "@/llm/pool"

const dark = ref(isDark(localStorage.getItem("jarvis-theme") || "system",
  window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches))
const paletteVars = computed(() => (dark.value ? DARK_VARS : LIGHT_VARS))
const activeTab = ref("manage")

const cfg = ref({ models: [], preset: "", routing_mode: "failover", proxy_active: false })
const catalog = ref([])
const models = ref([])
const err = ref("")
const saving = ref(false)
const sync = ref({ last_sync_status: "", pending: false })
let pollTimer = null

const mode = computed(() => deriveMode(models.value, cfg.value.preset))
const syncLabel = computed(() => sync.value.pending ? "Syncing to your agent…" : (sync.value.last_sync_status || ""))
function presetLabel(key) { return (catalog.value.find((c) => c.key === key) || {}).label || key }
function move(i, d) { models.value = reorder(models.value, i, i + d) }
function remove(i) { models.value = models.value.filter((_, j) => j !== i) }
function _err(e) { return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong." }

async function load() {
  try { cfg.value = (await api.getLlmConfig()) || cfg.value; models.value = (cfg.value.models || []).slice() }
  catch (e) { err.value = _err(e) }
  try { catalog.value = (await api.getPresetCatalog()) || [] } catch (e) { /* backend bundled fallback */ }
}
async function save() {
  const v = validatePool(models.value, cfg.value.preset)
  if (!v.ok) { err.value = v.error; return }
  saving.value = true; err.value = ""
  try { await api.saveLlmPool(models.value, cfg.value.preset || null, "failover"); startPolling(); await load() }
  catch (e) { err.value = _err(e) } finally { saving.value = false }
}
function startPolling() {
  stopPolling()
  pollTimer = setInterval(async () => {
    try { sync.value = await api.getLlmSyncStatus(); if (!sync.value.pending) stopPolling() }
    catch (e) { stopPolling() }
  }, 3000)
}
function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null } }
onMounted(load)
onBeforeUnmount(stopPolling)
</script>
```

- [ ] **Step 2:** Flesh out the preset picker (cards from `catalog.value`, split `kind`), the Custom "+ Add model" row, and progressive per-vendor key fields driven by `missingVendorKeys(entry, keysByVendor)` (block Save until empty — L8). Selecting a preset sets `cfg.value.preset` and `models.value = presetToModels(entry, keysByVendor)`.

- [ ] **Step 3: Verify** `npm run build` (exit 0). Manual/e2e at `/jarvis/ai` as System Manager: current pool shows from `get_llm_config`; add/remove/reorder, pick a preset, enter keys, Save → `save_llm_pool` fires, sync label pending → ok.

- [ ] **Step 4: Commit**
```bash
git add frontend/src/views/AiView.vue
git commit -m "feat(fe): /ai AiView with tabbed shell + Manage tab"
```

---

### Task C5 — Nav entry to `/ai` from the chat user menu

**Files:** edit `frontend/src/views/ChatView.vue`.

- [ ] **Step 1: Add a System-Manager-gated menu item** (in the user-menu dropdown, using the existing `.jv-menuitem` class):
```html
<router-link v-if="isSystemManager" to="/ai" class="jv-menuitem" @click="userMenuOpen = false" style="text-decoration:none;color:inherit;">
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/></svg>
  <span>AI / Models</span>
</router-link>
```

- [ ] **Step 2: Add** `const isSystemManager = !!window.is_system_manager` in `<script setup>` (near the `session` inject).

- [ ] **Step 3: Verify** `npm run build` (exit 0). Manual: item visible only for System Manager; navigates to `/jarvis/ai`.

- [ ] **Step 4: Whole-Phase-C gate + Commit**
```bash
cd apps/jarvis/frontend && node --test && npm run build   # theme + pool suites pass; build ok
cd /Users/kavin/frappe/v16/bench-16/apps/jarvis
git add frontend/src/views/ChatView.vue
git commit -m "feat(fe): AI/Models nav entry (System-Manager only)"
```

---

## Plan 2 Self-Review

- **Spec coverage:** L1/L2/L3 (BYO, failover-only, offer-not-require via unchanged Quick), L4 (preset + custom via cards/rows), L5 (desk + Vue split, shared logic), L8 (all-or-nothing via `missingVendorKeys`), §3.3 (catalog fetch/cache/fallback), §4 (Quick/Preset/Custom), §5.1 (Manage tab), §6.1-6.3 (endpoints), §7 (SM-only), §8 (Aerele-hosted rename). ✅
- **No placeholders:** all steps carry real code; the AiView preset-picker "flesh out" step (C4 Step 2 / B5 Step 1) is a described-but-bounded UI build over already-specified helpers — acceptable at task granularity, verified by the e2e matrix. ✅
- **Interface consistency:** one shared `pool.js` API (`deriveMode`/`uniqueVendors`/`missingVendorKeys`/`presetToModels`/`buildCustomModels`/`reorder`/`validatePool`) used by both desk (via bundle) and Vue; endpoint module map + hyphenated catalog keys consistent with Plan 1; `save_llm_pool` return shape reused by the desk poller and Vue polling. ✅
