import { describe, it, expect } from "vitest";
import { fmtTokens, contextReading, limitWindow } from "./tokens.js";

describe("fmtTokens", () => {
	it("renders an even thousand without a decimal", () => {
		expect(fmtTokens(42000)).toBe("42k");
	});
	it("renders an even hundred-thousand without a decimal", () => {
		expect(fmtTokens(200000)).toBe("200k");
	});
});

describe("contextReading", () => {
	it("reads the used/capacity pair when fresh", () => {
		const r = contextReading({ context: { used: 42000, capacity: 200000, fresh: true } });
		expect(r).toEqual({ fresh: true, text: "42k of 200k context in use" });
	});
	it("falls back to not measured yet when not fresh", () => {
		const r = contextReading({ context: { used: 0, capacity: 0, fresh: false } });
		expect(r).toEqual({ fresh: false, text: "Not measured yet" });
	});
});

describe("limitWindow", () => {
	it("an all-time cap counts the cumulative total", () => {
		const w = limitWindow({
			total_tokens: 500000,
			period_tokens: 40000,
			limit_period: "All time",
		});
		expect(w).toEqual({ used: 500000, label: "all time" });
	});
	it("a missing period reads as all time", () => {
		expect(limitWindow({ total_tokens: 7 })).toEqual({ used: 7, label: "all time" });
	});
	it("a daily / weekly / monthly cap counts the current window", () => {
		const m = { total_tokens: 500000, period_tokens: 40000 };
		expect(limitWindow({ ...m, limit_period: "Daily" })).toEqual({
			used: 40000,
			label: "today",
		});
		expect(limitWindow({ ...m, limit_period: "Weekly" })).toEqual({
			used: 40000,
			label: "this week",
		});
		expect(limitWindow({ ...m, limit_period: "Monthly" })).toEqual({
			used: 40000,
			label: "this month",
		});
	});
});
