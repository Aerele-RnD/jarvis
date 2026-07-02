import { test } from "node:test"
import assert from "node:assert/strict"
import { statusLabel, planPriceLabel, renewalLabel } from "./format.js"

test("statusLabel: maps known states, passes through unknown", () => {
  assert.equal(statusLabel("Active"), "Active")
  assert.equal(statusLabel("Pending Verification"), "Pending verification")
  assert.equal(statusLabel(""), "Unknown")
  assert.equal(statusLabel(null), "Unknown")
})
test("planPriceLabel: free, monthly, annual", () => {
  assert.equal(planPriceLabel(0, "Monthly"), "Free")
  assert.equal(planPriceLabel(100, "Monthly"), "₹100 / mo")
  assert.equal(planPriceLabel(1000, "Annual"), "₹1,000 / yr")
})
test("renewalLabel: renders days remaining; handles empty/zero", () => {
  assert.equal(renewalLabel("2026-08-01 00:00:00", 30), "Renews 2026-08-01 · 30 days left")
  assert.equal(renewalLabel("2026-08-01 00:00:00", 1), "Renews 2026-08-01 · 1 day left")
  assert.equal(renewalLabel("", 0), "No active period")
})
