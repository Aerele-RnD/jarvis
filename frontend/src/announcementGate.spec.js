import { describe, it, expect, vi } from "vitest";

// The gate reads window.announcement + the signed-in user ONCE at import, so each
// scenario resets the module registry and re-imports with a fresh window payload
// (the globalNotifier.spec pattern). Covers: the active gate, the id-keyed snooze
// seeded at boot, and the reactive hide on dismiss.
vi.mock("@/data/session", () => ({ session: { user: "u@example.com" } }));

const SNOOZE_KEY = "jarvis-announcement-banner-snooze:u@example.com";

const storage = new Map();
vi.stubGlobal("localStorage", {
	getItem: (k) => (storage.has(k) ? storage.get(k) : null),
	setItem: (k, v) => storage.set(k, String(v)),
	removeItem: (k) => storage.delete(k),
	clear: () => storage.clear(),
});

/** Reset modules + storage, seed an optional boot snooze, set window.announcement,
 *  then import a fresh copy of the gate. */
async function loadGate(announcement, seedSnooze) {
	vi.resetModules();
	storage.clear();
	if (seedSnooze) storage.set(SNOOZE_KEY, JSON.stringify(seedSnooze));
	window.announcement = announcement;
	return import("@/announcementGate");
}

describe("announcementGate", () => {
	it("shows when active and never snoozed", async () => {
		const { showAnnouncement } = await loadGate({
			active: true,
			id: "ANN-1",
			interval_days: 7,
		});
		expect(showAnnouncement.value).toBe(true);
	});

	it("is hidden when the announcement is inactive", async () => {
		const { showAnnouncement } = await loadGate({ active: false, id: "ANN-1" });
		expect(showAnnouncement.value).toBe(false);
	});

	it("hides reactively the moment it is dismissed", async () => {
		const { showAnnouncement, dismissAnnouncement } = await loadGate({
			active: true,
			id: "ANN-1",
			interval_days: 7,
		});
		expect(showAnnouncement.value).toBe(true);
		dismissAnnouncement();
		expect(showAnnouncement.value).toBe(false);
		// The dismissal is persisted for the same id, so a re-import stays hidden.
		const again = await loadGate(
			{ active: true, id: "ANN-1", interval_days: 7 },
			JSON.parse(storage.get(SNOOZE_KEY))
		);
		expect(again.showAnnouncement.value).toBe(false);
	});

	it("stays hidden at boot when an unexpired snooze for the SAME id exists", async () => {
		const snooze = { id: "ANN-1", until: Date.now() + 30 * 86400000 };
		const { showAnnouncement } = await loadGate(
			{ active: true, id: "ANN-1", interval_days: 7 },
			snooze
		);
		expect(showAnnouncement.value).toBe(false);
	});

	it("re-shows for a NEW id even under an unexpired old-id snooze", async () => {
		const snooze = { id: "ANN-old", until: Date.now() + 30 * 86400000 };
		const { showAnnouncement } = await loadGate(
			{ active: true, id: "ANN-new", interval_days: 7 },
			snooze
		);
		expect(showAnnouncement.value).toBe(true);
	});
});
