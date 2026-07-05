# LLM Preset Catalog (Admin) Implementation Plan — Plan 1 of 3

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Aerele-owned LLM preset catalog to `jarvis_admin` — a `Jarvis LLM Preset` doctype (+ child) the Aerele team edits in the admin desk, exposed via a guest-safe endpoint, seeded with the v1 BYO/failover catalog.

**Architecture:** Mirror the existing `Jarvis Plan` doctype + `get_plans` endpoint patterns. The catalog is the source of truth (spec L7); the customer app (Plan 2) fetches it via a guest POST, caches it, and keeps a bundled fallback. This plan ships a self-contained, testable admin feature.

**Tech Stack:** Frappe v16 (Python), FrappeTestCase (unittest), bench CLI.

**This is Plan 1 of 3** for the LLM-Proxy UI feature (spec: `jarvis/docs/superpowers/specs/2026-07-01-jarvis-llm-proxy-ui-design.md`). Plan 2 (customer config + onboarding + Manage UI) consumes this plan's endpoint; Plan 3 (usage monitor) is independent of it. No dependency on Plan 2/3 — build this first.

## Global Constraints

- **Envelope:** endpoints return `{"ok": True, "data": <list>}` exactly like `get_plans` (`billing/signup.py:139-145`). The customer `admin_client` unwraps `message.data`; a different shape breaks Plan 2.
- **Guest reads use `frappe.get_all`** (ignore_permissions, no page cap) — NOT `frappe.get_list` (would return `[]` for a Guest caller). Applies to both the preset query and the child-row query.
- **`order` is a MySQL reserved word.** Never pass `order_by="order asc"`. Fetch child rows and sort in Python by `row["order"]`.
- **Catalog carries NO secrets.** Child doctype has `provider`/`model`/`order` ONLY. Keys are collected from the customer at apply time.
- **Catalog keys are hyphenated slugs**, identical to Plan 2's bundled fallback: `openai-resilient`, `anthropic-resilient`, `gemini-resilient`, `mistral-resilient`, `cost-saver`, `balanced`, `max-reliability`.
- **Module** on both new doctypes = `Jarvis Admin` (jarvis_admin has zero existing `istable` doctypes; the only child exemplar `Jarvis LLM Pool Model` lives in the jarvis app under module `Jarvis` — do not copy its module or its secret fields).
- **Stable endpoint path** (wire contract for Plan 2): `jarvis_admin.billing.catalog.get_preset_catalog`. Do not rename later.
- **Catalog entry shape (exact):** `{ key, label, kind: "single_vendor"|"cross_vendor", blurb, enabled, models:[{provider,model,order}], vendors:[provider,...] }`. `vendors` is derived in the endpoint (distinct providers, order-preserving), not stored.
- **Seed is create-if-absent** (`frappe.db.exists` guard) so it never overwrites later admin-desk edits.
- **Run commands** (from `/Users/kavin/frappe/v16/bench-16`): tests `bench --site jarvis.admin run-tests --app jarvis_admin --module jarvis_admin.tests.test_llm_preset_catalog`; schema/seed apply `bench --site jarvis.admin migrate`.
- **v1 catalog model IDs + order** (order = failover priority; 0 = primary) exactly as in Task 4.

## File Structure

- `jarvis_admin/jarvis_admin/doctype/jarvis_llm_preset_model/{jarvis_llm_preset_model.json,.py,__init__.py}` — child (provider/model/order, no secrets)
- `jarvis_admin/jarvis_admin/doctype/jarvis_llm_preset/{jarvis_llm_preset.json,.py,__init__.py}` — parent (key/label/kind/enabled/blurb/models)
- `jarvis_admin/billing/catalog.py` — `get_preset_catalog()` endpoint + `seed_preset_catalog()` + `_V1_CATALOG`
- `jarvis_admin/patches/v1_13_seed_llm_preset_catalog.py` — seed patch
- `jarvis_admin/patches.txt` — register patch (edit)
- `jarvis_admin/tests/test_llm_preset_catalog.py` — structure + endpoint + seeder tests

All paths below are under `/Users/kavin/frappe/v16/bench-16/apps/jarvis_admin/`.

---

### Task 1: Create the "Jarvis LLM Preset Model" child doctype

**Files:**
- Create: `jarvis_admin/jarvis_admin/doctype/jarvis_llm_preset_model/jarvis_llm_preset_model.json`
- Create: `jarvis_admin/jarvis_admin/doctype/jarvis_llm_preset_model/jarvis_llm_preset_model.py`
- Create: `jarvis_admin/jarvis_admin/doctype/jarvis_llm_preset_model/__init__.py`

