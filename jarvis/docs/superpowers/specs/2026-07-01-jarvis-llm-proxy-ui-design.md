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
- **L6 — Monitor honestly.** The monitor view shows only data that exists today
  (status, current pool, sync state, connection/OAuth expiry, *estimated* tokens
  clearly labeled, configured budget ceiling). Real per-model $ cost / request logs /
  failover events are deferred — that data is locked inside each tenant's internal
  Bifrost with no read path (§10).

## 3. v1 preset catalog (BYO, failover)

Failover semantics reminder: `models[0]` handles every turn; the rest are fallbacks on
error/exhaustion (never cost/quality routing). UI guidance everywhere: *"Your first
model runs every turn; the others are backups if it fails."*

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

### 3.3 Catalog as a single source of truth

Fixes the current triplication (library `cost-saver` / doctype `Cost-saver` / SPA none).
One canonical `PRESET_CATALOG` lives in the customer app (proposed
`jarvis/jarvis/llm_config.py`), exposed via a whitelisted `get_preset_catalog()` that:
- the desk onboarding JS consumes,
- the Vue SPA consumes,
- seeds the `Jarvis Settings.preset` Select options.

Each catalog entry: `{ key, label, kind: "single_vendor"|"cross_vendor", blurb,
models: [{provider, model, order}], vendors: [provider,…] }` — **no secrets** (keys are
collected from the user at apply time). The llm-proxy library's `presets()` stays the
future managed-tier concern; we align them when the managed tier is built (§10).

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
- **Completion gate unchanged (L3):** onboarding finishes as soon as ≥1 model validates
  (`is_ready_for_chat`). A preset that needs 3 keys can still be completed with a subset;
  we surface which fallbacks are inactive until their key is added (no hard block).
- **Subscriptions:** Quick only (existing `begin_paste_signin`/`complete_paste_signin`);
  presets are API-key-backed (catalog spec D4). Anthropic-sub stays banned.

## 5. Separate LLM-proxy page (new Vue SPA route)

New route in `frontend/src/router` — proposed `/ai` (label "AI / Models") — with two
tabs (or one scrolling page):

### 5.1 Manage tab (same data as onboarding's step, full editor)
- Current setup summary: mode (Direct / Proxy), preset name or "Custom", the ordered
  model list with a live "runs every turn / backup" indicator, `proxy_active` badge.
- Actions (System-Manager-gated): switch preset, add/remove/reorder models, add/rotate a
  key, connect/disconnect a subscription. All write through `save_llm_pool` /
  `save_llm_creds` / the OAuth methods → the existing `on_update` sync pipeline.
- Post-save: poll `get_llm_sync_status` (already exists) and show pending/ok/failed.

### 5.2 Monitor tab (honest, available-now data only — L6)
- **Status card:** container running/healthy, last health check, uptime (via admin
  `dashboard.get_tenant_detail` / `diagnostics.ping_openclaw`).
- **Active pool:** models, order, routing mode, direct-vs-proxy.
- **Usage (estimated):** token estimate from stored message text (`get_usage`, ~4
  chars/token) rendered with **echarts**, explicitly labeled *"Estimated."*
- **Budget:** configured ceiling (`token_budget_monthly` / rendered Bifrost
  `max_limit_usd`) shown as a limit, **not** spend.
- **Connection:** OAuth/key status + expiry (fleet-agent `/llm-auth-status` via a new
  thin admin wrapper — small backend, §6).
- **Recent activity:** last sync/config state from the customer-side `get_llm_sync_status`
  (exists). A fuller audit trail lives admin-side in Jarvis Tenant Activity Log and is
  deferred (would need an admin wrapper — §10).
- Panels for real $ cost / request logs / failover events render a "Coming soon"
  placeholder, not fake numbers (§10).

## 6. Backend & data contract

Reuse the unified pipeline; add the minimum new surface:

1. **`save_llm_pool(models, preset=None, routing_mode="failover")`** (new whitelisted,
   customer app). Writes `Jarvis Settings.models[]` (+ `preset`, `routing_mode`), saves
   the doctype → existing `on_update` derives `proxy_active` and syncs DIRECT (`/llm-creds`)
   vs PROXY (`/llm-pool`) via `admin_client` → admin `api.tenant` → fleet-agent. Secrets
   travel in the `models[].api_key` fields, encrypted at rest, scrubbed from logs (reuse
   existing serializer hygiene). Validates via existing `validate_models`.
