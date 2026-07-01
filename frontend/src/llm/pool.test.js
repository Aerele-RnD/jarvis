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
