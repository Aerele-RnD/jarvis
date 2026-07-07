// Shared pure pool logic. Consumed by the Vue app (direct import) AND the desk
// onboarding page (via jarvis_onboarding_llm.bundle.js -> window). No framework imports.
export function deriveMode(models, preset) {
  const list = Array.isArray(models) ? models : []
  // A chat-subscription model needs the cliproxy sidecar, which only the proxy
  // path provisions — so even a single subscription is "proxy". (#200 review #1)
  const hasSubscription = list.some(
    (m) => m && (m.subscription || m.credentialType === "subscription" || m.credential_type === "subscription"),
  )
  if (hasSubscription) return "proxy"
  return (list.length <= 1 && !preset) ? "direct" : "proxy"
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
    .map((r, i) => {
      const m = { provider: r.provider.trim(), model: r.model.trim(), api_key: (r.apiKey || "").trim(), order: i }
      if (r.hasKey) m.has_key = true
      const b = (r.baseUrl || "").trim()
      if (b) m.base_url = b
      return m
    })
}
export function reorder(list, from, to) {
  const a = list.slice(); const [x] = a.splice(from, 1); a.splice(to, 0, x); return a
}
// Suggested chat-subscription model ids per upstream (index 0 = the default the
// onboarding editor uses when it hides the model field). Single source of truth,
// shared with LlmPoolEditor's datalist so the default + suggestions can't drift.
export const SUB_MODEL_SUGGESTIONS = { openai: ["gpt-5.5", "gpt-5.4"], google: ["gemini-2.5-pro", "gemini-3.5-flash"] }
// Default chat-subscription model for an upstream (SUB_MODEL_SUGGESTIONS[0], with
// an openai fallback for unmapped upstreams). Onboarding hides the model field
// (provider is enough), so the row still needs a model id for validatePool + save.
// Pure + exported for unit tests.
export function defaultSubscriptionModel(upstream) {
  return (SUB_MODEL_SUGGESTIONS[upstream] || SUB_MODEL_SUGGESTIONS.openai)[0]
}
export function validatePool(models, preset) {
  if (!Array.isArray(models) || models.length === 0) return { ok: false, error: "Add at least one model." }
  for (const m of models) {
    // Chat-subscription model: needs a model id + at least one connected account
    // (an account with a non-empty oauth_blob). No provider / api_key required.
    if (m.subscription) {
      if (!(m.model || "").trim()) return { ok: false, error: "Every model needs a model id." }
      const accounts = Array.isArray(m.subscription.accounts) ? m.subscription.accounts : []
      // Connected = a freshly-captured blob this session OR a previously-connected
      // account (has an account_ref; its stored blob is merged back on save, so the
      // user need not re-connect to edit an existing pool).
      const connected = accounts.some(a => a && ((a.oauth_blob || "").trim() || (a.account_ref || "").trim()))
      if (!connected) return { ok: false, error: `Model ${m.model} needs at least one connected account.` }
      continue
    }
    // API-key model.
    if (!(m.provider || "").trim() || !(m.model || "").trim()) return { ok: false, error: "Every model needs a provider and a model id." }
    // A freshly-entered key OR a previously-saved key (has_key; merged back on save).
    if (!(m.api_key || "").trim() && !m.has_key) return { ok: false, error: `Model ${m.model} needs an API key.` }
  }
  return { ok: true, error: "" }
}

// ---- provider id <-> label ------------------------------------------------
// Ports jarvis_account.js's PROVIDER_LABEL_BY_ID / providerLabel() verbatim
// (same ids, same labels) so the dropdown in the shared editor matches the
// desk page exactly. Stored pools may carry either the provider *id* (e.g.
// "openai_compat" from presets / admin normalization) or the dropdown
// *label* ("OpenAI-Compatible") directly - providerLabel() maps id -> label
// and passes an already-a-label (or unknown) value through unchanged.
export const PROVIDER_LABELS = [
  { id: "anthropic", label: "Anthropic" },
  { id: "openai", label: "OpenAI" },
  { id: "gemini", label: "Google Gemini" },
  { id: "mistral", label: "Mistral" },
  { id: "groq", label: "Groq" },
  { id: "together", label: "Together AI" },
  { id: "deepseek", label: "DeepSeek" },
  { id: "moonshot", label: "Moonshot (Kimi)" },
  { id: "openrouter", label: "OpenRouter" },
  { id: "ollama", label: "Ollama (local)" },
  { id: "vllm", label: "vLLM (local)" },
  { id: "openai_compat", label: "OpenAI-Compatible" },
]
const _LABEL_BY_ID = Object.fromEntries(PROVIDER_LABELS.map(p => [p.id, p.label]))
const _ID_BY_LABEL = Object.fromEntries(PROVIDER_LABELS.map(p => [p.label, p.id]))
export function providerLabel(id) { return _LABEL_BY_ID[id] || id || "" }
export function providerId(label) { return _ID_BY_LABEL[label] || label || "" }

// ---- config -> editor rows -------------------------------------------------
// Ports jarvis_account.js's seedLlmSetupFromConfig() into a pure function that
// turns a jarvis.onboarding.get_llm_config payload into the shared editor's
// row shape. get_llm_config never returns secrets - api-key rows carry
// `has_key` (bool) instead of the key itself, and subscription rows carry
// `accounts`/`rotation` flat on the model entry (credential_type distinguishes
// the two), NOT a nested `subscription` object with an `api_key` string.
// Both shapes are accepted here (credential_type/has_key from the real
// payload, subscription/api_key from the plain object shape) so this stays a
// faithful mirror of the desk regardless of which shape a caller passes.
export function seedRowsFromConfig(cfg) {
  const models = (cfg && Array.isArray(cfg.models)) ? cfg.models : []
  return models.slice().sort((a, b) => (a.order ?? 0) - (b.order ?? 0)).map((m, i) => {
    const sub = m.subscription || null
    const isSubscription = m.credential_type === "subscription" || !!sub
    if (isSubscription) {
      const rotation = (sub && sub.rotation) || m.rotation || "sticky"
      const rawAccounts = (sub && sub.accounts) || m.accounts || []
      const accounts = rawAccounts.map(a => ({
        upstream: a.upstream, account_ref: a.account_ref, label: a.label, connected: true,
      }))
      return { provider: "", model: m.model || "", apiKey: "", hasKey: !!m.has_key, baseUrl: "",
        credentialType: "subscription", rotation, accounts, order: i }
    }
    return { provider: providerLabel(m.provider), model: m.model || "",
      apiKey: "", hasKey: !!(m.has_key || m.api_key), baseUrl: m.base_url || "",
      credentialType: "api_key", rotation: "sticky", accounts: [], order: i }
  })
}
