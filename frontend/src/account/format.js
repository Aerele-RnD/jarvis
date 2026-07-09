// Pure display helpers for the account/billing section. No Vue, no I/O - unit-tested.
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
// Shared INR formatter - the single place amounts get localized.
export function inr(n) {
  return `₹${(Number(n) || 0).toLocaleString("en-IN")}`
}
// Big price line on a plan card: "₹3,999" for paid plans, "Free" otherwise.
export function planAmount(priceInr) {
  const n = Number(priceInr) || 0
  return n > 0 ? inr(n) : "Free"
}
// Small muted per-cycle suffix next to the amount: "/yr" for annual, "/mo"
// for everything else, "" for free plans.
export function planSuffix(priceInr, billingCycle) {
  const n = Number(priceInr) || 0
  if (n <= 0) return ""
  return (billingCycle || "").toLowerCase() === "annual" ? "/yr" : "/mo"
}
export function planPriceLabel(priceInr, billingCycle) {
  const suffix = planSuffix(priceInr, billingCycle)
  if (!suffix) return "Free"
  return `${planAmount(priceInr)} / ${suffix.slice(1)}`
}
export function renewalLabel(currentPeriodEnd, daysRemaining) {
  const end = (currentPeriodEnd || "").trim()
  if (!end) return "No active period"
  const date = end.split(" ")[0]
  const d = Number(daysRemaining) || 0
  // A past-due / expired subscription reports 0 or negative days; don't render a
  // nonsensical "Renews <past date> · -12 days left". #200 review #11.
  if (d <= 0) return `Expired ${date}`
  return `Renews ${date} · ${d} day${d === 1 ? "" : "s"} left`
}
