import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";

vi.mock("frappe-ui", () => ({
	Dialog: {
		props: ["modelValue", "options"],
		template: "<div><slot name='body-content'/><slot name='actions'/></div>",
	},
	Button: {
		props: ["label", "variant", "disabled"],
		emits: ["click"],
		template: "<button :disabled='disabled' @click=\"$emit('click')\">{{ label }}</button>",
	},
	FormControl: {
		props: ["modelValue", "type", "rows"],
		emits: ["update:modelValue"],
		template:
			"<textarea :value='modelValue' @input=\"$emit('update:modelValue', $event.target.value)\"/>",
	},
}));

vi.mock("@/branding", () => ({ agentName: "Jarvis" }));

vi.mock("@/api", () => ({
	submitPulseFeedback: vi.fn().mockResolvedValue({ ok: true }),
}));

import * as api from "@/api";
import PulseFeedbackDialog from "./PulseFeedbackDialog.vue";
import { pulseFeedbackOpen, pulseFeedbackContext } from "@/lib/pulseFeedbackGate";

describe("PulseFeedbackDialog", () => {
	beforeEach(() => {
		pulseFeedbackOpen.value = false;
		pulseFeedbackContext.value = null;
		vi.clearAllMocks();
	});

	it("hides the chip question entirely when features_offered is empty", () => {
		pulseFeedbackContext.value = {
			period_label: "This month, Sep 2026",
			features_offered: [],
		};
		pulseFeedbackOpen.value = true;
		const w = mount(PulseFeedbackDialog);
		expect(w.text()).not.toContain("Which do you use most?");
	});

	it("renders chips with voice_chat mapped to Notes and dictation, not Voice chat", () => {
		pulseFeedbackContext.value = {
			period_label: "This month, Sep 2026",
			features_offered: ["file_box", "voice_chat", "skills"],
		};
		pulseFeedbackOpen.value = true;
		const w = mount(PulseFeedbackDialog);
		expect(w.text()).toContain("Which do you use most?");
		expect(w.text()).toContain("Notes and dictation");
		expect(w.text()).not.toContain("Voice chat");
		expect(w.text()).toContain("File box");
		expect(w.text()).toContain("Skills");
	});

	it("Send is disabled until a star is picked, then submits with offered+selected", async () => {
		pulseFeedbackContext.value = {
			period_label: "This month",
			features_offered: ["file_box"],
		};
		pulseFeedbackOpen.value = true;
		const w = mount(PulseFeedbackDialog);
		const sendBtn = () => w.findAll("button").find((b) => b.text() === "Send feedback");
		expect(sendBtn().attributes("disabled")).toBeDefined();

		const stars = w.findAll("button").filter((b) => b.text() === "★");
		await stars[2].trigger("click"); // 3rd star = 3 stars
		expect(sendBtn().attributes("disabled")).toBeUndefined();

		await w
			.findAll("button")
			.find((b) => b.text() === "File box")
			.trigger("click");
		await sendBtn().trigger("click");
		expect(api.submitPulseFeedback).toHaveBeenCalledWith(
			3,
			["file_box"],
			["file_box"],
			"",
			""
		);
	});

	it("Maybe later closes without submitting", async () => {
		pulseFeedbackContext.value = { period_label: "This month", features_offered: [] };
		pulseFeedbackOpen.value = true;
		const w = mount(PulseFeedbackDialog);
		await w
			.findAll("button")
			.find((b) => b.text() === "Maybe later")
			.trigger("click");
		expect(api.submitPulseFeedback).not.toHaveBeenCalled();
		expect(pulseFeedbackOpen.value).toBe(false);
	});
});
