import { test } from "node:test";
import assert from "node:assert/strict";

import {
	snoozeUntil,
	bannerShouldShow,
	bannerToneFor,
	isSafeLink,
	readSnooze,
	writeSnooze,
	SNOOZE_KEY,
} from "./announcementNudge.js";

const DAY = 86400000;
const NOW = 1_000_000_000_000; // frozen "now" for every time-based assertion

// ---- snoozeUntil: the single floored builder -------------------------------

test("snoozeUntil: a normal interval -> now + N days", () => {
	assert.equal(snoozeUntil({ interval_days: 3 }, NOW), NOW + 3 * DAY);
});

test("snoozeUntil: missing / zero / NaN interval defaults to 7 days", () => {
	assert.equal(snoozeUntil({}, NOW), NOW + 7 * DAY);
	assert.equal(snoozeUntil({ interval_days: 0 }, NOW), NOW + 7 * DAY);
	assert.equal(snoozeUntil({ interval_days: "abc" }, NOW), NOW + 7 * DAY);
});

test("snoozeUntil: a negative interval floors to 1 day (never an already-expired snooze)", () => {
	assert.equal(snoozeUntil({ interval_days: -5 }, NOW), NOW + 1 * DAY);
});

// ---- bannerShouldShow ------------------------------------------------------

test("bannerShouldShow: never snoozed -> true", () => {
	assert.equal(bannerShouldShow({ id: "ANN-1" }, NOW, null), true);
});

test("bannerShouldShow: same id, unexpired snooze -> false (hides within the interval)", () => {
	const snooze = { id: "ANN-1", until: NOW + DAY };
	assert.equal(bannerShouldShow({ id: "ANN-1" }, NOW, snooze), false);
});

test("bannerShouldShow: same id, expired snooze -> true (re-shows after the interval)", () => {
	const snooze = { id: "ANN-1", until: NOW - 1 };
	assert.equal(bannerShouldShow({ id: "ANN-1" }, NOW, snooze), true);
});

test("bannerShouldShow: a NEW id re-shows even under an unexpired old-id snooze", () => {
	const snooze = { id: "ANN-1", until: NOW + 999 * DAY };
	assert.equal(bannerShouldShow({ id: "ANN-2" }, NOW, snooze), true);
});

// ---- bannerToneFor ---------------------------------------------------------

test("bannerToneFor: Warning -> warning; everything else -> info", () => {
	assert.equal(bannerToneFor({ severity: "Warning" }), "warning");
	assert.equal(bannerToneFor({ severity: "warning" }), "warning"); // case-insensitive
	assert.equal(bannerToneFor({ severity: "Info" }), "info");
	assert.equal(bannerToneFor({ severity: "" }), "info");
	assert.equal(bannerToneFor({}), "info");
	assert.equal(bannerToneFor(null), "info");
	// An unknown future severity never becomes a false alarm - it stays neutral info.
	assert.equal(bannerToneFor({ severity: "Critical" }), "info");
});

// ---- isSafeLink ------------------------------------------------------------

test("isSafeLink: accepts http(s), any case", () => {
	assert.equal(isSafeLink("https://example.com"), true);
	assert.equal(isSafeLink("http://example.com"), true);
	assert.equal(isSafeLink("HTTPS://EXAMPLE.COM"), true);
});

test("isSafeLink: rejects javascript:/data:/protocol-relative and whitespace tricks", () => {
	assert.equal(isSafeLink("javascript:alert(1)"), false);
	assert.equal(isSafeLink("data:text/html,<script>"), false);
	assert.equal(isSafeLink("//evil.example.com"), false);
	assert.equal(isSafeLink(" javascript:alert(1)"), false); // leading space
	assert.equal(isSafeLink("\njavascript:alert(1)"), false); // leading newline
	assert.equal(isSafeLink(""), false);
	assert.equal(isSafeLink(null), false);
	assert.equal(isSafeLink(undefined), false);
});

// ---- snooze read/write -----------------------------------------------------

function installLocalStorage() {
	const store = new Map();
	globalThis.localStorage = {
		getItem: (k) => (store.has(k) ? store.get(k) : null),
		setItem: (k, v) => store.set(k, String(v)),
		removeItem: (k) => store.delete(k),
	};
	return store;
}

test("writeSnooze/readSnooze: round-trip, and writeSnooze returns the record", () => {
	installLocalStorage();
	try {
		const rec = writeSnooze({ id: "ANN-1", interval_days: 3 }, NOW, "user@a");
		assert.deepEqual(rec, { id: "ANN-1", until: NOW + 3 * DAY });
		assert.deepEqual(readSnooze("user@a"), rec);
	} finally {
		delete globalThis.localStorage;
	}
});

test("writeSnooze returns the record even with no localStorage (caller still hides the banner)", () => {
	assert.equal(typeof globalThis.localStorage, "undefined");
	const rec = writeSnooze({ id: "ANN-1", interval_days: 2 }, NOW, "user@a");
	assert.deepEqual(rec, { id: "ANN-1", until: NOW + 2 * DAY });
});

test("snooze is per-user: A's write doesn't suppress B's banner", () => {
	const store = installLocalStorage();
	try {
		writeSnooze({ id: "ANN-1", interval_days: 7 }, NOW, "user@a");
		assert.ok(readSnooze("user@a"));
		assert.equal(readSnooze("user@b"), null);
		assert.ok(store.has(`${SNOOZE_KEY}:user@a`));
		assert.ok(!store.has(`${SNOOZE_KEY}:user@b`));
	} finally {
		delete globalThis.localStorage;
	}
});

test("missing userId falls back to a stable 'anon' key", () => {
	const store = installLocalStorage();
	try {
		writeSnooze({ id: "ANN-1", interval_days: 7 }, NOW, undefined);
		assert.ok(store.has(`${SNOOZE_KEY}:anon`));
		assert.equal(readSnooze().id, "ANN-1");
		assert.equal(readSnooze(undefined).id, "ANN-1");
	} finally {
		delete globalThis.localStorage;
	}
});

test("readSnooze: malformed JSON -> null, never throws", () => {
	installLocalStorage();
	try {
		globalThis.localStorage.setItem(`${SNOOZE_KEY}:user@a`, "{not json");
		assert.equal(readSnooze("user@a"), null);
	} finally {
		delete globalThis.localStorage;
	}
});

test("readSnooze read-throw -> null (banner shows); writeSnooze write-throw -> no crash", () => {
	globalThis.localStorage = {
		getItem: () => {
			throw new Error("blocked");
		},
		setItem: () => {
			throw new Error("quota");
		},
		removeItem: () => {},
	};
	try {
		// A read that throws reads as not-snoozed -> bannerShouldShow(..., null) is true.
		const snooze = readSnooze("user@a");
		assert.equal(snooze, null);
		assert.equal(bannerShouldShow({ id: "ANN-1" }, NOW, snooze), true);
		// A write that throws is swallowed AND still returns the record.
		let rec;
		assert.doesNotThrow(() => {
			rec = writeSnooze({ id: "ANN-1", interval_days: 3 }, NOW, "user@a");
		});
		assert.deepEqual(rec, { id: "ANN-1", until: NOW + 3 * DAY });
	} finally {
		delete globalThis.localStorage;
	}
});

test("readSnooze/writeSnooze: localStorage absent -> null / returns record, no throw", () => {
	assert.equal(typeof globalThis.localStorage, "undefined");
	assert.equal(readSnooze("user@a"), null);
	assert.doesNotThrow(() => writeSnooze({ id: "ANN-1" }, NOW, "user@a"));
});
