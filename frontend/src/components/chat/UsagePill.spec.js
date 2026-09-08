import { describe, it, expect, vi } from "vitest";
import { mount } from "@vue/test-utils";

vi.mock("frappe-ui", () => ({
	Popover: {
		props: ["placement"],
		template:
			"<div><slot name='target' :togglePopover='() => {}'/><slot name='body' :close='() => {}'/></div>",
	},
}));

import UsagePill from "./UsagePill.vue";

const weekly = (over = {}) => ({
	monthly_token_limit: 1000000,
	limit_period: "Weekly",
	period_tokens: 400000,
	total_tokens: 4200000,
	...over,
});

describe("UsagePill", () => {
	it("stays hidden when the user has no cap", () => {
		const w = mount(UsagePill, { props: { usage: weekly({ monthly_token_limit: 0 }) } });
		expect(w.find("[data-testid=usage-pill]").exists()).toBe(false);
		expect(
			mount(UsagePill, { props: { usage: null } })
				.find("[data-testid=usage-pill]")
				.exists()
		).toBe(false);
	});

	it("is a bare bar: no text, the fill at the used percentage, the reading on hover", () => {
		const w = mount(UsagePill, { props: { usage: weekly() } });
		const pill = w.find("[data-testid=usage-pill]");
		expect(pill.text()).toBe("");
		expect(pill.attributes("aria-label")).toBe("400k of 1M this week");
		expect(pill.attributes("title")).toBe("400k of 1M this week");
		expect(pill.find("[data-testid=usage-fill]").attributes("style")).toContain("width: 40%");
		expect(pill.classes()).not.toContain("jv-usage-warn");
	});

	it("turns amber at 80%", () => {
		const w = mount(UsagePill, { props: { usage: weekly({ period_tokens: 820000 }) } });
		const pill = w.find("[data-testid=usage-pill]");
		expect(pill.find("[data-testid=usage-fill]").attributes("style")).toContain("width: 82%");
		expect(pill.classes()).toContain("jv-usage-warn");
	});

	it("says the limit is reached and when it resets, on hover and to screen readers", () => {
		const w = mount(UsagePill, { props: { usage: weekly({ period_tokens: 1000000 }) } });
		const pill = w.find("[data-testid=usage-pill]");
		expect(pill.text()).toBe("");
		expect(pill.attributes("aria-label")).toBe("Limit reached · resets Sunday");
		expect(pill.classes()).toContain("jv-usage-full");
	});

	it("popover shows the window, the reset and the all-time total", () => {
		const w = mount(UsagePill, { props: { usage: weekly({ period_tokens: 820000 }) } });
		const text = w.text();
		expect(text).toContain("Jarvis usage limit");
		expect(text).toContain(
			"Your allowance in Jarvis, set by your admin. Not your model provider's usage."
		);
		expect(text).toContain("820k of 1M");
		expect(text).toContain("Sunday 00:00");
		expect(text).toContain("4.2M");
	});
});
