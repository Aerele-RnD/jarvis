# Jarvis LLM-Proxy UI/UX — Design

**Date:** 2026-07-01
**Status:** Design (brainstorm-approved; awaiting spec review)
**Scope:** The customer-facing UI for configuring the Jarvis LLM setup — integrated
into onboarding, and a separate manage/monitor page for after onboarding. This is the
"customer/onboarding UI for preset selection" that the preset-catalog spec explicitly
defers (§9). It covers the **BYO (bring-your-own-key) tier only**; the Aerele-hosted
"managed" tier and its central gateway are out of scope (see §10).

Related (different repos — referenced by name, not linked):
- `llm-proxy` repo → `docs/superpowers/specs/2026-07-01-jarvis-preset-catalog-design.md`
  — the preset *catalog* (models/tiers/routing). **This spec is its downstream UI companion.**
- `jarvis_admin` repo → `docs/superpowers/` unified LLM-config design — the
  `Jarvis Settings.models[]` source-of-truth and the direct-vs-proxy derivation this UI
  writes into.

---

## 1. Context & goal

Jarvis customers configure which LLM(s) their agent uses. Today the only customer
surface is a single-model "connect one AI" step in the Frappe desk onboarding page
(`jarvis_onboarding.js` → `save_llm_creds`), plus admin-only doctype grids. There is
no customer surface to build a **multi-model pool** (failover), pick a **preset**, or
**monitor** the setup. This spec designs those surfaces.

Two moments, one underlying data model (`Jarvis Settings.models[]`):

1. **Onboarding** — offer an LLM setup while connecting, but keep the fast path fast.
2. **Reconfigure + monitor later** — a dedicated page a customer returns to when they
   want failover/cost changes or want to see status/usage.

**Key architectural fact that shapes everything:** in the unified config there is no
"enable proxy" toggle. The per-tenant Bifrost proxy is **derived** — 1 model → DIRECT
(no proxy), ≥2 models or a preset → PROXY (per-tenant Bifrost sidecar). So
"configuring the LLM proxy" *is* "configuring your models/preset"; both surfaces edit
the same `models[]` and let the existing `Jarvis Settings.on_update` pipeline sync it.

## 2. Locked decisions (from brainstorm)

- **L1 — BYO keys, v1.** Presets are quick-start *templates* the customer supplies
  their own keys for — **not** zero-key Aerele-hosted hosting. No central gateway is
  built or assumed here.
- **L2 — Failover-only routing, v1.** All pools (presets and custom) use
  `routing_mode="failover"`. The catalog spec's `dynamic` presets are re-expressed as
  failover because nothing in the stack sets `complexity_tier` yet — dynamic routing
  would silently collapse to one tier (catalog spec §7). `models[0]` serves every turn;
  lower-priority models take over only when a higher one errors/exhausts. Tier-adaptive
  dynamic routing is a later upgrade (§10).
- **L3 — Onboarding offers, does not require.** The onboarding completion gate stays
  "one working model" (`is_ready_for_chat`). Preset/custom pools are optional there.
- **L4 — Two preset shapes** (both failover, both BYO):
  - **Single-vendor ladders** — one key, a failover ladder *within* one vendor. Low
    friction; protects against per-model rate-limit blips, not a whole-vendor outage.
    The easy default.
  - **Cross-vendor trio** (Cost-saver / Balanced / Max-reliability) — the catalog
    spec's presets, needing a key per vendor. True outage resilience; "advanced".
- **L5 — Placement.** Onboarding stays the **Frappe desk** page (extend
  `jarvis_onboarding.js`); the separate manage/monitor surface is a **new Vue SPA
  route** (the chat app: Vue 3 + frappe-ui + echarts). The two frontends share the
  **backend contract + preset catalog**, not a literal component.