**Interfaces:**
- Produces: child doctype `Jarvis LLM Preset Model`, module `Jarvis Admin`, `istable`, fields `provider`/`model`/`order` (no secrets).

- [ ] **Step 1: Write the child JSON** (mirror the jarvis app's `jarvis_llm_pool_model.json` but drop all credential fields):
```json
{
  "doctype": "DocType",
  "name": "Jarvis LLM Preset Model",
  "module": "Jarvis Admin",
  "istable": 1,
  "custom": 0,
  "engine": "InnoDB",
  "field_order": ["provider", "model", "order"],
  "fields": [
    {"fieldname": "provider", "fieldtype": "Data", "label": "Provider", "reqd": 1, "in_list_view": 1, "description": "e.g. openai, anthropic, gemini, mistral"},
    {"fieldname": "model", "fieldtype": "Data", "label": "Model", "reqd": 1, "in_list_view": 1},
    {"fieldname": "order", "fieldtype": "Int", "label": "Order", "default": "0", "in_list_view": 1, "description": "Failover priority; 0 = primary (runs every turn)"}
  ],
  "permissions": []
}
```

- [ ] **Step 2: Write the controller** `jarvis_llm_preset_model.py`:
```python
from frappe.model.document import Document


class JarvisLLMPresetModel(Document):
    pass
```

- [ ] **Step 3: Create empty** `__init__.py`.

- [ ] **Step 4: Commit**
```bash
git add jarvis_admin/jarvis_admin/doctype/jarvis_llm_preset_model
git commit -m "feat(admin): add Jarvis LLM Preset Model child doctype"
```

---

### Task 2: Create the "Jarvis LLM Preset" parent doctype

**Files:**
- Create: `jarvis_admin/jarvis_admin/doctype/jarvis_llm_preset/jarvis_llm_preset.json`
- Create: `jarvis_admin/jarvis_admin/doctype/jarvis_llm_preset/jarvis_llm_preset.py`
- Create: `jarvis_admin/jarvis_admin/doctype/jarvis_llm_preset/__init__.py`

**Interfaces:**
- Consumes: `Jarvis LLM Preset Model` (Task 1) as the `models` Table target.
- Produces: parent doctype `Jarvis LLM Preset`, autoname `field:key` (so `doc.name == key`).

- [ ] **Step 1: Write the parent JSON** (mirror `jarvis_plan.json` autoname + permissions):
```json
{
  "doctype": "DocType",
  "name": "Jarvis LLM Preset",
  "module": "Jarvis Admin",
  "issingle": 0,
  "custom": 0,
  "engine": "InnoDB",
  "autoname": "field:key",
  "field_order": ["key", "label", "kind", "enabled", "blurb", "models"],
  "fields": [
    {"fieldname": "key", "fieldtype": "Data", "label": "Key", "reqd": 1, "unique": 1, "in_list_view": 1, "description": "Stable catalog key, e.g. openai-resilient, cost-saver"},
    {"fieldname": "label", "fieldtype": "Data", "label": "Label", "reqd": 1, "in_list_view": 1, "description": "Customer-facing name, e.g. 'OpenAI — resilient'"},
    {"fieldname": "kind", "fieldtype": "Select", "label": "Kind", "options": "single_vendor\ncross_vendor", "reqd": 1, "in_list_view": 1},
    {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1", "in_list_view": 1, "description": "Only enabled presets are returned by the catalog endpoint"},
    {"fieldname": "blurb", "fieldtype": "Small Text", "label": "Blurb", "description": "Short customer-facing description; no secrets"},
    {"fieldname": "models", "fieldtype": "Table", "label": "Models", "options": "Jarvis LLM Preset Model", "reqd": 1, "description": "Ordered failover ladder; row 0 runs every turn"}
  ],
  "permissions": [
    {"role": "Jarvis Admin", "read": 1, "write": 1, "create": 1, "delete": 1}
  ],
  "sort_field": "modified",
  "sort_order": "DESC",
  "track_changes": 1
}
```

- [ ] **Step 2: Write the controller** `jarvis_llm_preset.py`:
```python
from frappe.model.document import Document


class JarvisLLMPreset(Document):
    pass
```

- [ ] **Step 3: Create empty** `__init__.py`.

- [ ] **Step 4: Sync schema** (from `/Users/kavin/frappe/v16/bench-16`): `bench --site jarvis.admin migrate`
  Expected: migrate completes; `frappe.get_meta("Jarvis LLM Preset")` now resolves.

- [ ] **Step 5: Commit**
```bash
git add jarvis_admin/jarvis_admin/doctype/jarvis_llm_preset
git commit -m "feat(admin): add Jarvis LLM Preset parent doctype"
```

---

### Task 3: Structure tests for both doctypes

**Files:**
- Create: `jarvis_admin/jarvis_admin/tests/test_llm_preset_catalog.py`

**Interfaces:**
- Consumes: the two doctypes from Tasks 1-2 (via `frappe.get_meta`).

- [ ] **Step 1: Write the structure tests** (mirror `tests/test_doctypes_structure.py`):
```python
import frappe
from frappe.tests.utils import FrappeTestCase


class TestJarvisLLMPresetStructure(FrappeTestCase):
    DT = "Jarvis LLM Preset"

    def test_required_fields(self):
        fields = {f.fieldname for f in frappe.get_meta(self.DT).fields}
        for required in ("key", "label", "kind", "enabled", "blurb", "models"):
            self.assertIn(required, fields)

    def test_key_unique_required(self):
        f = next(x for x in frappe.get_meta(self.DT).fields if x.fieldname == "key")
        self.assertTrue(f.reqd)
        self.assertTrue(f.unique)

    def test_kind_options(self):
        f = next(x for x in frappe.get_meta(self.DT).fields if x.fieldname == "kind")
        self.assertEqual(set((f.options or "").split("\n")), {"single_vendor", "cross_vendor"})

    def test_models_is_child_table(self):
        f = next(x for x in frappe.get_meta(self.DT).fields if x.fieldname == "models")
        self.assertEqual(f.fieldtype, "Table")
        self.assertEqual(f.options, "Jarvis LLM Preset Model")


class TestJarvisLLMPresetModelStructure(FrappeTestCase):
    DT = "Jarvis LLM Preset Model"

    def test_is_child_table(self):
        self.assertTrue(frappe.get_meta(self.DT).istable)

    def test_fields_and_no_secrets(self):
        fields = {f.fieldname for f in frappe.get_meta(self.DT).fields}
        for required in ("provider", "model", "order"):
            self.assertIn(required, fields)
        for forbidden in ("api_key", "credential_type", "accounts"):
            self.assertNotIn(forbidden, fields, f"catalog must carry NO secrets: {forbidden}")
```

- [ ] **Step 2: Run** (from `/Users/kavin/frappe/v16/bench-16`): `bench --site jarvis.admin run-tests --app jarvis_admin --module jarvis_admin.tests.test_llm_preset_catalog`
  Expected: PASS (Tasks 1-2 + migrate created the meta).

- [ ] **Step 3: Commit**
```bash
git add jarvis_admin/jarvis_admin/tests/test_llm_preset_catalog.py
git commit -m "test(admin): structure tests for LLM preset doctypes"
```

---

### Task 4: Guest-safe `get_preset_catalog` endpoint + seed data module

**Files:**
- Create: `jarvis_admin/jarvis_admin/billing/catalog.py`

**Interfaces:**
- Produces: `get_preset_catalog() -> {"ok": True, "data": [<catalog entry>]}` (guest-safe); `seed_preset_catalog()` (used by Task 6 patch + Task 7 test); `_V1_CATALOG`.

- [ ] **Step 1: Write `catalog.py`** (endpoint mirrors the `get_plans` envelope; uses `frappe.get_all`):
```python
"""Aerele-owned LLM preset catalog. Source of truth is the `Jarvis LLM Preset`
doctype (edited in the admin desk, revisable without a customer-app deploy).
The guest-safe endpoint returns the ENABLED catalog as JSON for the customer
app to fetch/cache (same pattern as get_plans). NO secrets: model IDs + labels
+ order only; the customer supplies keys at apply time (spec 3.3)."""
import frappe

PRESET_DT = "Jarvis LLM Preset"
PRESET_MODEL_DT = "Jarvis LLM Preset Model"


@frappe.whitelist(allow_guest=True)
def get_preset_catalog() -> dict:
    """Enabled BYO/failover presets for the onboarding + SPA preset picker.

    frappe.get_all ignores user permissions, so a Guest bench call succeeds like
    get_plans without granting Guest read on the doctype. Children are fetched
    separately (get_all does not join child rows).
    """
    presets = frappe.get_all(
        PRESET_DT,
        filters={"enabled": 1},
        fields=["name as key", "label", "kind", "blurb", "enabled"],
        order_by="kind asc, label asc",
    )
    data = []
    for p in presets:
        rows = frappe.get_all(
            PRESET_MODEL_DT,
            filters={"parent": p["key"], "parenttype": PRESET_DT},
            fields=["provider", "model", "order"],
        )
        # 'order' is a MySQL reserved word -> sort in Python, never in order_by.
        rows.sort(key=lambda r: (r.get("order") or 0))
        models = [{"provider": r["provider"], "model": r["model"], "order": r["order"]} for r in rows]
        vendors = list(dict.fromkeys(r["provider"] for r in rows))  # distinct, order-preserving
        data.append({
            "key": p["key"],
            "label": p["label"],
            "kind": p["kind"],
            "blurb": p.get("blurb") or "",
            "enabled": bool(p["enabled"]),
            "models": models,
            "vendors": vendors,
        })
    return {"ok": True, "data": data}


# v1 BYO failover catalog (spec 3.1 + 3.2). order = failover priority; 0 = primary.
# Keys are hyphenated slugs and MUST match the customer app's bundled fallback.
_V1_CATALOG = [
    {"key": "openai-resilient", "label": "OpenAI — resilient", "kind": "single_vendor",
     "blurb": "One OpenAI key. Your first model runs every turn; the others are backups if it fails.",
     "models": [
         {"provider": "openai", "model": "gpt-5.5", "order": 0},
         {"provider": "openai", "model": "gpt-5.4", "order": 1},
         {"provider": "openai", "model": "gpt-5.4-mini", "order": 2},
     ]},
    {"key": "anthropic-resilient", "label": "Anthropic — resilient", "kind": "single_vendor",
     "blurb": "One Anthropic key. Your first model runs every turn; the others are backups if it fails.",
     "models": [
         {"provider": "anthropic", "model": "claude-opus-4-8", "order": 0},
         {"provider": "anthropic", "model": "claude-sonnet-4-6", "order": 1},
         {"provider": "anthropic", "model": "claude-haiku-4-5", "order": 2},
     ]},
    {"key": "gemini-resilient", "label": "Google (Gemini API) — resilient", "kind": "single_vendor",
     "blurb": "One Gemini API key. Your first model runs every turn; the others are backups if it fails.",
     "models": [
         {"provider": "gemini", "model": "gemini-2.5-pro", "order": 0},
         {"provider": "gemini", "model": "gemini-3.5-flash", "order": 1},
         {"provider": "gemini", "model": "gemini-3.1-flash-lite", "order": 2},
     ]},
    {"key": "mistral-resilient", "label": "Mistral — resilient", "kind": "single_vendor",
     "blurb": "One Mistral key. Your first model runs every turn; the others are backups if it fails.",
     "models": [
         {"provider": "mistral", "model": "mistral-large-latest", "order": 0},
         {"provider": "mistral", "model": "mistral-medium-latest", "order": 1},
         {"provider": "mistral", "model": "mistral-small-latest", "order": 2},
     ]},
    {"key": "cost-saver", "label": "Cost-saver", "kind": "cross_vendor",
     "blurb": "Cheapest primary with cross-vendor fallbacks. Needs one key per vendor.",
     "models": [
         {"provider": "gemini", "model": "gemini-3.1-flash-lite", "order": 0},
         {"provider": "mistral", "model": "mistral-large-latest", "order": 1},
         {"provider": "openai", "model": "gpt-5.4", "order": 2},
     ]},
    {"key": "balanced", "label": "Balanced", "kind": "cross_vendor",
     "blurb": "Balanced quality/cost with cross-vendor fallbacks. Needs one key per vendor.",
     "models": [
         {"provider": "anthropic", "model": "claude-sonnet-4-6", "order": 0},
         {"provider": "gemini", "model": "gemini-3.5-flash", "order": 1},
         {"provider": "anthropic", "model": "claude-opus-4-8", "order": 2},
     ]},
    {"key": "max-reliability", "label": "Max-reliability", "kind": "cross_vendor",
     "blurb": "Strongest primary with cross-vendor outage resilience. Needs one key per vendor.",
     "models": [
         {"provider": "anthropic", "model": "claude-opus-4-8", "order": 0},
         {"provider": "openai", "model": "gpt-5.5", "order": 1},
         {"provider": "gemini", "model": "gemini-2.5-pro", "order": 2},
     ]},
]


def seed_preset_catalog():
    """Idempotently create the v1 BYO preset catalog (spec 3). Create-if-absent:
    never overwrites a later admin-desk edit."""
    for entry in _V1_CATALOG:
        if frappe.db.exists(PRESET_DT, entry["key"]):
            continue
        doc = frappe.new_doc(PRESET_DT)
        doc.update({
            "key": entry["key"], "label": entry["label"],
            "kind": entry["kind"], "blurb": entry["blurb"], "enabled": 1,
        })
        for m in entry["models"]:
            doc.append("models", {"provider": m["provider"], "model": m["model"], "order": m["order"]})
        doc.insert(ignore_permissions=True)
```

- [ ] **Step 2: Commit**
```bash
git add jarvis_admin/jarvis_admin/billing/catalog.py
git commit -m "feat(admin): guest-safe get_preset_catalog endpoint + v1 seed data"
```

---

### Task 5: Endpoint tests (guest-safe, enabled-only, derived vendors, order, envelope)

**Files:**
- Modify: `jarvis_admin/jarvis_admin/tests/test_llm_preset_catalog.py`

**Interfaces:**
- Consumes: `catalog.get_preset_catalog` (Task 4).

- [ ] **Step 1: Append the endpoint test class** (guest-call pattern from `tests/api/test_onboarding_endpoints.py`):
```python
from jarvis_admin.billing.catalog import get_preset_catalog


class TestGetPresetCatalogEndpoint(FrappeTestCase):
    def setUp(self):
        for key in ("test-enabled-x", "test-disabled-x"):
            if frappe.db.exists("Jarvis LLM Preset", key):
                frappe.delete_doc("Jarvis LLM Preset", key, force=True, ignore_permissions=True)
        d = frappe.new_doc("Jarvis LLM Preset")
        d.update({"key": "test-enabled-x", "label": "Enabled X", "kind": "cross_vendor",
                  "blurb": "b", "enabled": 1})
        # deliberately out-of-order rows to prove endpoint sorts by `order`
        d.append("models", {"provider": "openai", "model": "gpt-5.4", "order": 1})
        d.append("models", {"provider": "gemini", "model": "gemini-3.1-flash-lite", "order": 0})
        d.append("models", {"provider": "openai", "model": "gpt-5.5", "order": 2})
        d.insert(ignore_permissions=True)
        dd = frappe.new_doc("Jarvis LLM Preset")
        dd.update({"key": "test-disabled-x", "label": "Disabled X", "kind": "single_vendor",
                   "blurb": "b", "enabled": 0})
        dd.append("models", {"provider": "mistral", "model": "mistral-large-latest", "order": 0})
        dd.insert(ignore_permissions=True)
        frappe.db.commit()
        self.addCleanup(frappe.set_user, "Administrator")
        self.addCleanup(frappe.delete_doc, "Jarvis LLM Preset", "test-enabled-x", True, True)
        self.addCleanup(frappe.delete_doc, "Jarvis LLM Preset", "test-disabled-x", True, True)

    def _entry(self, out, key):
        return next(e for e in out["data"] if e["key"] == key)

    def test_envelope_and_guest_safe(self):
        frappe.set_user("Guest")
        out = get_preset_catalog()
        self.assertTrue(out["ok"])
        self.assertIsInstance(out["data"], list)

    def test_only_enabled_returned(self):
        out = get_preset_catalog()
        keys = {e["key"] for e in out["data"]}
        self.assertIn("test-enabled-x", keys)
        self.assertNotIn("test-disabled-x", keys)

    def test_models_sorted_and_vendors_derived(self):
        e = self._entry(get_preset_catalog(), "test-enabled-x")
        self.assertEqual([m["order"] for m in e["models"]], [0, 1, 2])
        self.assertEqual(e["models"][0]["model"], "gemini-3.1-flash-lite")
        self.assertEqual(e["vendors"], ["gemini", "openai"])  # distinct, order-preserving

    def test_entry_shape_no_secrets(self):
        e = self._entry(get_preset_catalog(), "test-enabled-x")
        self.assertEqual(set(e.keys()), {"key", "label", "kind", "blurb", "enabled", "models", "vendors"})
        for m in e["models"]:
            self.assertEqual(set(m.keys()), {"provider", "model", "order"})
```

- [ ] **Step 2: Run:** `bench --site jarvis.admin run-tests --app jarvis_admin --module jarvis_admin.tests.test_llm_preset_catalog`
  Expected: PASS.

- [ ] **Step 3: Commit**
```bash
git add jarvis_admin/jarvis_admin/tests/test_llm_preset_catalog.py
git commit -m "test(admin): get_preset_catalog endpoint behaviour"
```

---

### Task 6: Seed patch + register in patches.txt

**Files:**
- Create: `jarvis_admin/jarvis_admin/patches/v1_13_seed_llm_preset_catalog.py`
- Modify: `jarvis_admin/jarvis_admin/patches.txt`

**Interfaces:**
- Consumes: `catalog.seed_preset_catalog` (Task 4).

- [ ] **Step 1: Write the patch** (mirror `v1_9_bench_oauth_client.py`):
```python
"""Seed the v1 BYO LLM preset catalog (spec 3)."""
from jarvis_admin.billing.catalog import seed_preset_catalog


def execute():
    seed_preset_catalog()
```

- [ ] **Step 2: Append under `[post_model_sync]` in `patches.txt`**, after the last existing patch line (currently `jarvis_admin.patches.v1_12_raise_plan_memory_floor` — confirm the last line before adding):
```
jarvis_admin.patches.v1_13_seed_llm_preset_catalog
```
(If `v1_12...` is not the last patch, append after whatever the current last `[post_model_sync]` entry is, and rename the file's `v1_13_` prefix to the next free number.)

- [ ] **Step 3: Apply:** `bench --site jarvis.admin migrate`
  Expected: patch runs; `frappe.db.exists("Jarvis LLM Preset", "cost-saver")` is truthy.

- [ ] **Step 4: Commit**
```bash
git add jarvis_admin/jarvis_admin/patches/v1_13_seed_llm_preset_catalog.py jarvis_admin/jarvis_admin/patches.txt
git commit -m "feat(admin): seed v1 LLM preset catalog via patch"
```

---

### Task 7: Seeder test (7 presets, correct data, idempotent) + regression

**Files:**
- Modify: `jarvis_admin/jarvis_admin/tests/test_llm_preset_catalog.py`

**Interfaces:**
- Consumes: `catalog.seed_preset_catalog`, `catalog._V1_CATALOG` (Task 4).

- [ ] **Step 1: Append the seeder test class:**
```python
from jarvis_admin.billing.catalog import seed_preset_catalog, _V1_CATALOG


class TestSeedPresetCatalog(FrappeTestCase):
    def test_seed_creates_all_v1_presets(self):
        seed_preset_catalog()
        for entry in _V1_CATALOG:
            self.assertTrue(frappe.db.exists("Jarvis LLM Preset", entry["key"]),
                            f"missing seeded preset: {entry['key']}")
        self.assertEqual(len(_V1_CATALOG), 7)

    def test_seed_is_idempotent(self):
        seed_preset_catalog()
        seed_preset_catalog()  # second run must not duplicate or error
        for entry in _V1_CATALOG:
            rows = frappe.get_all("Jarvis LLM Preset", filters={"key": entry["key"]})
            self.assertEqual(len(rows), 1)

    def test_cost_saver_order_and_models(self):
        seed_preset_catalog()
        doc = frappe.get_doc("Jarvis LLM Preset", "cost-saver")
        ladder = sorted(doc.models, key=lambda m: m.order)
        self.assertEqual([(m.provider, m.model) for m in ladder],
                         [("gemini", "gemini-3.1-flash-lite"),
                          ("mistral", "mistral-large-latest"),
                          ("openai", "gpt-5.4")])
        self.assertEqual(doc.kind, "cross_vendor")
```

- [ ] **Step 2: Full-module run:** `bench --site jarvis.admin run-tests --app jarvis_admin --module jarvis_admin.tests.test_llm_preset_catalog`
  Expected: PASS.

- [ ] **Step 3: App regression run:** `bench --site jarvis.admin run-tests --app jarvis_admin`
  Expected: PASS (no existing tests broken).

- [ ] **Step 4: Commit**
```bash
git add jarvis_admin/jarvis_admin/tests/test_llm_preset_catalog.py
git commit -m "test(admin): seeder correctness + idempotency"
```

---

## Plan 1 Self-Review

- **Spec coverage:** L7 (admin-owned catalog doctype, guest-safe fetch), §3.1/§3.2 (exact v1 model IDs + failover order), §3.3 (no secrets, single source of truth). ✅
- **No placeholders:** all code complete; the only conditional is the patch-number check in Task 6 (a real environment check, not a placeholder). ✅
- **Interface consistency:** endpoint path `jarvis_admin.billing.catalog.get_preset_catalog`, envelope `{"ok",data}`, catalog entry shape, and hyphenated keys are used identically across tasks and match Plan 2's bundled fallback. ✅