2. **`get_preset_catalog()`** (new whitelisted, read-only) — returns the §3.3 catalog.
3. **`get_llm_config()`** (new whitelisted, read-only) — returns the current effective
   pool (`models[]`, `preset`, `routing_mode`, `proxy_active`) for the SPA/desk to render.
   Must read `models[]`, **not** the legacy `llm_*` mirror fields (those reflect only
   `models[0]`).
4. **`get_llm_usage()`** (new whitelisted, read-only) — the estimated-token summary +
   budget ceiling for the monitor tab. Labeled estimate.
5. **`get_llm_connection_status()`** (new whitelisted, read-only) — thin wrapper over the
   admin/fleet `/llm-auth-status` (auth present, OAuth expiry).
6. **Reused as-is:** `save_llm_creds`, `begin_paste_signin`, `complete_paste_signin`,
   `disconnect`, `get_llm_sync_status`, `is_ready_for_chat`.

The SPA calls these via `frontend/src/api.js` (frappe-ui resources).

## 7. Permissions

- **Config writes** (`save_llm_pool`, key/subscription changes): **System Manager**
  (matches today's `Jarvis Settings` gate; keys are sensitive).
- **Reads** (`get_llm_config`, `get_llm_usage`, status): **System Manager** for v1
  (simplest). Broadening monitor read to all chat users is a later, opt-in decision
  (§11).
- Onboarding gate unchanged.

## 8. Naming

- **Resolve the "Aerele-managed" collision:** today onboarding's hosting choice is
  labeled "Aerele-managed" (= Aerele hosts the *container*). Rename it to
  **"Aerele-hosted"** so "managed" can later mean the Aerele-keys LLM tier without
  colliding. This is a copy change in `jarvis_onboarding.js`.
- **Preset labels** (customer-facing): single-vendor = "<Vendor> — resilient";
  cross-vendor = "Cost-saver" / "Balanced" / "Max-reliability". Confirm marketing (§11).

## 9. Build sequence (informs the plan, not the final plan)

1. **Backend contract first:** `PRESET_CATALOG` + `get_preset_catalog` + `save_llm_pool`
   + `get_llm_config` (unlocks both frontends). TDD.
2. **Onboarding desk step** (Quick/Preset/Custom + progressive keys) over the new
   endpoints.
3. **Vue SPA Manage tab** (reuses the same endpoints).
4. **Monitor endpoints + Vue Monitor tab** (`get_llm_usage`, connection status,
   echarts).
5. **Naming/label fixes**, docs.

## 10. Out of scope / deferred (explicit)

- **Aerele managed tier + central gateway** — Aerele key vault, shared Bifrost, non-
  sidecar routing target, per-tenant metering/billing, zero-key presets. The whole
  "managed" value proposition. Separate spec + backend milestone.
- **Dynamic / tier-adaptive routing** — needs a `complexity_tier` signal (Bifrost auto-
  classify or an openclaw per-turn hint) + the Auto/Fast/Best steering plumbing. Until
  then, everything is failover (L2).
- **Real usage/cost read-back** — per-model token counts, $ spend, spend-remaining,
  request logs, failover-event history. Data lives in each tenant's internal Bifrost
  `logs.db` with no host port / read route; DIRECT tenants have no Bifrost at all. Needs
  a fleet-agent usage route + admin wrapper + storage.
- **Vertex ADC + EU residency** for Google (managed-tier concern).
- **Chat subscriptions in presets** (catalog spec D4 — custom/Quick only).
- **In-chat model steering** (per-conversation Auto/Fast/Best) — separate plan.

## 11. Open questions (for spec review)

1. **Preset model sets/orders (§3):** confirm the single-vendor ladders and the
   cross-vendor trio failover orders. In particular, is single-vendor ladder order
   "best→cheaper" (primary = strongest, degrade under rate-limit) the intended default?
2. **Monitor read permission (§7):** System-Manager-only for v1, or readable by all
   signed-in chat users?
3. **Catalog home (§3.3):** define `PRESET_CATALOG` in the customer app now (proposed),
   or align the llm-proxy library `presets()` as the shared source immediately?
4. **Route/label (§5):** `/ai` ("AI / Models") acceptable, or a different path/name?
5. **Marketing names (§8):** confirm customer-facing preset labels.
6. **Progressive-key partial preset (§4):** OK to let a customer finish onboarding with a
   preset only partially keyed (inactive fallbacks surfaced), or require all vendor keys
   before a cross-vendor preset can be saved?