- **L6 — Monitor: admin-only, minimal, real Bifrost data.** The monitor view is
  **System-Manager-only** and shows a **curated/abstracted subset of real metrics read
  from the tenant's own Bifrost** (usage, cost, per-model tokens) — not an estimate. This
  requires a minimal read-back path (fleet-agent → admin → client, §6). Constraint: only
  **PROXY** tenants have a Bifrost; a single-model **DIRECT** tenant shows status/config
  only (no usage panel). Full request logs / failover-event history stay deferred (§10).
- **L7 — Catalog lives in admin; custom lives in jarvis.** The curated preset catalog is
  **Aerele-owned in `jarvis_admin`** (a `Jarvis LLM Preset` doctype the Aerele team edits
  in the admin desk — revisable without a customer-app deploy), fetched by the customer
  app over the existing customer→admin channel, **cached with a bundled fallback** so
  onboarding never hard-fails. Custom pools are the customer's own
  `Jarvis Settings.models[]`, stored in **jarvis** (unchanged).
- **L8 — Presets are all-or-nothing.** Choosing a preset requires **all** of that
  preset's vendor keys (a preset is a complete package; no half-configured pools). The
  escape hatch to finish onboarding with fewer keys is **Quick** (one model) or
  **Custom** (any models you have keys for). A single-vendor ladder needs only one key,
  so "all keys" = one key there.

## 3. v1 preset catalog (BYO, failover)

Failover semantics reminder: `models[0]` handles every turn; the rest are fallbacks on
error/exhaustion (never cost/quality routing). UI guidance everywhere: *"Your first
model runs every turn; the others are backups if it fails."*

**Order = failover priority (resolved §11.1).** For single-vendor ladders the primary is
the vendor's **strongest agentic model**; fallbacks degrade to cheaper/faster models — so
you keep top quality and only drop a tier if the primary is rate-limited/erroring.

Model IDs below are the catalog spec's verified current IDs. **Data residency for BYO is
the customer's own responsibility** (their keys/accounts); the catalog spec's D2
residency-clean constraint applies to the future *managed* tier, not BYO.

### 3.1 Single-vendor ladders (one key each — the easy default)

| Ladder (label) | Provider | Failover order (primary → fallbacks) | Key type |
|---|---|---|---|
| OpenAI — resilient | `openai` | `gpt-5.5` → `gpt-5.4` → `gpt-5.4-mini` | API key (bearer) |
| Anthropic — resilient | `anthropic` | `claude-opus-4-8` → `claude-sonnet-4-6` → `claude-haiku-4-5` | API key (bearer) |
| Google (Gemini API) — resilient | `gemini` | `gemini-2.5-pro` → `gemini-3.5-flash` → `gemini-3.1-flash-lite` | API key (bearer) |
| Mistral — resilient | `mistral` | `mistral-large-latest` → `mistral-medium-latest` → `mistral-small-latest` | API key (bearer) |

Note: BYO Google uses the **Gemini API** bearer key (simple paste), **not** Vertex ADC.
Vertex (GCP ADC + EU residency) is reserved for the future managed tier (§10).

### 3.2 Cross-vendor trio (advanced — one key per vendor)

Catalog spec's presets, re-expressed as failover with the primary reflecting the tier:

| Preset | Failover order (primary → fallbacks) | Vendors (keys needed) |
|---|---|---|
| **Cost-saver** | `gemini-3.1-flash-lite` → `mistral-large-latest` → `gpt-5.4` | Google + Mistral + OpenAI |
| **Balanced** | `claude-sonnet-4-6` → `gemini-3.5-flash` → `claude-opus-4-8` | Anthropic + Google |
| **Max-reliability** | `claude-opus-4-8` → `gpt-5.5` → `gemini-2.5-pro` | Anthropic + OpenAI + Google |

(Model *sets* are the catalog spec's; only the routing mode and explicit order are v1
adaptations. To be confirmed in review — see §11.)

### 3.3 Catalog source of truth: admin-owned, client-cached (L7)

Fixes the current triplication (library `cost-saver` / doctype `Cost-saver` / SPA none)
by making the catalog **Aerele-owned in `jarvis_admin`**:

