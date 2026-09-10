import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";

vi.mock("frappe-ui", () => ({
	Dialog: {
		props: ["modelValue", "options"],
		emits: ["close"],
		template: "<div><slot name='body-content'/><slot name='actions'/></div>",
	},
	Button: {
		props: ["label", "variant", "disabled"],
		emits: ["click"],
		template: "<button :disabled='disabled' @click=\"$emit('click')\">{{ label }}</button>",
	},
	FormControl: {
		props: ["modelValue", "placeholder", "type"],
		emits: ["update:modelValue"],
		template:
			"<input :value='modelValue' @input=\"$emit('update:modelValue', $event.target.value)\"/>",
	},
}));

vi.mock("@/api", () => ({
	submitSessionFeedback: vi.fn().mockResolvedValue({ ok: true, recorded: true }),
}));

import * as api from "@/api";
import { Dialog } from "frappe-ui";
import SessionFeedbackDialog from "./SessionFeedbackDialog.vue";
import {
	sessionFeedbackOpen,
	sessionFeedbackConversation,
	openSessionFeedback,
} from "@/lib/sessionFeedbackGate";

describe("SessionFeedbackDialog", () => {
	beforeEach(() => {
		sessionFeedbackOpen.value = false;
		sessionFeedbackConversation.value = null;
		vi.clearAllMocks();
	});

	it("shows all 5 chips and no note field until a low chip is selected", async () => {
		openSessionFeedback("conv-1");
		const w = mount(SessionFeedbackDialog);
		const buttons = w.findAll("button");
		// 5 chips + Skip + Send = 7 buttons
		const chipButtons = buttons.filter((b) =>
			["Great", "Good", "Okay", "Not great", "Frustrating"].some((v) => b.text().includes(v))
		);
		expect(chipButtons).toHaveLength(5);
		expect(w.find("input").exists()).toBe(false);
	});

	it("shows the note field only for Okay/Not great/Frustrating, not Great/Good", async () => {
		openSessionFeedback("conv-1");
		const w = mount(SessionFeedbackDialog);
		const chip = (label) => w.findAll("button").find((b) => b.text().includes(label));

		await chip("Great, got what I needed").trigger("click");
		expect(w.find("input").exists()).toBe(false);

		await chip("Good, mostly helpful").trigger("click");
		expect(w.find("input").exists()).toBe(false);

		await chip("Okay, so-so").trigger("click");
		expect(w.find("input").exists()).toBe(true);

		await chip("Not great, missed the mark").trigger("click");
		expect(w.find("input").exists()).toBe(true);

		await chip("Frustrating, wasted my time").trigger("click");
		expect(w.find("input").exists()).toBe(true);
	});

	it("disables Send until a chip is selected, then submits with chip_value + note", async () => {
		openSessionFeedback("conv-1");
		const w = mount(SessionFeedbackDialog);
		const sendBtn = () => w.findAll("button").find((b) => b.text() === "Send");
		expect(sendBtn().attributes("disabled")).toBeDefined();

		await w
			.findAll("button")
			.find((b) => b.text().includes("Okay, so-so"))
			.trigger("click");
		expect(sendBtn().attributes("disabled")).toBeUndefined();

		await w.find("input").setValue("it hallucinated a total");
		await sendBtn().trigger("click");
		expect(api.submitSessionFeedback).toHaveBeenCalledWith(
			"conv-1",
			"Okay",
			"it hallucinated a total"
		);
	});

	it("Skip submits with chip_value omitted (null) and closes", async () => {
		openSessionFeedback("conv-1");
		const w = mount(SessionFeedbackDialog);
		await w
			.findAll("button")
			.find((b) => b.text() === "Skip")
			.trigger("click");
		expect(api.submitSessionFeedback).toHaveBeenCalledWith("conv-1", null, "");
		expect(sessionFeedbackOpen.value).toBe(false);
	});

	it("an Escape/X/outside-click dismissal (Dialog's close event) claims the offer exactly like Skip", async () => {
		// Regression: frappe-ui's Dialog fires `close` on Escape, its ghost X
		// button, and an outside click — all bypass this component's own Skip/
		// Send handlers. Without @close wired to skip(), session_feedback_asked_at
		// never gets stamped, so the next reply re-polls as still due and the
		// popup reopens on top of it (and burns feedbackGate's IGNORE_CAP).
		openSessionFeedback("conv-1");
		const w = mount(SessionFeedbackDialog);
		await w.findComponent(Dialog).vm.$emit("close");
		expect(api.submitSessionFeedback).toHaveBeenCalledWith("conv-1", null, "");
		expect(sessionFeedbackOpen.value).toBe(false);
	});
});
