// Pure display helpers for the account/billing section. No Vue, no I/O - unit-tested.
const STATUS_LABELS = {
	Active: "Active",
	"Pending Verification": "Pending verification",
	Cancelled: "Cancelled",
	Expired: "Expired",
};
export function statusLabel(status, cancelAtPeriodEnd) {
	// A plan scheduled to end still reports status "Active" server-side (the
	// customer keeps full access until the period ends), so "Active" would be
	// technically true and practically misleading. Say what is happening.
	if (cancelAtPeriodEnd) return "Cancelling";
	if (!status) return "Unknown";
	return STATUS_LABELS[status] || status;
}
// Pill colour for a subscription status. Lives here (not inline in the pane)
// so the cancelling branch is unit-tested like its siblings.
export function pillTone(status, cancelAtPeriodEnd) {
	if (cancelAtPeriodEnd) return "jv-pill-warn";
	if (status === "Active") return "jv-pill-ok";
	if (
		status === "Cancelled" ||
		status === "Past Due" ||
		status === "Pending Payment" ||
		status === "Pending Verification"
	)
		return "jv-pill-warn";
	if (status === "Expired") return "jv-pill-bad";
	return "jv-pill-muted";
}
// The cancel button's label adapts to what the customer actually has: an
// autopay mandate is an auto-renewal to switch off; a one-shot plan is a
// subscription to end. Promising to "cancel auto-renewal" on a plan that
// never auto-renews would be a lie.
export function cancelActionLabel(hasMandate) {
	return hasMandate ? "Cancel auto-renewal" : "Cancel subscription";
}
// Banner copy while a cancellation is scheduled.
export function cancellationNotice(accessEndsOn) {
	const end = (accessEndsOn || "").trim();
	const date = end ? end.split(" ")[0] : "";
	if (!date) return "Your plan is scheduled to end. You keep full access until then.";
	return `Your plan ends on ${date}. You keep full access until then.`;
}
// Shared INR formatter - the single place amounts get localized.
export function inr(n) {
	return `₹${(Number(n) || 0).toLocaleString("en-IN")}`;
}
// Big price line on a plan card: "₹3,999" for paid plans, "Free" otherwise.
export function planAmount(priceInr) {
	const n = Number(priceInr) || 0;
	return n > 0 ? inr(n) : "Free";
}
// Small muted per-cycle suffix next to the amount: "/yr" for annual, "/mo"
// for everything else, "" for free plans.
export function planSuffix(priceInr, billingCycle) {
	const n = Number(priceInr) || 0;
	if (n <= 0) return "";
	return (billingCycle || "").toLowerCase() === "annual" ? "/yr" : "/mo";
}
export function planPriceLabel(priceInr, billingCycle) {
	const suffix = planSuffix(priceInr, billingCycle);
	if (!suffix) return "Free";
	return `${planAmount(priceInr)} / ${suffix.slice(1)}`;
}
export function renewalLabel(currentPeriodEnd, daysRemaining) {
	const end = (currentPeriodEnd || "").trim();
	if (!end) return "No active period";
	const date = end.split(" ")[0];
	const d = Number(daysRemaining) || 0;
	// A past-due / expired subscription reports 0 or negative days; don't render a
	// nonsensical "Renews <past date> · -12 days left". #200 review #11.
	if (d <= 0) return `Expired ${date}`;
	return `Renews ${date} · ${d} day${d === 1 ? "" : "s"} left`;
}
