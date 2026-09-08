import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";

/**
 * The per-user token cap carries a window (All time / Daily / Weekly /
 * Monthly). The admin table must show which window a user is on, read their
 * usage against THAT window, and send the window along with the number.
 */

vi.mock("frappe-ui", () => ({
	Button: {
		name: "Button",
		props: ["label", "variant", "iconLeft", "loading", "disabled", "size"],
		emits: ["click"],
		template: `<button class="stub-button" :disabled="disabled" @click="$emit('click')">{{ label }}</button>`,
	},
	FeatherIcon: { name: "FeatherIcon", props: ["name"], template: `<i class="stub-icon" />` },
	ErrorMessage: {
		name: "ErrorMessage",
		props: ["message"],
		template: `<span>{{ message }}</span>`,
	},
	FormControl: {
		name: "FormControl",
		props: ["type", "options", "modelValue", "label", "size", "disabled", "placeholder"],
		emits: ["update:modelValue"],
		template: `
			<select v-if="type === 'select'" class="stub-select" :value="modelValue"
				@change="$emit('update:modelValue', $event.target.value)">
				<option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option>
			</select>
			<input v-else class="stub-input" :value="modelValue"
				@input="$emit('update:modelValue', $event.target.value)" />`,
	},
	toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/utils/datetime", () => ({ timeAgo: () => "just now" }));

const api = vi.hoisted(() => ({
	adminListUserUsage: vi.fn(),
	adminSetUserLimit: vi.fn(),
	adminSetUserModelLimit: vi.fn(),
	adminSyncUsage: vi.fn(),
}));
vi.mock("@/api", () => api);

import UsageAdminPane from "./UsageAdminPane.vue";

function weeklyUser() {
	return {
		user: "a@example.test",
		full_name: "A",
		monthly_token_limit: 100000,
		limit_period: "Weekly",
		period_tokens: 40000,
		total_tokens: 500000,
		last_usage_at: null,
		per_model: [],
	};
}

async function mountWith(rows) {
	api.adminListUserUsage.mockResolvedValue({ ok: true, data: rows });
	const w = mount(UsageAdminPane);
	await flushPromises();
	return w;
}

beforeEach(() => {
	vi.clearAllMocks();
	api.adminSetUserLimit.mockResolvedValue({
		ok: true,
		data: { monthly_token_limit: 100000, limit_period: "Daily" },
	});
});

describe("UsageAdminPane, limit window", () => {
	it("shows the user's window and reads usage against it", async () => {
		const w = await mountWith([weeklyUser()]);
		expect(w.find("select.stub-select").element.value).toBe("Weekly");
		expect(w.text()).toContain("40k of 100k this week · 40%");
	});

	it("changing only the window enables Save and sends it with the number", async () => {
		const w = await mountWith([weeklyUser()]);
		const save = w.findAll("button.stub-button").find((b) => b.text() === "Save");
		expect(save.attributes("disabled")).toBeDefined();
		await w.find("select.stub-select").setValue("Daily");
		expect(save.attributes("disabled")).toBeUndefined();
		await save.trigger("click");
		await flushPromises();
		expect(api.adminSetUserLimit).toHaveBeenCalledWith("a@example.test", 100000, "Daily");
	});
});
