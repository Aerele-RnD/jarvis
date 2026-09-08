import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";

/**
 * The per-user token cap is edited in a dialog (Limit + Window), never inline:
 * the row reads as text with a pencil, and the per-model rows get the same
 * pencil for their monthly cap.
 */

vi.mock("frappe-ui", () => ({
	Button: {
		name: "Button",
		props: ["label", "variant", "iconLeft", "icon", "loading", "disabled", "size", "tooltip"],
		emits: ["click"],
		template: `<button class="stub-button" :data-icon="icon" :disabled="disabled" @click="$emit('click')">{{ label }}</button>`,
	},
	FeatherIcon: { name: "FeatherIcon", props: ["name"], template: `<i class="stub-icon" />` },
	ErrorMessage: {
		name: "ErrorMessage",
		props: ["message"],
		template: `<span>{{ message }}</span>`,
	},
	Dialog: {
		name: "Dialog",
		props: ["modelValue", "options"],
		emits: ["update:modelValue"],
		template: `<div v-if="modelValue" class="stub-dialog"><h4>{{ options && options.title }}</h4><slot name="body-content" /><slot name="actions" /></div>`,
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
		monthly_token_limit: 1000000,
		limit_period: "Weekly",
		period_tokens: 40000,
		total_tokens: 500000,
		last_usage_at: null,
		per_model: [
			{
				model: "gpt-5.5",
				month_tokens: 302500,
				month_input_tokens: 300000,
				month_output_tokens: 2500,
				monthly_token_limit: 0,
			},
		],
	};
}

async function mountWith(rows) {
	api.adminListUserUsage.mockResolvedValue({ ok: true, data: rows });
	const w = mount(UsageAdminPane);
	await flushPromises();
	return w;
}

const saveButton = (w) => w.findAll("button.stub-button").find((b) => b.text() === "Save");
const editButtons = (w) => w.findAll("button.stub-button[data-icon='edit-2']");

beforeEach(() => {
	vi.clearAllMocks();
	api.adminSetUserLimit.mockResolvedValue({
		ok: true,
		data: { monthly_token_limit: 1000000, limit_period: "Daily" },
	});
	api.adminSetUserModelLimit.mockResolvedValue({
		ok: true,
		data: { monthly_token_limit: 50000 },
	});
});

describe("UsageAdminPane, token limit dialog", () => {
	it("shows the limit and window as text with no inline inputs", async () => {
		const w = await mountWith([weeklyUser()]);
		expect(w.text()).toContain("1M · weekly");
		expect(w.text()).toContain("40k of 1M this week · 4%");
		expect(w.find("input.stub-input").exists()).toBe(false);
		expect(w.find(".stub-dialog").exists()).toBe(false);
	});

	it("the pencil opens a dialog; saving sends limit and window and updates the row", async () => {
		const w = await mountWith([weeklyUser()]);
		await editButtons(w)[0].trigger("click");
		expect(w.find(".stub-dialog h4").text()).toBe("Token limit · A");
		await w.find(".stub-dialog select.stub-select").setValue("Daily");
		await saveButton(w).trigger("click");
		await flushPromises();
		expect(api.adminSetUserLimit).toHaveBeenCalledWith("a@example.test", 1000000, "Daily");
		expect(w.find(".stub-dialog").exists()).toBe(false);
		expect(w.text()).toContain("1M · daily");
		expect(w.text()).toContain("0 of 1M today · 0%");
	});

	it("a per-model row gets the same pencil for its monthly cap", async () => {
		const w = await mountWith([weeklyUser()]);
		await w.find("button[aria-expanded]").trigger("click");
		expect(w.text()).toContain("Unlimited");
		await editButtons(w)[1].trigger("click");
		expect(w.find(".stub-dialog h4").text()).toBe("Monthly limit · gpt-5.5");
		expect(w.find(".stub-dialog select.stub-select").exists()).toBe(false);
		await w.find(".stub-dialog input.stub-input").setValue("50000");
		await saveButton(w).trigger("click");
		await flushPromises();
		expect(api.adminSetUserModelLimit).toHaveBeenCalledWith(
			"a@example.test",
			"gpt-5.5",
			50000
		);
		expect(w.text()).toContain("50k monthly");
	});
});
