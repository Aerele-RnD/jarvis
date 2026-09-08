import { describe, it, expect, vi, beforeEach } from "vitest";

const api = vi.hoisted(() => ({ getMySettings: vi.fn() }));
vi.mock("@/api", () => api);

import { myUsage, loadMyUsage, takeUsage } from "./usage";

const reading = () => ({
	monthly_token_limit: 1000000,
	limit_period: "Weekly",
	period_tokens: 400000,
	total_tokens: 4200000,
});

beforeEach(() => {
	vi.clearAllMocks();
	myUsage.value = null;
});

describe("usage store", () => {
	it("takes the cap reading off a conversation-context payload, no extra request", () => {
		takeUsage({ used: 1, capacity: 2, usage: reading() });
		expect(myUsage.value).toEqual(reading());
		expect(api.getMySettings).not.toHaveBeenCalled();
	});

	it("keeps the last reading when a payload carries none", () => {
		myUsage.value = reading();
		takeUsage({ used: 1, capacity: 2 });
		takeUsage(null);
		expect(myUsage.value).toEqual(reading());
	});

	it("loads once from settings for a chat with no conversation yet", async () => {
		api.getMySettings.mockResolvedValue({
			ok: true,
			data: { ...reading(), sidebar_order: "" },
		});
		await loadMyUsage();
		expect(myUsage.value).toEqual(reading());
	});
});
