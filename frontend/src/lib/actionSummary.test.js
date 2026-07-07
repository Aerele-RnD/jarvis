// frontend/src/lib/actionSummary.test.js
import { test } from "node:test"
import assert from "node:assert/strict"
import { identifyingFields, changedFields, lineItemSummary, summarize } from "./actionSummary.js"

const createModel = {
  verb: "create", doctype: "Sales Order", title: "Sales Order", titleField: "customer",
  fields: [
    { fieldname: "customer", label: "Customer", value: "Acme Corp", orig: "", changed: false, reqd: 1, fieldtype: "Link" },
    { fieldname: "delivery_date", label: "Delivery Date", value: "2026-08-01", orig: "", changed: false, reqd: 1, fieldtype: "Date" },
    { fieldname: "note", label: "Note", value: "", orig: "", changed: false, reqd: 0, fieldtype: "Small Text" },
  ],
  tables: [{
    fieldname: "items", label: "Items",
    columns: [
      { fieldname: "item_code", label: "Item", fieldtype: "Link" },
      { fieldname: "qty", label: "Qty", fieldtype: "Float" },
      { fieldname: "rate", label: "Rate", fieldtype: "Currency" },
      { fieldname: "amount", label: "Amount", fieldtype: "Currency" },
    ],
    rows: [
      { item_code: "Widget A", qty: 10, rate: 50, amount: 500 },
      { item_code: "Widget B", qty: 5, rate: 120, amount: 600 },
    ],
  }],
  tableMeta: {},
}

test("identifyingFields: title field first, then required, drops empties", () => {
  const rows = identifyingFields(createModel)
  assert.equal(rows[0].fieldname, "customer")
  assert.ok(rows.every((r) => String(r.value).trim() !== ""))
  assert.ok(!rows.some((r) => r.fieldname === "note")) // empty non-required dropped
})

test("changedFields: only changed fields, as from -> to", () => {
  const updateModel = {
    verb: "update", fields: [
      { label: "Status", value: "Closed", orig: "Open", changed: true },
      { label: "Customer", value: "Acme", orig: "Acme", changed: false },
    ], tables: [],
  }
  const rows = changedFields(updateModel)
  assert.deepEqual(rows, [{ label: "Status", from: "Open", to: "Closed" }])
})

test("lineItemSummary: count, compact rows, currency total when an amount column exists", () => {
  const s = lineItemSummary(createModel.tables[0])
  assert.equal(s.count, 2)
  assert.equal(s.total, 1100)
  assert.equal(s.rows.length, 2)
  assert.equal(s.rows[0].cells[0], "Widget A")
})

test("summarize(create): kind=create, has identifying rows and tables", () => {
  const out = summarize(createModel)
  assert.equal(out.kind, "create")
  assert.ok(out.rows.length >= 2)
  assert.equal(out.tables[0].count, 2)
})

test("summarize(update): kind=update, diff rows", () => {
  const out = summarize({ verb: "update", fields: [{ label: "Status", value: "Closed", orig: "Open", changed: true }], tables: [] })
  assert.equal(out.kind, "update")
  assert.deepEqual(out.diff, [{ label: "Status", from: "Open", to: "Closed" }])
})
