// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// frappe-ui's `call` is the control-plane round-trip recheck() makes; mock it.
const callMock = vi.fn();
vi.mock("frappe-ui", () => ({ call: (...a) => callMock(...a) }));

// The gate reads window.maintenance at import time, so seed it then dynamic-import
// with a fresh module registry so each test gets its own module state.
async function loadGate(boot) {
	vi.resetModules();
	window.maintenance = boot;
	return import("./maintenanceGate.js");
}

beforeEach(() => {
	// The gate polls via setInterval while a hold is up; fake timers keep those out of
	// the event loop (no real 60s timer leaks across the resetModules-per-test).
	vi.useFakeTimers();
	callMock.mockReset();
	delete window.agent_name; // -> agentName defaults to "Jarvis"
});

afterEach(() => {
	vi.clearAllTimers();
	vi.useRealTimers();
});

describe("maintenanceGate", () => {
	it("seeds holdActive + branded holdText from the boot payload", async () => {
		const g = await loadGate({ active: true, message: "" });
		expect(g.holdActive.value).toBe(true);
		expect(g.holdText.value).toBe("Jarvis is upgrading and will be back shortly.");
	});

	it("is not held when boot is absent or inactive", async () => {
		expect((await loadGate(undefined)).holdActive.value).toBe(false);
		expect((await loadGate({ active: false })).holdActive.value).toBe(false);
	});

	it("shows the operator's custom message when set", async () => {
		const g = await loadGate({ active: true, message: "Scheduled upgrade, ~5 min." });
		expect(g.holdText.value).toBe("Scheduled upgrade, ~5 min.");
	});

	it("uses the white-label agent name in the default copy", async () => {
		window.agent_name = "Acme AI";
		const g = await loadGate({ active: true, message: "" });
		expect(g.holdText.value).toBe("Acme AI is upgrading and will be back shortly.");
	});

	it("raiseHold turns a not-held tab into held with the server message", async () => {
		const g = await loadGate({ active: false, message: "" });
		expect(g.holdActive.value).toBe(false);
		g.raiseHold("We're upgrading now.");
		expect(g.holdActive.value).toBe(true);
		expect(g.holdText.value).toBe("We're upgrading now.");
	});

	it("recheck lifts the hold when the CP reports it cleared", async () => {
		const g = await loadGate({ active: true, message: "x" });
		callMock.mockResolvedValueOnce({ active: false, message: "" });
		const stillHeld = await g.recheck();
		expect(callMock).toHaveBeenCalledWith("jarvis.maintenance_notice.check");
		expect(g.holdActive.value).toBe(false);
		expect(stillHeld).toBe(false);
	});

	it("recheck keeps the last-known hold when the poll throws (never clears on error)", async () => {
		const g = await loadGate({ active: true, message: "held" });
		callMock.mockRejectedValueOnce(new Error("offline"));
		await g.recheck();
		expect(g.holdActive.value).toBe(true);
		expect(g.holdText.value).toBe("held");
	});

	it("recheck keeps the last-known hold when the CP payload is malformed (missing active)", async () => {
		const g = await loadGate({ active: true, message: "held" });
		callMock.mockResolvedValueOnce({ message: "no active key" });
		await g.recheck();
		expect(g.holdActive.value).toBe(true);
	});

	it("clearHold lifts an active hold (self-heal when a send is accepted)", async () => {
		const g = await loadGate({ active: true, message: "up" });
		expect(g.holdActive.value).toBe(true);
		g.clearHold();
		expect(g.holdActive.value).toBe(false);
	});
});
