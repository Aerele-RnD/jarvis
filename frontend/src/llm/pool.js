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
