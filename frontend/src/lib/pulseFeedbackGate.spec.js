// vi.mock("@/api", () => ({...})) is this repo's established idiom for
// mocking @/api in a module that imports it directly (see
// SessionFeedbackDialog.spec.js) - vi.spyOn on the live module's named export
// is not reliably interceptable through the Vite/vitest ESM boundary here.
import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("@/api", () => ({
	pulseContext: vi.fn(),
}));

import * as apiModule from "@/api";
import {
	pulseFeedbackOpen,
	pulseFeedbackContext,
	maybeOpenPulseFeedback,
	closePulseFeedback,
} from "./pulseFeedbackGate";

describe("pulseFeedbackGate", () => {
	beforeEach(() => {
		pulseFeedbackOpen.value = false;
		pulseFeedbackContext.value = null;
		vi.clearAllMocks();
	});

	it("opens and stores context when pulseContext() says due", async () => {
		apiModule.pulseContext.mockResolvedValue({
			due: true,
			period_label: "This month, Sep 2026",
			features_offered: ["file_box"],
		});
		await maybeOpenPulseFeedback();
		expect(pulseFeedbackOpen.value).toBe(true);
		expect(pulseFeedbackContext.value.features_offered).toEqual(["file_box"]);
	});

	it("stays closed when pulseContext() says not due", async () => {
		apiModule.pulseContext.mockResolvedValue({ due: false });
		await maybeOpenPulseFeedback();
		expect(pulseFeedbackOpen.value).toBe(false);
	});

	it("stays closed and does not throw when pulseContext() rejects", async () => {
		apiModule.pulseContext.mockRejectedValue(new Error("offline"));
		await expect(maybeOpenPulseFeedback()).resolves.not.toThrow();
		expect(pulseFeedbackOpen.value).toBe(false);
	});

	it("closePulseFeedback closes without clearing context", () => {
		pulseFeedbackContext.value = { due: true, features_offered: [] };
		pulseFeedbackOpen.value = true;
		closePulseFeedback();
		expect(pulseFeedbackOpen.value).toBe(false);
		expect(pulseFeedbackContext.value).not.toBeNull();
	});
});
