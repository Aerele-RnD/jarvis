import { test } from "node:test"
import assert from "node:assert/strict"
import { budgetGaugeOption, perModelBarSpec } from "./usageCharts.js"
import { buildOption } from "./chartTheme.js"

test("gauge: null when no positive limit", () => {
  assert.equal(budgetGaugeOption(5, 0), null)
  assert.equal(budgetGaugeOption(5, -1), null)
})
test("gauge: percent, caps at 100, red at >=90%", () => {
  const o = budgetGaugeOption(45, 100)
  assert.equal(o.series[0].type, "gauge")
  assert.equal(o.series[0].data[0].value, 45)
  const over = budgetGaugeOption(150, 100)
  assert.equal(over.series[0].data[0].value, 100)
  assert.equal(over.series[0].progress.itemStyle.color, "#fc8181")
})
test("perModelBarSpec: chartTheme-renderable bar spec", () => {
  const s = perModelBarSpec([{ model: "gpt-5.5", tokens: 10, cost: 0.2 }], "tokens")
  assert.equal(s.type, "bar")
  assert.deepEqual(s.x, ["gpt-5.5"])
  assert.deepEqual(s.series[0].data, [10])
  assert.notEqual(buildOption(s), null)
  const cost = perModelBarSpec([{ model: "m", tokens: 10, cost: 0.2 }], "cost")
  assert.deepEqual(cost.series[0].data, [0.2])
})
