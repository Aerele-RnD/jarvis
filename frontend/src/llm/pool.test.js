import { test } from "node:test"
import assert from "node:assert/strict"
import { deriveMode, uniqueVendors, missingVendorKeys, presetToModels, buildCustomModels, reorder, validatePool } from "./pool.js"
import { PROVIDER_LABELS, providerLabel, providerId, seedRowsFromConfig } from "./pool.js"
import { defaultSubscriptionModel } from "./pool.js"

test("defaultSubscriptionModel: per-upstream default, openai fallback", () => {
  assert.equal(defaultSubscriptionModel("openai"), "gpt-5.5")
  assert.equal(defaultSubscriptionModel("google"), "gemini-2.5-pro")
  assert.equal(defaultSubscriptionModel("unknown"), "gpt-5.5")
  assert.equal(defaultSubscriptionModel(undefined), "gpt-5.5")
})

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
test("deriveMode: a single subscription model is proxy (needs cliproxy)", () => {
  assert.equal(deriveMode([{ model: "gpt-5.5", credentialType: "subscription" }], null), "proxy")
  assert.equal(deriveMode([{ model: "gpt-5.5", subscription: { accounts: [] } }], null), "proxy")
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
test("buildCustomModels: emits base_url when present, omits when blank", () => {
  const rows = [{ provider: "openai_compat", model: "qwen2.5:3b", apiKey: "ollama", baseUrl: "http://host.docker.internal:11434/v1" },
                { provider: "openai", model: "gpt-5.5", apiKey: "sk-o" }]
  const models = buildCustomModels(rows)
  assert.equal(models[0].base_url, "http://host.docker.internal:11434/v1")
  assert.equal("base_url" in models[1], false)
})
test("reorder: pure move", () => {
  assert.deepEqual(reorder(["a", "b", "c"], 2, 0), ["c", "a", "b"])
})
test("validatePool: rejects empty pool", () => {
  assert.equal(validatePool([], null).ok, false)
  assert.equal(validatePool([{ provider: "openai", model: "gpt-5.5", api_key: "k" }], null).ok, true)
})
test("validatePool: subscription model valid with a connected account (no provider/api_key)", () => {
  const sub = { model: "gpt-5.5", order: 0, subscription: { rotation: "sticky",
    accounts: [{ upstream: "openai", account_ref: "SUB_abc123", label: "me@x.com", oauth_blob: '{"token":"t"}' }] } }
  assert.equal(validatePool([sub], null).ok, true)
})
test("validatePool: subscription model invalid with no accounts", () => {
  const sub = { model: "gpt-5.5", order: 0, subscription: { rotation: "sticky", accounts: [] } }
  assert.equal(validatePool([sub], null).ok, false)
})
test("validatePool: subscription account with account_ref but blank blob is valid (previously connected; blob merged back on save)", () => {
  const sub = { model: "gpt-5.5", order: 0, subscription: { rotation: "sticky",
    accounts: [{ upstream: "openai", account_ref: "SUB_abc123", label: "me@x.com", oauth_blob: "" }] } }
  assert.equal(validatePool([sub], null).ok, true)
})
test("validatePool: subscription account with neither blob nor account_ref is invalid (never connected)", () => {
  const sub = { model: "gpt-5.5", order: 0, subscription: { rotation: "sticky",
    accounts: [{ upstream: "openai", account_ref: "", label: "", oauth_blob: "" }] } }
  assert.equal(validatePool([sub], null).ok, false)
})
test("validatePool: api_key model with blank key but has_key is valid (key preserved on save)", () => {
  assert.equal(validatePool([{ provider: "openai", model: "gpt-5.5", api_key: "", has_key: true }], null).ok, true)
})
test("validatePool: api_key model with neither key nor has_key is invalid", () => {
  assert.equal(validatePool([{ provider: "openai", model: "gpt-5.5", api_key: "" }], null).ok, false)
})

test("providerLabel/providerId: id⇄label round-trip for openai_compat", () => {
  assert.equal(providerLabel("openai_compat"), "OpenAI-Compatible")
  assert.equal(providerId("OpenAI-Compatible"), "openai_compat")
  // unknown id passes through unchanged (no crash)
  assert.equal(providerLabel("weird"), "weird")
})
test("providerLabel/providerId: gemini id ⇄ Google Gemini label (matches catalog id, not legacy 'google')", () => {
  assert.equal(providerLabel("gemini"), "Google Gemini")
  assert.equal(providerId("Google Gemini"), "gemini")
})
test("PROVIDER_LABELS: includes the vendors + compat, each {id,label}", () => {
  const ids = PROVIDER_LABELS.map(p => p.id)
  assert.ok(ids.includes("openai"))
  assert.ok(ids.includes("anthropic"))
  assert.ok(ids.includes("openai_compat"))
  assert.ok(PROVIDER_LABELS.every(p => p.id && p.label))
})
test("seedRowsFromConfig: api-key model → api_key row with label provider + hasKey", () => {
  const cfg = { models: [{ provider: "openai_compat", model: "claude-sonnet-4-6", api_key: "set", base_url: "http://h:9000/openai", order: 0 }] }
  const [row] = seedRowsFromConfig(cfg)
  assert.equal(row.credentialType, "api_key")
  assert.equal(row.provider, "OpenAI-Compatible")
  assert.equal(row.model, "claude-sonnet-4-6")
  assert.equal(row.baseUrl, "http://h:9000/openai")
  assert.equal(row.apiKey, "")      // keys never returned to client
  assert.equal(row.hasKey, true)    // but we know one is set → placeholder
})
test("seedRowsFromConfig: subscription model → subscription row with connected accounts", () => {
  const cfg = { models: [{ model: "gpt-5.5", order: 1, subscription: { rotation: "sticky",
    accounts: [{ upstream: "openai", account_ref: "SUB_x", label: "me@x" }] } }] }
  const [row] = seedRowsFromConfig(cfg)
  assert.equal(row.credentialType, "subscription")
  assert.equal(row.rotation, "sticky")
  assert.equal(row.accounts.length, 1)
  assert.equal(row.accounts[0].connected, true)
  assert.equal(row.accounts[0].account_ref, "SUB_x")
})
test("seedRowsFromConfig: empty/absent → empty array", () => {
  assert.deepEqual(seedRowsFromConfig(null), [])
  assert.deepEqual(seedRowsFromConfig({ models: [] }), [])
})

// ---- real jarvis.onboarding.get_llm_config shape (credential_type/has_key,
// flat rotation+accounts - NOT the fixture's nested `subscription` object) --
test("seedRowsFromConfig: real get_llm_config shape - api_key model", () => {
  const cfg = { models: [{ provider: "openai", model: "gpt-4o", credential_type: "api_key",
    has_key: true, base_url: "", order: 0 }] }
  const [row] = seedRowsFromConfig(cfg)
  assert.equal(row.credentialType, "api_key")
  assert.equal(row.provider, "OpenAI")
  assert.equal(row.model, "gpt-4o")
  assert.equal(row.apiKey, "")
  assert.equal(row.hasKey, true)
})
test("seedRowsFromConfig: real get_llm_config shape - subscription model (flat rotation+accounts)", () => {
  const cfg = { models: [{ model: "gpt-5.5", credential_type: "subscription", rotation: "sticky",
    accounts: [{ upstream: "openai", account_ref: "SUB_x", label: "me@x" }], order: 1 }] }
  const [row] = seedRowsFromConfig(cfg)
  assert.equal(row.credentialType, "subscription")
  assert.equal(row.rotation, "sticky")
  assert.equal(row.accounts.length, 1)
  assert.equal(row.accounts[0].connected, true)
  assert.equal(row.accounts[0].account_ref, "SUB_x")
})