- **Admin (source):** a `Jarvis LLM Preset` doctype (+ a `Jarvis LLM Preset Model` child)
  the Aerele team edits in the admin desk. Fields per preset: `key`, `label`, `kind`
  (`single_vendor` | `cross_vendor`), `blurb`, `enabled`, and ordered child rows
  `{provider, model, order}`. **No secrets** — the catalog is model IDs + labels + order
  only; keys are collected from the customer at apply time. Aerele can revise the catalog
  without a customer-app deploy.
- **Admin API:** a whitelisted `billing`/catalog endpoint (guest-safe, same pattern as
  `get_plans`) returns the enabled catalog as JSON.
- **Customer app (client):** `admin_client.get_preset_catalog()` fetches it, **caches**
  the result, and **falls back to a bundled default copy** if admin is unreachable so
  onboarding never hard-fails. The desk onboarding JS and the Vue SPA both read this via a
  thin customer-side `get_preset_catalog()` whitelisted wrapper. The
  `Jarvis Settings.preset` Select is validated against the fetched catalog keys, not a
  hardcoded list.
- **Custom pools** are **not** in the catalog — they are the customer's own
  `Jarvis Settings.models[]`, stored in jarvis (unchanged).

The llm-proxy library's `presets()` stays the future managed-tier concern; we align it
with the admin catalog when the managed tier is built (§10).

## 4. Onboarding integration (Frappe desk — extend `jarvis_onboarding.js`)

Replace the current single-mode LLM step (`renderLlm`) with a **mode selector** that
defaults to Quick:

```
Connect your AI                                    [ Quick ]  Preset   Custom
──────────────────────────────────────────────────────────────────────────
QUICK (default)   ○ API key      ○ Chat subscription
                  → paste key / OAuth connect            → save_llm_creds  (unchanged)

PRESET            [ single-vendor ladders … ]  [ advanced: Cost-saver | Balanced | … ]
                  → pick a card → progressive key entry (one field per unique vendor)
                  → save_llm_pool(models, preset, routing_mode="failover")

CUSTOM (failover) + Add model  (provider ▾  model  key)   [drag to set priority]
                  → save_llm_pool(models, preset=None, routing_mode="failover")
```

