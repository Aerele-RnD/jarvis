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

	// The "dismissed this page load" flag is module-private state with no
	// reset hook (by design -- it is meant to last for the page's lifetime,
	// only a real reload clears it), so a plain `it` block sharing the
	// already-imported module would see whatever an earlier test in this file
	// left behind (e.g. the "closePulseFeedback closes..." case above already
	// dismisses it). vi.resetModules() + a fresh dynamic import gives this
	// test its own module instance, the same isolation announcementGate.spec.js
	// uses for its own module-private state.
	it("does not call pulseContext() again after the survey was dismissed this page load", async () => {
		vi.resetModules();
		const fresh = await import("./pulseFeedbackGate");
		apiModule.pulseContext.mockResolvedValue({ due: true, features_offered: [] });

		await fresh.maybeOpenPulseFeedback();
		expect(apiModule.pulseContext).toHaveBeenCalledTimes(1);
		expect(fresh.pulseFeedbackOpen.value).toBe(true);

		fresh.closePulseFeedback();
		await fresh.maybeOpenPulseFeedback();

		// Still exactly one call: the second maybeOpenPulseFeedback() returned
		// early instead of hitting the backend again -- switching conversations
		// after "Maybe later" must not re-offer (and re-burn the monthly cap).
		expect(apiModule.pulseContext).toHaveBeenCalledTimes(1);
	});

	// Two chat opens in quick succession both pass the "dismissed?" gate before
	// either pulseContext() call returns. If the survey the first one opened is
	// dismissed while the second request is still in flight, the second must
	// not reopen it on top of the dismissal: the gate has to be re-checked
	// AFTER the await, not only before it.
	it("does not reopen when the survey was dismissed while a check was still in flight", async () => {
		vi.resetModules();
		const fresh = await import("./pulseFeedbackGate");
		let resolveInFlight;
		apiModule.pulseContext.mockImplementation(
			() => new Promise((resolve) => (resolveInFlight = resolve))
		);

		const inFlight = fresh.maybeOpenPulseFeedback(); // passes the gate, awaits
		fresh.closePulseFeedback(); // user dismisses meanwhile
		resolveInFlight({ due: true, features_offered: [] });
		await inFlight;

		expect(fresh.pulseFeedbackOpen.value).toBe(false);
	});
});
