import { test } from "node:test";
import assert from "node:assert/strict";
import {
	statusLabel,
	pillTone,
	planPriceLabel,
	renewalLabel,
	inr,
	planAmount,
	planSuffix,
	cancelActionLabel,
	cancellationNotice,
	shortDate,
	cancelPillLabel,
} from "./format.js";

test("statusLabel: maps known states, passes through unknown", () => {
	assert.equal(statusLabel("Active"), "Active");
	assert.equal(statusLabel("Pending Verification"), "Pending verification");
	assert.equal(statusLabel(""), "Unknown");
	assert.equal(statusLabel(null), "Unknown");
});
test("planPriceLabel: free, monthly, annual", () => {
	assert.equal(planPriceLabel(0, "Monthly"), "Free");
	assert.equal(planPriceLabel(100, "Monthly"), "₹100 / mo");
	assert.equal(planPriceLabel(1000, "Annual"), "₹1,000 / yr");
});
test("inr: localizes amounts, coerces junk to 0", () => {
	assert.equal(inr(0), "₹0");
	assert.equal(inr(3999), "₹3,999");
	assert.equal(inr(150000), "₹1,50,000");
	assert.equal(inr(null), "₹0");
	assert.equal(inr("abc"), "₹0");
});
test("planAmount: Free for zero/negative, INR amount otherwise", () => {
	assert.equal(planAmount(0), "Free");
	assert.equal(planAmount(-5), "Free");
	assert.equal(planAmount(null), "Free");
	assert.equal(planAmount(100), "₹100");
	assert.equal(planAmount(3999), "₹3,999");
});
test("planSuffix: empty for free, /yr for annual, /mo otherwise", () => {
	assert.equal(planSuffix(0, "Monthly"), "");
	assert.equal(planSuffix(0, "Annual"), "");
	assert.equal(planSuffix(100, "Monthly"), "/mo");
	assert.equal(planSuffix(100, ""), "/mo");
	assert.equal(planSuffix(1000, "Annual"), "/yr");
	assert.equal(planSuffix(1000, "annual"), "/yr");
});
test("renewalLabel: renders days remaining; handles empty/zero", () => {
	assert.equal(renewalLabel("2026-08-01 00:00:00", 30), "Renews 2026-08-01 · 30 days left");
	assert.equal(renewalLabel("2026-08-01 00:00:00", 1), "Renews 2026-08-01 · 1 day left");
	assert.equal(renewalLabel("", 0), "No active period");
});
test("renewalLabel: expired/past-due (<= 0 days) shows Expired, not negative days", () => {
	assert.equal(renewalLabel("2026-06-01 00:00:00", -12), "Expired 2026-06-01");
	assert.equal(renewalLabel("2026-06-01 00:00:00", 0), "Expired 2026-06-01");
});

test("statusLabel: a scheduled cancellation reads Cancelling, not Active", () => {
	// The server keeps status Active through the paid period, so without this
	// branch a cancelling plan would render a reassuring green "Active".
	assert.equal(statusLabel("Active", 1), "Cancelling");
	assert.equal(statusLabel("Active", 0), "Active");
	assert.equal(statusLabel("Active"), "Active");
});

test("pillTone: cancelling warns; otherwise tracks status", () => {
	assert.equal(pillTone("Active", 1), "jv-pill-warn");
	assert.equal(pillTone("Active", 0), "jv-pill-ok");
	assert.equal(pillTone("Expired", 0), "jv-pill-bad");
	assert.equal(pillTone("Past Due", 0), "jv-pill-warn");
	assert.equal(pillTone("", 0), "jv-pill-muted");
});

test("cancelActionLabel: only promises auto-renewal when one exists", () => {
	assert.equal(cancelActionLabel(true), "Cancel auto-renewal");
	assert.equal(cancelActionLabel(false), "Cancel subscription");
	assert.equal(cancelActionLabel(undefined), "Cancel subscription");
});

test("cancellationNotice: names the end date, degrades without one", () => {
	assert.equal(
		cancellationNotice("2026-08-20 16:11:36.216083"),
		"Your plan ends on 2026-08-20. You keep full access until then."
	);
	assert.match(cancellationNotice(""), /keep full access until then/);
	assert.match(cancellationNotice(null), /keep full access until then/);
});

test("shortDate: D MMM, degrades on junk", () => {
	assert.equal(shortDate("2026-08-21 12:56:09"), "21 Aug");
	assert.equal(shortDate("2026-01-05"), "5 Jan");
	assert.equal(shortDate(""), "");
	assert.equal(shortDate(null), "");
	assert.equal(shortDate("not-a-date"), "");
});

test("cancelPillLabel: glanceable end date, not the ambiguous 'Cancelling'", () => {
	assert.equal(cancelPillLabel("2026-08-21 12:56:09"), "Ends 21 Aug");
	assert.equal(cancelPillLabel(""), "Ending");
	assert.equal(cancelPillLabel(null), "Ending");
});