- **Progressive key entry:** picking a preset reveals exactly the key fields its unique
  vendors need (one per vendor; the same key is reused across that vendor's models). A
  single-vendor ladder → one field.
- **Presets are all-or-nothing (L8):** to *save a preset*, **all** its vendor keys must be
  present and validate — no partially-keyed pools. A customer who can't supply every key
  uses **Quick** (one model) or **Custom** (any subset they have keys for) to finish.
- **Completion gate (L3):** onboarding finishes as soon as ≥1 working model exists
  (`is_ready_for_chat`) — reachable via Quick/Custom even if the customer skips presets.
- **Subscriptions:** Quick only (existing `begin_paste_signin`/`complete_paste_signin`);
  presets are API-key-backed (catalog spec D4). Anthropic-sub stays banned.

## 5. Separate LLM-proxy page (new Vue SPA route)

New route in `frontend/src/router` — proposed `/ai` (label "AI / Models") — with two
tabs (or one scrolling page):

The whole `/ai` page is **System-Manager-only** (L6/§7).

### 5.1 Manage tab (same data as onboarding's step, full editor)
- Current setup summary: mode (Direct / Proxy), preset name or "Custom", the ordered
  model list with a live "runs every turn / backup" indicator, `proxy_active` badge.
- Actions: switch preset, add/remove/reorder models, add/rotate a key,
  connect/disconnect a subscription. All write through `save_llm_pool` / `save_llm_creds`
  / the OAuth methods → the existing `on_update` sync pipeline.
- Post-save: poll `get_llm_sync_status` (already exists) and show pending/ok/failed.

### 5.2 Monitor tab (admin-only, minimal real Bifrost metrics — L6)
Real, abstracted metrics read from the **tenant's own Bifrost** (not an estimate), via
the read-back path in §6. **Only shown for PROXY tenants** — a DIRECT (single-model)
tenant has no Bifrost, so it shows the status/pool cards only with a "usage available on
multi-model (proxy) setups" note.
- **Status card:** container running/healthy, last health check, uptime (admin
  `dashboard.get_tenant_detail` / `diagnostics.ping_openclaw`).
- **Active pool:** models, failover order, routing mode, direct-vs-proxy.
- **Usage (real, abstracted):** total tokens (in/out) and $ cost **for the current
  period**, plus a **per-model** breakdown — read from Bifrost's usage/governance data
  and curated down to the few relevant numbers. Rendered with **echarts**.
- **Budget:** configured ceiling (`token_budget_monthly` / Bifrost `max_limit_usd`) shown
  against consumption as a used/limit gauge.
- **Connection:** OAuth/key status + expiry (fleet-agent `/llm-auth-status` via a thin
  admin wrapper — §6).
- **Recent activity:** last sync/config state from `get_llm_sync_status` (exists).
- Deferred panels (full request-log stream, failover-event history) render a "Coming
  soon" placeholder, not fake data (§10).

## 6. Backend & data contract

Reuse the unified pipeline; add the minimum new surface:

1. **`save_llm_pool(models, preset=None, routing_mode="failover")`** (new whitelisted,
   customer app). Writes `Jarvis Settings.models[]` (+ `preset`, `routing_mode`), saves
   the doctype → existing `on_update` derives `proxy_active` and syncs DIRECT (`/llm-creds`)
   vs PROXY (`/llm-pool`) via `admin_client` → admin `api.tenant` → fleet-agent. Secrets
   travel in the `models[].api_key` fields, encrypted at rest, scrubbed from logs (reuse
   existing serializer hygiene). Validates via existing `validate_models`.
2. **Preset catalog (admin-owned, L7/§3.3):**
   - Admin: `Jarvis LLM Preset` doctype (+ child) → a whitelisted admin endpoint returns
     the enabled catalog JSON (guest-safe, `get_plans` pattern).
   - Customer app: `admin_client.get_preset_catalog()` (fetch + cache + bundled fallback)
     behind a thin whitelisted `get_preset_catalog()` the desk/SPA call.
3. **`get_llm_config()`** (new whitelisted, read-only) — returns the current effective
   pool (`models[]`, `preset`, `routing_mode`, `proxy_active`) for the SPA/desk to render.
   Must read `models[]`, **not** the legacy `llm_*` mirror fields (those reflect only
   `models[0]`).
4. **`get_llm_usage()`** (new whitelisted, read-only) — **real Bifrost metrics read-back**
   for the monitor tab (L6). New chain: fleet-agent `GET /v1/containers/{name}/llm-usage`
   queries the tenant's Bifrost usage/governance API on the internal network and returns
   curated JSON (period tokens in/out, $ cost, per-model breakdown, used-vs-limit) →
   admin `api.tenant.get_llm_usage` wrapper → customer `get_llm_usage`. Returns an empty/
   "not applicable" shape for DIRECT tenants (no Bifrost). No new persistent storage in
   v1 — read live from Bifrost.
5. **`get_llm_connection_status()`** (new whitelisted, read-only) — thin wrapper over the
   admin/fleet `/llm-auth-status` (auth present, OAuth expiry).
6. **Reused as-is:** `save_llm_creds`, `begin_paste_signin`, `complete_paste_signin`,
   `disconnect`, `get_llm_sync_status`, `is_ready_for_chat`.

The SPA calls these via `frontend/src/api.js` (frappe-ui resources). All monitor/usage
reads and all config writes are System-Manager-gated (§7).

## 7. Permissions

- **Config writes** (`save_llm_pool`, key/subscription changes): **System Manager**
  (matches today's `Jarvis Settings` gate; keys are sensitive).
- **Reads / monitor** (`get_llm_config`, `get_llm_usage`, status, the whole `/ai` page):
  **System-Manager-only** (resolved §11.2 — usage/cost is sensitive; not exposed to
  ordinary chat users in v1).
- Onboarding gate unchanged.

## 8. Naming

- **Resolve the "Aerele-managed" collision:** today onboarding's hosting choice is
  labeled "Aerele-managed" (= Aerele hosts the *container*). Rename it to
  **"Aerele-hosted"** so "managed" can later mean the Aerele-keys LLM tier without
  colliding. This is a copy change in `jarvis_onboarding.js`.
- **Preset labels** (customer-facing): single-vendor = "<Vendor> — resilient";
  cross-vendor = "Cost-saver" / "Balanced" / "Max-reliability". Confirm marketing (§11).

## 9. Build sequence (informs the plan, not the final plan)

1. **Admin catalog:** `Jarvis LLM Preset` doctype + child + catalog endpoint + seed the
   §3 presets. TDD.
2. **Customer backend contract:** `get_preset_catalog` (admin_client fetch/cache/fallback)
   + `save_llm_pool` + `get_llm_config` (unlocks both frontends). TDD.
3. **Onboarding desk step** (Quick/Preset/Custom + progressive keys, all-or-nothing preset)
   over the new endpoints.
4. **Vue SPA Manage tab** (reuses the same endpoints).
5. **Bifrost usage read-back:** fleet-agent `/llm-usage` route → admin wrapper →
   `get_llm_usage` + `get_llm_connection_status`. TDD.
6. **Vue Monitor tab** (echarts over the real metrics; DIRECT-tenant fallback).
7. **Naming/label fixes**, docs.

## 10. Out of scope / deferred (explicit)

- **Aerele managed tier + central gateway** — Aerele key vault, shared Bifrost, non-
  sidecar routing target, per-tenant metering/billing, zero-key presets. The whole
  "managed" value proposition. Separate spec + backend milestone.
- **Dynamic / tier-adaptive routing** — needs a `complexity_tier` signal (Bifrost auto-
  classify or an openclaw per-turn hint) + the Auto/Fast/Best steering plumbing. Until
  then, everything is failover (L2).
- **Full request-log stream + failover-event history** — the raw per-request log feed and
  a history of which model served/failed each turn. (v1 **does** build a minimal read-back
  for curated usage/cost/per-model tokens — §5.2/§6.4; only the deep log stream and event
  history are deferred, plus any persistent usage storage — v1 reads Bifrost live.)
- **Vertex ADC + EU residency** for Google (managed-tier concern).
- **Chat subscriptions in presets** (catalog spec D4 — custom/Quick only).
- **In-chat model steering** (per-conversation Auto/Fast/Best) — separate plan.

## 11. Open questions

**Resolved in review (2026-07-01):**
1. **Preset order (§3)** → order = failover priority; single-vendor ladders are
   best→cheaper (primary = strongest, degrade under rate-limit). ✅
2. **Monitor read permission (§7)** → System-Manager-only. ✅
3. **Catalog home (§3.3)** → Aerele-owned `Jarvis LLM Preset` doctype in admin, client
   fetches/caches with a bundled fallback; custom pools stay in jarvis. ✅
6. **Partial preset (§4)** → all-or-nothing; a preset needs all its vendor keys, else use
   Quick/Custom (L8). ✅

**Still defaulted (not blocking — will use these unless you say otherwise):**
4. **Route/label (§5):** `/ai` ("AI / Models"). Change if you prefer another name.
5. **Marketing names (§8):** single-vendor = "<Vendor> — resilient"; cross-vendor =
   "Cost-saver" / "Balanced" / "Max-reliability".
7. **Bifrost read-back mechanics (§6.4):** two things get pinned during the read-back task
   (a small spike): (a) the exact Bifrost usage/governance endpoint + fields to read, and
   (b) **how the host-side fleet-agent reaches the internal-only Bifrost** (`docker exec`
   + localhost curl vs container bridge IP vs a loopback publish — the Bifrost UI needed a
   temp socat forwarder in prior spikes). The spec fixes the *contract we expose*, not
   Bifrost's internal API surface.
