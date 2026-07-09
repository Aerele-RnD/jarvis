import { test } from "node:test"
import assert from "node:assert/strict"
import { statusLabel, planPriceLabel, renewalLabel, inr, planAmount, planSuffix } from "./format.js"

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
test("inr: localizes amounts, coerces junk to 0", () => {
  assert.equal(inr(0), "₹0")
  assert.equal(inr(3999), "₹3,999")
  assert.equal(inr(150000), "₹1,50,000")
  assert.equal(inr(null), "₹0")
  assert.equal(inr("abc"), "₹0")
})
test("planAmount: Free for zero/negative, INR amount otherwise", () => {
  assert.equal(planAmount(0), "Free")
  assert.equal(planAmount(-5), "Free")
  assert.equal(planAmount(null), "Free")
  assert.equal(planAmount(100), "₹100")
  assert.equal(planAmount(3999), "₹3,999")
})
test("planSuffix: empty for free, /yr for annual, /mo otherwise", () => {
  assert.equal(planSuffix(0, "Monthly"), "")
  assert.equal(planSuffix(0, "Annual"), "")
  assert.equal(planSuffix(100, "Monthly"), "/mo")
  assert.equal(planSuffix(100, ""), "/mo")
  assert.equal(planSuffix(1000, "Annual"), "/yr")
  assert.equal(planSuffix(1000, "annual"), "/yr")
})
test("renewalLabel: renders days remaining; handles empty/zero", () => {
  assert.equal(renewalLabel("2026-08-01 00:00:00", 30), "Renews 2026-08-01 · 30 days left")
  assert.equal(renewalLabel("2026-08-01 00:00:00", 1), "Renews 2026-08-01 · 1 day left")
  assert.equal(renewalLabel("", 0), "No active period")
})
test("renewalLabel: expired/past-due (<= 0 days) shows Expired, not negative days", () => {
  assert.equal(renewalLabel("2026-06-01 00:00:00", -12), "Expired 2026-06-01")
  assert.equal(renewalLabel("2026-06-01 00:00:00", 0), "Expired 2026-06-01")
})
