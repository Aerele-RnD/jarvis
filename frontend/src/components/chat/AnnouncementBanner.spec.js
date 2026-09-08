import { describe, it, expect, beforeEach, vi } from "vitest";
import { mount } from "@vue/test-utils";

// The banner is the customer's view of an operator-authored announcement, so these
// pin that untrusted title/body/link can never become executable markup, and that
// the scheme-gated CTA + dismiss behave. The gate is mocked so each test controls
// the announcement payload directly (the gate reads window.announcement once at
// import, which a component test can't re-vary - its reactivity is covered in
// announcementGate.spec.js).
const mocks = vi.hoisted(() => ({
	announcement: {
		active: true,
		id: "ANN-1",
		title: "",
		message: "",
		severity: "Info",
		link_url: "",
		link_label: "",
		interval_days: 7,
	},
	dismissAnnouncement: vi.fn(),
}));

vi.mock("@/announcementGate", () => ({
	announcement: mocks.announcement,
	dismissAnnouncement: mocks.dismissAnnouncement,
	showAnnouncement: { value: true },
}));

import AnnouncementBanner from "./AnnouncementBanner.vue";

/** Reset the shared announcement to a clean baseline, then apply overrides. */
function setAnn(overrides = {}) {
	Object.assign(mocks.announcement, {
		title: "",
		message: "",
		severity: "Info",
		link_url: "",
		link_label: "",
		...overrides,
	});
}

describe("AnnouncementBanner", () => {
	beforeEach(() => {
		mocks.dismissAnnouncement.mockClear();
		setAnn();
	});

	it("renders an untrusted title/body as inert escaped TEXT, never markup (XSS-safe)", () => {
		setAnn({
			title: "Heads up <script>alert(1)</script>",
			message: "<img src=x onerror=alert(1)>",
		});
		const w = mount(AnnouncementBanner);
		// A v-html render would create these elements; escaped interpolation keeps
		// them as literal text.
		expect(w.find("script").exists()).toBe(false);
		expect(w.find("img").exists()).toBe(false);
		expect(w.text()).toContain("<script>alert(1)</script>");
		expect(w.text()).toContain("<img src=x onerror=alert(1)>");
	});

	it("shows the CTA for an http(s) link, with target=_blank + rel=noopener noreferrer", () => {
		setAnn({ link_url: "https://status.example.com", link_label: "Status page" });
		const a = mount(AnnouncementBanner).find("a");
		expect(a.exists()).toBe(true);
		expect(a.attributes("href")).toBe("https://status.example.com");
		expect(a.attributes("target")).toBe("_blank");
		expect(a.attributes("rel")).toBe("noopener noreferrer");
		expect(a.text()).toBe("Status page");
	});

	it("falls back to 'Learn more' when no label is given", () => {
		setAnn({ link_url: "https://x.example.com", link_label: "" });
		expect(mount(AnnouncementBanner).find("a").text()).toBe("Learn more");
	});

	it("suppresses the CTA for a javascript: link (scheme gate)", () => {
		setAnn({ link_url: "javascript:alert(1)", link_label: "Bad" });
		expect(mount(AnnouncementBanner).find("a").exists()).toBe(false);
	});

	it("dismiss button calls dismissAnnouncement", async () => {
		const w = mount(AnnouncementBanner);
		await w.find(".jv-an-x").trigger("click");
		expect(mocks.dismissAnnouncement).toHaveBeenCalledOnce();
	});
});
