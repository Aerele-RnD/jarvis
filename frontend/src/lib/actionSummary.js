// frontend/src/lib/actionSummary.js
// Pure display helpers for the summary-first confirmation card. No Vue, no DOM.
// Summarization is MODEL-DRIVEN: the card renders the fields the model proposed and
// an optional model-written headline. It imposes no opinion on which fields matter
// or what to total - that is the model's job, since it knows the doctype.

export function proposedFields(action) {
  return (action.fields || [])
    .filter((f) => String(f.value ?? "").trim() !== "")
    .map((f) => ({ label: f.label, value: f.value }))
}

export function changedFields(model) {
  return model.fields
    .filter((f) => f.changed)
    .map((f) => ({ label: f.label, from: f.orig ?? "", to: f.value ?? "" }))
}

export function lineItemSummary(table) {
  return {
    fieldname: table.fieldname,
    label: table.label,
    count: table.rows.length,
    columns: table.columns.map((c) => c.label),
    rows: table.rows.map((r) => ({ cells: table.columns.map((c) => r[c.fieldname] ?? "") })),
  }
}

export function summarize(model, action = {}) {
  const headline = String(action.summary ?? "").trim()
  const tables = (model.tables || []).filter((t) => (t.rows || []).length).map(lineItemSummary)
  if (model.verb === "update") {
    return { kind: "update", headline, diff: changedFields(model), tables }
  }
  return { kind: "create", headline, rows: proposedFields(action), tables }
}
