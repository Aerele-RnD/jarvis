// frontend/src/lib/actionSummary.test.js
import { test } from "node:test"
import assert from "node:assert/strict"
import { proposedFields, changedFields, lineItemSummary, summarize } from "./actionSummary.js"

const createAction = {
  kind: "doc", verb: "create", doctype: "Sales Order", summary: "Sales Order - Acme, 2 items, total 1,100",
  fields: [
    { label: "Customer", value: "Acme Corp" },
    { label: "Delivery Date", value: "2026-08-01" },
    { label: "Note", value: "" },
  ],
  tables: [{ fieldname: "items", rows: [{ item_code: "Widget A" }, { item_code: "Widget B" }] }],
}
const createModel = {
  verb: "create", doctype: "Sales Order",
  fields: [
    { fieldname: "customer", label: "Customer", value: "Acme Corp", orig: "", changed: false },
    { fieldname: "delivery_date", label: "Delivery Date", value: "2026-08-01", orig: "", changed: false },
  ],
  tables: [{
    fieldname: "items", label: "Items",
    columns: [
      { fieldname: "item_code", label: "Item", fieldtype: "Link" },
      { fieldname: "qty", label: "Qty", fieldtype: "Float" },
      { fieldname: "rate", label: "Rate", fieldtype: "Currency" },
    ],
    rows: [{ item_code: "Widget A", qty: 10, rate: 50 }, { item_code: "Widget B", qty: 5, rate: 120 }],
  }],
}

test("proposedFields: the fields the model set, non-empty, as label -> value", () => {
  const rows = proposedFields(createAction)
  assert.deepEqual(rows, [
    { label: "Customer", value: "Acme Corp" },
    { label: "Delivery Date", value: "2026-08-01" },
  ]) // empty Note dropped, no schema-driven ranking
})

test("proposedFields: empty or missing fields array yields empty list", () => {
  assert.deepEqual(proposedFields({}), [])
  assert.deepEqual(proposedFields({ fields: [] }), [])
})

test("changedFields: only changed fields, as from -> to (update diff, unchanged)", () => {
  const rows = changedFields({ verb: "update", fields: [
    { label: "Status", value: "Closed", orig: "Open", changed: true },
    { label: "Customer", value: "Acme", orig: "Acme", changed: false },
  ] })
  assert.deepEqual(rows, [{ label: "Status", from: "Open", to: "Closed" }])
})

test("lineItemSummary: count + compact rows + column labels, and NO total field", () => {
  const s = lineItemSummary(createModel.tables[0])
  assert.equal(s.count, 2)
  assert.equal(s.rows.length, 2)
  assert.equal(s.rows[0].cells[0], "Widget A")
  assert.deepEqual(s.columns, ["Item", "Qty", "Rate"])
  assert.ok(!("total" in s)) // no code-computed total any more
})

test("lineItemSummary: missing cell values render as empty string", () => {
  const s = lineItemSummary({
    fieldname: "items", label: "Items",
    columns: [{ fieldname: "item_code", label: "Item", fieldtype: "Link" }, { fieldname: "qty", label: "Qty", fieldtype: "Float" }],
    rows: [{ item_code: "Widget A" }],
  })
  assert.equal(s.rows[0].cells[1], "")
})

test("summarize(create): kind=create, headline from action.summary, rows from proposed fields", () => {
  const out = summarize(createModel, createAction)
  assert.equal(out.kind, "create")
  assert.equal(out.headline, "Sales Order - Acme, 2 items, total 1,100")
  assert.deepEqual(out.rows, [
    { label: "Customer", value: "Acme Corp" },
    { label: "Delivery Date", value: "2026-08-01" },
  ])
  assert.equal(out.tables[0].count, 2)
  assert.ok(!("total" in out.tables[0]))
})

test("summarize(create): headline is empty string when the model provides no summary", () => {
  const out = summarize(createModel, { ...createAction, summary: undefined })
  assert.equal(out.headline, "")
  assert.ok(out.rows.length >= 1) // proposed fields still render (graceful default)
})

test("summarize(update): kind=update, mechanical diff, headline optional", () => {
  const out = summarize(
    { verb: "update", fields: [{ label: "Status", value: "Closed", orig: "Open", changed: true }], tables: [] },
    { verb: "update", doctype: "Sales Order", fields: [], summary: "Closing SO-0001" },
  )
  assert.equal(out.kind, "update")
  assert.equal(out.headline, "Closing SO-0001")
  assert.deepEqual(out.diff, [{ label: "Status", from: "Open", to: "Closed" }])
})
