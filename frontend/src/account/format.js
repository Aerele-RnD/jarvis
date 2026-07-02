// Pure display helpers for the account/billing section. No Vue, no I/O — unit-tested.
const STATUS_LABELS = {
  Active: "Active",
  "Pending Verification": "Pending verification",
  Cancelled: "Cancelled",
  Expired: "Expired",
}
export function statusLabel(status) {
  if (!status) return "Unknown"
  return STATUS_LABELS[status] || status
}
export function planPriceLabel(priceInr, billingCycle) {
  const n = Number(priceInr) || 0
  if (n <= 0) return "Free"
  const per = (billingCycle || "").toLowerCase() === "annual" ? "yr" : "mo"
  return `₹${n.toLocaleString("en-IN")} / ${per}`
}
export function renewalLabel(currentPeriodEnd, daysRemaining) {
  const end = (currentPeriodEnd || "").trim()
  if (!end) return "No active period"
  const date = end.split(" ")[0]
  const d = Number(daysRemaining) || 0
  return `Renews ${date} · ${d} day${d === 1 ? "" : "s"} left`
}
