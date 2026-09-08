import { test } from "node:test";
import assert from "node:assert/strict";
import { holdShouldShow, holdMessage, nextNotice } from "./maintenanceHold.js";

test("holdShouldShow: only when active", () => {
	assert.equal(holdShouldShow({ active: true }), true);
	assert.equal(holdShouldShow({ active: false }), false);
	assert.equal(holdShouldShow({}), false);
	assert.equal(holdShouldShow(null), false);
	assert.equal(holdShouldShow(undefined), false);
});

test("holdMessage: operator message wins when present", () => {
	assert.equal(holdMessage({ active: true, message: "Back at 3pm." }, "Aida"), "Back at 3pm.");
});

test("holdMessage: branded default when no message", () => {
	assert.equal(
		holdMessage({ active: true }, "Aida"),
		"Aida is upgrading and will be back shortly."
	);
	assert.equal(holdMessage({}, "Aida"), "Aida is upgrading and will be back shortly.");
});

test("holdMessage: white-label - blank/missing brand falls back to Jarvis", () => {
	const expected = "Jarvis is upgrading and will be back shortly.";
	assert.equal(holdMessage({}, ""), expected);
	assert.equal(holdMessage({}, "   "), expected);
	assert.equal(holdMessage({}), expected);
});

test("holdMessage: a whitespace-only operator message falls back to the branded default", () => {
	assert.equal(
		holdMessage({ message: "   " }, "Aida"),
		"Aida is upgrading and will be back shortly."
	);
});

test("nextNotice: a well-formed payload is authoritative (sets and clears)", () => {
	const cur = { active: true, message: "old" };
	assert.deepEqual(nextNotice(cur, { active: false }), { active: false, message: "" });
	assert.deepEqual(nextNotice(cur, { active: true, message: " up " }), {
		active: true,
		message: "up",
	});
});

test("nextNotice: a missing/malformed payload keeps the last-known notice (never clears on garbage)", () => {
	const cur = { active: true, message: "held" };
	assert.equal(nextNotice(cur, undefined), cur);
	assert.equal(nextNotice(cur, null), cur);
	assert.equal(nextNotice(cur, "nope"), cur);
	// A payload missing `active` entirely is UNKNOWN, not "inactive" - keep last-known
	// rather than let !!undefined silently flip a live hold off.
	assert.equal(nextNotice(cur, { message: "x" }), cur);
});
