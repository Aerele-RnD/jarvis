// frontend/src/lib/actionSummary.js
// Pure display helpers for the summary-first confirmation card. No Vue, no DOM.

const AMOUNT_COLS = new Set(["amount", "net_amount", "base_amount", "total"])

export function identifyingFields(model, limit = 6) {
  const nonEmpty = (f) => String(f.value ?? "").trim() !== ""
  const seen = new Set()
  const picked = []
  const push = (f) => { if (f && nonEmpty(f) && !seen.has(f.fieldname)) { seen.add(f.fieldname); picked.push(f) } }
  push(model.fields.find((f) => f.fieldname === model.titleField))
  model.fields.filter((f) => f.reqd).forEach(push)
  model.fields.forEach(push) // fill remaining non-empty up to limit
  return picked.slice(0, limit).map((f) => ({ fieldname: f.fieldname, label: f.label, value: f.value }))
}

export function changedFields(model) {
  return model.fields
    .filter((f) => f.changed)
    .map((f) => ({ label: f.label, from: f.orig ?? "", to: f.value ?? "" }))
}

export function lineItemSummary(table) {
  // Prefer a named amount column; else fall back to the first Currency column
  // (which may be a unit rate - the total is display-only, not authoritative).
  const amountCol = table.columns.find((c) => AMOUNT_COLS.has(c.fieldname)) || table.columns.find((c) => c.fieldtype === "Currency")
  const total = amountCol
    ? table.rows.reduce((s, r) => s + (Number(r[amountCol.fieldname]) || 0), 0)
    : null
  return {
    fieldname: table.fieldname,
    label: table.label,
    count: table.rows.length,
    columns: table.columns.map((c) => c.label),
    rows: table.rows.map((r) => ({ cells: table.columns.map((c) => r[c.fieldname] ?? "") })),
    total,
  }
}

export function summarize(model) {
  const tables = (model.tables || []).map(lineItemSummary)
  if (model.verb === "update") {
    return { kind: "update", diff: changedFields(model), rows: [], tables }
  }
  return { kind: "create", rows: identifyingFields(model), diff: [], tables }
}
